"""Durable portfolio defaults and per-run snapshots for the web console."""

from __future__ import annotations

from datetime import date

import pytest

from tradingagents.persistence.run_repository import RunRepository
from tradingagents.runtime.config_builder import build_run_request


def _draft(portfolio):
    return {
        "ticker": "NVDA",
        "trade_date": date.today().isoformat(),
        "analysts": ["market"],
        "output_language": "English",
        "research_depth": "Shallow",
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.6-luna",
        "deep_think_llm": "gpt-5.6",
        "checkpoint_enabled": True,
        "portfolio": portfolio,
    }


@pytest.mark.unit
def test_saved_portfolio_default_is_non_secret_and_removable(tmp_path):
    repository = RunRepository(tmp_path / "web.db")
    portfolio = {
        "cash": 500.0,
        "currency": "USD",
        "positions": [{"ticker": "NVDA", "quantity": 2}],
    }

    repository.set_setting("portfolio", portfolio)
    assert repository.get_settings()["portfolio"] == portfolio
    repository.delete_setting("portfolio")
    assert "portfolio" not in repository.get_settings()


@pytest.mark.unit
def test_queued_request_keeps_snapshot_when_saved_book_changes():
    saved_book = {"positions": [{"ticker": "NVDA", "quantity": 2}]}
    request = build_run_request(_draft(saved_book))
    saved_book["positions"][0]["quantity"] = 99

    assert request.portfolio["positions"][0]["quantity"] == 2.0


@pytest.mark.unit
def test_per_run_opt_out_is_serialized_as_no_context():
    request = build_run_request(_draft(None))
    assert request.portfolio is None
