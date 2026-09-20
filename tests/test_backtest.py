"""Backtest grids stay isolated, resumable, and correctly scored."""

from __future__ import annotations

import pytest

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.backtest import iter_grid, run_backtest, summarize

DECISION = "**Rating**: Buy\n\nTest decision"


class _FakeGraph:
    instances: list[_FakeGraph] = []
    fail_on: set[tuple[str, str]] = set()

    def __init__(self, selected_analysts=None, config=None, **_kwargs):
        self.analysts = list(selected_analysts or [])
        self.config = config
        self.memory_log = TradingMemoryLog(config)
        self.calls: list[tuple[str, str]] = []
        self.settled: list[str] = []
        self.__class__.instances.append(self)

    def propagate(self, ticker, trade_date, asset_type="stock", portfolio=None):
        self.calls.append((ticker, trade_date))
        if (ticker, trade_date) in self.__class__.fail_on:
            raise RuntimeError("vendor exploded")
        self.memory_log.store_decision(ticker, trade_date, DECISION)
        return {"final_trade_decision": DECISION}, "Buy"

    def settle_pending(self, ticker):
        self.settled.append(ticker)


@pytest.fixture(autouse=True)
def fake_graph(monkeypatch):
    import tradingagents.backtest as backtest

    _FakeGraph.instances = []
    _FakeGraph.fail_on = set()
    monkeypatch.setattr(backtest, "TradingAgentsGraph", _FakeGraph)


def config(tmp_path):
    return {
        "results_dir": str(tmp_path / "results"),
        "memory_log_path": str(tmp_path / "live.md"),
    }


def test_grid_is_canonical_spaced_and_stops_today(monkeypatch):
    import tradingagents.backtest as backtest

    monkeypatch.setattr(backtest, "get_current_date", lambda: "2026-01-10")
    assert iter_grid("2026-01-05", "2026-01-20", 2) == ["2026-01-05", "2026-01-07", "2026-01-09"]
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        iter_grid("2026-1-5", "2026-01-20")


def test_private_log_and_resume_skip_completed_cells(tmp_path):
    first = run_backtest(["NVDA"], ["2026-01-05"], config(tmp_path), run_id="evaluation-one")
    again = run_backtest(
        ["NVDA"], ["2026-01-05", "2026-01-12"], config(tmp_path), run_id=first.run_id
    )

    assert not (tmp_path / "live.md").exists()
    assert again.cells_run == 1
    assert again.skipped == 1
    assert _FakeGraph.instances[-1].calls == [("NVDA", "2026-01-12")]
    assert _FakeGraph.instances[-1].settled == ["NVDA"]


def test_failed_cell_does_not_stop_grid_or_later_settlement(tmp_path):
    _FakeGraph.fail_on = {("NVDA", "2026-01-05")}

    result = run_backtest(["NVDA", "AAPL"], ["2026-01-05"], config(tmp_path))

    assert result.cells_run == 1
    assert result.failures == [("NVDA", "2026-01-05", "vendor exploded")]
    assert _FakeGraph.instances[-1].settled == ["NVDA", "AAPL"]


def test_summary_scores_direction_and_excludes_pending(tmp_path):
    log = TradingMemoryLog({"memory_log_path": str(tmp_path / "result.md")})
    log.store_decision("NVDA", "2026-01-05", "Rating: Buy")
    log.update_with_outcome("NVDA", "2026-01-05", 0.10, 0.04, 5, "good", "2026-01-12")
    log.store_decision("AAPL", "2026-01-05", "Rating: Sell")
    log.update_with_outcome("AAPL", "2026-01-05", -0.08, -0.03, 5, "good", "2026-01-12")
    log.store_decision("MSFT", "2026-01-05", "Rating: Buy")

    summary = summarize(log)

    assert summary.resolved == 2 and summary.pending == 1
    assert summary.by_rating["Buy"].hit_rate == 1.0
    assert summary.by_rating["Sell"].hit_rate == 1.0
