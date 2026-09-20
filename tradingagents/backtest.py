"""Evaluate independent TradingAgents decisions across a ticker/date grid.

The decision log is deliberately the results table.  A backtest receives a
private log path, so its temporary historical decisions can never become
lessons for the live decision journal.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.agents.utils.rating import RATING_REVIEW
from tradingagents.dataflows.utils import get_current_date, safe_ticker_component
from tradingagents.graph.trading_graph import TradingAgentsGraph

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, str, str | None], None]
CancelCheck = Callable[[], bool]


class BacktestCancelled(RuntimeError):
    """Raised when a caller asks to stop between independently-run cells."""


def _canonical(value: str) -> datetime:
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"grid dates must be in YYYY-MM-DD format, got {value!r}") from exc
    if parsed.strftime("%Y-%m-%d") != str(value):
        raise ValueError(f"grid dates must be in YYYY-MM-DD format, got {value!r}")
    return parsed


def iter_grid(start_date: str, end_date: str, every_n_days: int = 7) -> list[str]:
    """Return calendar-spaced analysis dates, stopping at the current date."""
    start, end = _canonical(start_date), _canonical(end_date)
    if every_n_days < 1:
        raise ValueError("every_n_days must be at least 1")
    if end < start:
        raise ValueError(f"the grid ends before it starts: {end_date} is before {start_date}")
    last = min(end, datetime.strptime(get_current_date(), "%Y-%m-%d"))
    dates: list[str] = []
    cursor = start
    while cursor <= last:
        dates.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=every_n_days)
    return dates


def _alpha(entry: dict[str, Any]) -> float | None:
    try:
        return float(str(entry.get("alpha") or "").strip().rstrip("%")) / 100
    except ValueError:
        return None


@dataclass
class BacktestResult:
    run_id: str
    log_path: Path
    cells_run: int = 0
    skipped: int = 0
    failures: list[tuple[str, str, str]] = field(default_factory=list)
    settlement_failures: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RatingScore:
    count: int
    hit_rate: float | None
    mean_alpha: float


@dataclass
class BacktestSummary:
    resolved: int
    pending: int
    by_rating: dict[str, RatingScore]
    unscored: int = 0
    holding: str = ""

    def render(self) -> str:
        lines = [
            f"Resolved cells: {self.resolved} · pending: {self.pending}"
            + (f" · unscored: {self.unscored}" if self.unscored else "")
        ]
        for rating, score in self.by_rating.items():
            direction = (
                f"called the direction {score.hit_rate:.0%}"
                if score.hit_rate is not None
                else "no direction claimed"
            )
            lines.append(
                f"- {rating}: n={score.count}, {direction}, "
                f"mean alpha {score.mean_alpha:+.2%} vs the benchmark"
            )
        if self.pending:
            lines.append("Pending cells are not scored above; retrying later settles eligible cells.")
        lines.append(
            f"Alpha is measured over {self.holding or 'the configured window'} after each analysis date. "
            "This is independent decision-quality research, not a portfolio simulation."
        )
        return "\n".join(lines)


_DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}


def run_backtest(
    tickers: list[str],
    dates: list[str],
    config: dict[str, Any],
    *,
    asset_type: str = "stock",
    portfolio: Any = None,
    selected_analysts: tuple[str, ...] | list[str] = ("market", "social", "news", "fundamentals"),
    run_id: str | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCheck | None = None,
) -> BacktestResult:
    """Run each independent cell in an isolated journal and score later.

    Reusing ``run_id`` resumes an interrupted grid: a cell whose decision is
    already present in that journal is skipped.  Callbacks run only between
    graph invocations, the safe cancellation boundary for the current engine.
    """
    if not tickers:
        raise ValueError("at least one ticker is required")
    if not dates:
        raise ValueError("at least one evaluation date is required")
    safe_run_id = safe_ticker_component(run_id or datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir = Path(config["results_dir"]) / "backtest" / safe_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_config = {
        **config,
        "results_dir": str(run_dir),
        "memory_log_path": str(run_dir / "trading_memory.md"),
        # Checkpoint state belongs to interactive single runs. The private
        # journal is the durable per-cell resume mechanism for evaluations.
        "checkpoint_enabled": False,
    }
    graph = TradingAgentsGraph(selected_analysts, config=run_config)
    result = BacktestResult(run_id=safe_run_id, log_path=Path(run_config["memory_log_path"]))
    done = {(entry["ticker"], entry["date"]) for entry in graph.memory_log.load_entries()}

    def check_cancelled() -> None:
        if cancelled and cancelled():
            raise BacktestCancelled("Evaluation cancelled after the current completed cell.")

    for ticker in tickers:
        for trade_date in dates:
            check_cancelled()
            if (ticker, trade_date) in done:
                result.skipped += 1
                if progress:
                    progress("skipped", ticker, trade_date, None)
                continue
            if progress:
                progress("running", ticker, trade_date, None)
            try:
                graph.propagate(ticker, trade_date, asset_type, portfolio=portfolio)
                result.cells_run += 1
                if progress:
                    progress("completed", ticker, trade_date, None)
            except Exception as exc:  # a single vendor/model failure must not kill the sweep
                logger.warning("Evaluation cell %s %s failed: %s", ticker, trade_date, exc)
                result.failures.append((ticker, trade_date, str(exc)))
                if progress:
                    progress("failed", ticker, trade_date, str(exc))

    for ticker in tickers:
        check_cancelled()
        try:
            graph.settle_pending(ticker)
            if progress:
                progress("settled", ticker, "", None)
        except Exception as exc:  # reflection calls are isolated per ticker
            logger.warning("Evaluation settlement for %s failed: %s", ticker, exc)
            result.settlement_failures.append((ticker, str(exc)))
            if progress:
                progress("settlement_failed", ticker, "", str(exc))
    return result


def summarize(memory_log: TradingMemoryLog) -> BacktestSummary:
    """Summarize settled alpha by the directional claim made in each rating."""
    entries = memory_log.load_entries()
    scored = [(entry, _alpha(entry)) for entry in entries if not entry["pending"] and entry["rating"] != RATING_REVIEW]
    scored = [(entry, alpha) for entry, alpha in scored if alpha is not None]
    by_rating: dict[str, RatingScore] = {}
    for rating in dict.fromkeys(entry["rating"] for entry, _ in scored):
        alphas = [alpha for entry, alpha in scored if entry["rating"] == rating]
        direction = _DIRECTION.get(rating, 0)
        by_rating[rating] = RatingScore(
            count=len(alphas),
            hit_rate=(sum(alpha * direction > 0 for alpha in alphas) / len(alphas)) if direction else None,
            mean_alpha=sum(alphas) / len(alphas),
        )
    unscored = sum(1 for entry in entries if entry["rating"] == RATING_REVIEW)
    holding_windows = {
        f"{entry['holding'][:-1]} trading days"
        for entry, _ in scored
        if str(entry.get("holding") or "").endswith("d")
    }
    return BacktestSummary(
        resolved=len(scored),
        pending=len(entries) - len(scored) - unscored,
        by_rating=by_rating,
        unscored=unscored,
        holding=", ".join(sorted(holding_windows)),
    )
