"""Durable worker handlers for memory settlement and decision evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import BacktestCancelled, run_backtest, summarize
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.persistence.run_repository import RunRepository
from tradingagents.portfolio import PortfolioContext


class BackgroundJobCancelled(RuntimeError):
    """A cancellation requested at a safe boundary between independent units."""


def _summary_dict(summary) -> dict[str, Any]:
    return {
        "resolved": summary.resolved,
        "pending": summary.pending,
        "unscored": summary.unscored,
        "holding": summary.holding,
        "by_rating": {
            rating: {
                "count": score.count,
                "hit_rate": score.hit_rate,
                "mean_alpha": score.mean_alpha,
            }
            for rating, score in summary.by_rating.items()
        },
    }


def _cancel_if_requested(repository: RunRepository, job_id: str) -> None:
    if repository.background_job_cancellation_requested(job_id):
        raise BackgroundJobCancelled("Job cancelled after the current completed unit.")


def run_memory_refresh(job: dict[str, Any], repository: RunRepository) -> dict[str, Any]:
    """Attempt every pending live-memory ticker without starting analyses."""
    job_id = job["id"]
    config = dict(job["config"])
    graph = TradingAgentsGraph(config=config, selected_analysts=config["selected_analysts"])
    before = graph.memory_log.get_pending_entries()
    tickers = list(dict.fromkeys(str(entry["ticker"]) for entry in before))
    repository.update_background_job(
        job_id,
        stage="Settling outcomes",
        total_units=len(tickers),
        pending_units=len(before),
        result={"pending_before": len(before), "tickers": tickers},
    )
    repository.emit_background_job_event(
        job_id, "started", {"pending_entries": len(before), "tickers": tickers}
    )
    failures: list[dict[str, str]] = []
    completed = 0
    for ticker in tickers:
        _cancel_if_requested(repository, job_id)
        repository.update_background_job(
            job_id, active_item=ticker, completed_units=completed, failed_units=len(failures)
        )
        repository.emit_background_job_event(job_id, "ticker_started", {"ticker": ticker})
        try:
            graph.settle_pending(ticker)
            completed += 1
            repository.emit_background_job_event(job_id, "ticker_finished", {"ticker": ticker})
        except Exception as exc:  # keep processing remaining independent tickers
            failures.append({"ticker": ticker, "reason": str(exc)})
            completed += 1
            repository.emit_background_job_event(
                job_id, "ticker_failed", {"ticker": ticker, "reason": str(exc)}
            )
    after = graph.memory_log.get_pending_entries()
    result = {
        "pending_before": len(before),
        "pending_after": len(after),
        "resolved": max(0, len(before) - len(after)),
        "tickers_checked": len(tickers),
        "failures": failures,
    }
    repository.update_background_job(
        job_id,
        stage="Finalizing",
        active_item="",
        completed_units=completed,
        failed_units=len(failures),
        pending_units=len(after),
        result=result,
    )
    return result


def _sync_evaluation_cells(job_id: str, log: TradingMemoryLog, repository: RunRepository) -> None:
    """Project the private Markdown journal into queryable UI rows."""
    for entry in log.load_entries():
        repository.upsert_evaluation_cell(
            job_id,
            entry["ticker"],
            entry["date"],
            "pending" if entry["pending"] else "resolved",
            rating=entry.get("rating"),
            raw_return=entry.get("raw"),
            alpha_return=entry.get("alpha"),
            holding_window=entry.get("holding"),
            resolution_date=entry.get("resolved"),
        )


def run_evaluation(job: dict[str, Any], repository: RunRepository) -> dict[str, Any]:
    """Run a private grid, persist progress, then project scores for the UI."""
    job_id = job["id"]
    request = dict(job["request"])
    config = dict(job["config"])
    root = Path(job["artifact_root"])
    root.mkdir(parents=True, exist_ok=True)
    config["results_dir"] = str(root)
    portfolio_data = request.get("portfolio")
    portfolio = PortfolioContext.model_validate(portfolio_data) if portfolio_data is not None else None
    completed, failures = 0, 0

    def progress(status: str, ticker: str, trade_date: str, reason: str | None) -> None:
        nonlocal completed, failures
        if status == "running":
            repository.upsert_evaluation_cell(job_id, ticker, trade_date, "running")
            active_item = f"{ticker} · {trade_date}"
        elif status == "failed":
            failures += 1
            completed += 1
            repository.upsert_evaluation_cell(
                job_id, ticker, trade_date, "failed", error_message=reason or "Cell failed"
            )
            active_item = ""
        elif status in {"completed", "skipped"}:
            completed += 1
            active_item = ""
        else:
            active_item = ticker
        repository.update_background_job(
            job_id,
            stage="Evaluating" if status not in {"settled", "settlement_failed"} else "Settling outcomes",
            active_item=active_item,
            completed_units=completed,
            failed_units=failures,
        )
        repository.emit_background_job_event(
            job_id, "cell_progress", {"status": status, "ticker": ticker, "trade_date": trade_date, "reason": reason}
        )

    repository.update_background_job(job_id, stage="Evaluating", total_units=len(request["tickers"]) * len(request["dates"]))
    repository.emit_background_job_event(
        job_id, "started", {"tickers": request["tickers"], "dates": request["dates"]}
    )
    try:
        result = run_backtest(
            request["tickers"],
            request["dates"],
            config,
            asset_type=request["asset_type"],
            portfolio=portfolio,
            selected_analysts=tuple(config["selected_analysts"]),
            run_id=job_id,
            progress=progress,
            cancelled=lambda: repository.background_job_cancellation_requested(job_id),
        )
    except BacktestCancelled as exc:
        log = TradingMemoryLog({"memory_log_path": str(root / "backtest" / job_id / "trading_memory.md")})
        _sync_evaluation_cells(job_id, log, repository)
        raise BackgroundJobCancelled(str(exc)) from exc

    log = TradingMemoryLog({"memory_log_path": str(result.log_path)})
    _sync_evaluation_cells(job_id, log, repository)
    summary = _summary_dict(summarize(log))
    payload = {
        "run_id": result.run_id,
        "log_path": str(result.log_path),
        "cells_run": result.cells_run,
        "skipped": result.skipped,
        "failures": [
            {"ticker": ticker, "trade_date": trade_date, "reason": reason}
            for ticker, trade_date, reason in result.failures
        ],
        "settlement_failures": [
            {"ticker": ticker, "reason": reason}
            for ticker, reason in result.settlement_failures
        ],
        "summary": summary,
    }
    (root / "evaluation_summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    repository.update_background_job(
        job_id,
        stage="Finalizing",
        active_item="",
        completed_units=result.cells_run + result.skipped + len(result.failures),
        failed_units=len(result.failures),
        pending_units=summary["pending"],
        result=payload,
    )
    return payload
