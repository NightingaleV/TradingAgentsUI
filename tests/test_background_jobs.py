"""Durable refresh/evaluation queue behavior."""

from __future__ import annotations

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.persistence.run_repository import RunRepository
from tradingagents.runtime.background_runner import run_memory_refresh


def test_queue_claims_oldest_analysis_then_background_job(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WEBUI_DIR", str(tmp_path / "webui"))
    repo = RunRepository(tmp_path / "console.db")
    run, _ = repo.create_run(
        {"ticker": "SPY", "asset_type": "stock", "trade_date": "2026-01-01", "checkpoint_enabled": False},
        "run-hash",
        "analysis-token",
    )
    job, _ = repo.create_background_job("evaluation", {"tickers": ["NVDA"]}, {"llm_provider": "openai"}, "job-token")

    first = repo.claim_next_work_item("worker")
    assert first["work_source"] == "run" and first["id"] == run["id"]
    repo.fail_run(run["id"], "test", "continue")
    second = repo.claim_next_work_item("worker")
    assert second["work_source"] == "background" and second["id"] == job["id"]


def test_evaluation_cells_and_cancelled_jobs_can_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WEBUI_DIR", str(tmp_path / "webui"))
    repo = RunRepository(tmp_path / "console.db")
    job, _ = repo.create_background_job("evaluation", {}, {"llm_provider": "openai"}, "job-token")
    repo.upsert_evaluation_cell(job["id"], "NVDA", "2026-01-05", "pending", rating="Buy")
    assert repo.list_evaluation_cells(job["id"])[0]["rating"] == "Buy"
    repo.cancel_background_job(job["id"], {"message": "stopped"})
    assert repo.requeue_background_job(job["id"])
    assert repo.get_background_job(job["id"])["status"] == "queued"


def test_refresh_processes_every_ticker_and_keeps_unavailable_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WEBUI_DIR", str(tmp_path / "webui"))
    log_path = tmp_path / "memory.md"
    log = TradingMemoryLog({"memory_log_path": str(log_path)})
    log.store_decision("NVDA", "2026-01-05", "Rating: Buy")
    log.store_decision("AAPL", "2026-01-05", "Rating: Sell")
    repo = RunRepository(tmp_path / "console.db")
    job, _ = repo.create_background_job(
        "memory_refresh",
        {"scope": "all_pending"},
        {"memory_log_path": str(log_path), "selected_analysts": ["market"]},
        "refresh-token",
        total_units=2,
    )

    class FakeGraph:
        def __init__(self, config, selected_analysts):
            self.memory_log = TradingMemoryLog(config)

        def settle_pending(self, ticker):
            if ticker == "NVDA":
                self.memory_log.update_with_outcome(ticker, "2026-01-05", 0.05, 0.02, 5, "correct")

    monkeypatch.setattr("tradingagents.runtime.background_runner.TradingAgentsGraph", FakeGraph)
    result = run_memory_refresh(repo.get_background_job(job["id"]), repo)

    assert result["resolved"] == 1
    assert result["pending_after"] == 1
    assert [entry["ticker"] for entry in TradingMemoryLog({"memory_log_path": str(log_path)}).get_pending_entries()] == ["AAPL"]
