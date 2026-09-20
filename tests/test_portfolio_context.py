"""Portfolio context stays optional, durable, and visible only to decision agents."""

from __future__ import annotations

import inspect
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.utils.agent_utils import get_portfolio_context_from_state
from tradingagents.portfolio import PortfolioContext, load_portfolio
from tradingagents.runtime.config_builder import build_run_request, request_hash

HOLDING = {
    "cash": 25000.0,
    "currency": "USD",
    "positions": [
        {"ticker": "AAPL", "quantity": 120, "average_price": 150.0},
        {"ticker": "MSFT", "quantity": 10},
    ],
}


def _draft(portfolio):
    return {
        "ticker": "AAPL",
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
def test_render_leads_with_target_holding_and_includes_other_context():
    text = PortfolioContext.model_validate(HOLDING).render("aapl")
    assert "Current position in AAPL: 120" in text
    assert "average price 150.00" in text
    assert "MSFT 10" in text
    assert "25,000.00 USD" in text


@pytest.mark.unit
def test_flat_book_and_missing_context_are_not_conflated():
    flat = PortfolioContext.model_validate({"positions": []}).render("AAPL")
    missing = get_portfolio_context_from_state({"company_of_interest": "AAPL"})
    assert "No current position in AAPL" in flat
    assert "not provided" in missing.lower()
    assert "no current position" not in missing.lower()


@pytest.mark.unit
def test_partial_book_does_not_invent_cash():
    text = PortfolioContext.model_validate(
        {"positions": [{"ticker": "AAPL", "quantity": -5}]}
    ).render("AAPL")
    assert "-5" in text
    assert "Cash" not in text


@pytest.mark.unit
def test_load_portfolio_validates_json(tmp_path):
    valid = tmp_path / "book.json"
    valid.write_text(json.dumps(HOLDING), encoding="utf-8")
    assert load_portfolio(valid).position_in("AAPL").quantity == 120

    malformed = tmp_path / "bad.json"
    malformed.write_text('{"positions": [{"quantity": 5}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="portfolio"):
        load_portfolio(malformed)


@pytest.mark.unit
def test_run_request_serializes_book_and_hashes_each_distinct_context():
    missing = build_run_request(_draft(None))
    flat = build_run_request(_draft({"positions": []}))
    held = build_run_request(_draft(HOLDING))

    assert missing.portfolio is None
    assert flat.portfolio == {"cash": None, "currency": None, "positions": []}
    assert held.portfolio["positions"][0]["ticker"] == "AAPL"
    assert len({request_hash(missing), request_hash(flat), request_hash(held)}) == 3


def _bare_graph(tmp_path):
    from tradingagents.agents.utils.memory import TradingMemoryLog
    from tradingagents.graph.propagation import Propagator
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "memory_log_path": str(tmp_path / "memory.md"),
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    }
    graph.memory_log = TradingMemoryLog(graph.config)
    graph.propagator = Propagator()
    graph.selected_analysts = ("market",)
    graph.resolve_pending_entries = lambda ticker: None
    graph.resolve_instrument_context = lambda ticker, asset_type="stock": ""
    graph.memory_as_of = lambda trade_date: None
    return graph


@pytest.mark.unit
def test_graph_state_and_checkpoint_signature_include_portfolio(tmp_path):
    graph = _bare_graph(tmp_path)
    book = PortfolioContext.model_validate(HOLDING)

    state = graph.create_run_state("AAPL", "2026-08-14", portfolio=book)
    assert "120" in state["portfolio_context"]
    assert graph.create_run_state("AAPL", "2026-08-14")["portfolio_context"] == ""
    assert len(
        {
            graph.run_signature("stock"),
            graph.run_signature("stock", PortfolioContext()),
            graph.run_signature("stock", book),
        }
    ) == 3


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module_name", "factory_name"),
    [
        ("tradingagents.agents.trader.trader", "create_trader"),
        ("tradingagents.agents.managers.portfolio_manager", "create_portfolio_manager"),
        ("tradingagents.agents.risk_mgmt.aggressive_debator", "create_aggressive_debator"),
        ("tradingagents.agents.risk_mgmt.conservative_debator", "create_conservative_debator"),
        ("tradingagents.agents.risk_mgmt.neutral_debator", "create_neutral_debator"),
    ],
)
def test_only_decision_agents_receive_portfolio_context(module_name, factory_name):
    module = __import__(module_name, fromlist=[factory_name])
    prompts = []

    class LLM:
        def with_structured_output(self, *args, **kwargs):
            raise NotImplementedError

        def invoke(self, prompt, *args, **kwargs):
            prompts.append(str(prompt))
            return MagicMock(content="Rating: Hold\n\nNo action.")

    state = {
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
        "portfolio_context": "PORTFOLIO_BLOCK_MARKER",
        "market_report": "M",
        "sentiment_report": "S",
        "news_report": "N",
        "fundamentals_report": "F",
        "investment_plan": "P",
        "trader_investment_plan": "T",
        "past_context": "",
        "risk_debate_state": {
            "history": "",
            "latest_speaker": "",
            "count": 0,
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
        },
    }
    getattr(module, factory_name)(LLM())(state)
    assert any("PORTFOLIO_BLOCK_MARKER" in prompt for prompt in prompts)


@pytest.mark.unit
def test_research_agents_remain_blind_to_portfolio_context():
    from tradingagents.agents.researchers import bear_researcher, bull_researcher

    assert "portfolio_context" not in inspect.getsource(bull_researcher)
    assert "portfolio_context" not in inspect.getsource(bear_researcher)


@pytest.mark.unit
def test_cli_loads_book_before_starting_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import cli.main as cli

    book = tmp_path / "book.json"
    book.write_text(json.dumps(HOLDING), encoding="utf-8")
    received = []
    monkeypatch.setattr(cli, "run_analysis", lambda **kwargs: received.append(kwargs))

    result = CliRunner().invoke(cli.app, ["--portfolio", str(book)])
    assert result.exit_code == 0
    assert received[0]["portfolio"].position_in("AAPL").quantity == 120
