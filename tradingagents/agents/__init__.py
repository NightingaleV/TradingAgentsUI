"""Lazy public agent exports.

Keeping package import lightweight lets read-only surfaces such as the decision
memory viewer load without initializing every LangChain agent implementation.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "create_fundamentals_analyst": (".analysts.fundamentals_analyst", "create_fundamentals_analyst"),
    "create_market_analyst": (".analysts.market_analyst", "create_market_analyst"),
    "create_news_analyst": (".analysts.news_analyst", "create_news_analyst"),
    "create_sentiment_analyst": (".analysts.sentiment_analyst", "create_sentiment_analyst"),
    "create_social_media_analyst": (".analysts.sentiment_analyst", "create_social_media_analyst"),
    "create_portfolio_manager": (".managers.portfolio_manager", "create_portfolio_manager"),
    "create_research_manager": (".managers.research_manager", "create_research_manager"),
    "create_bear_researcher": (".researchers.bear_researcher", "create_bear_researcher"),
    "create_bull_researcher": (".researchers.bull_researcher", "create_bull_researcher"),
    "create_aggressive_debator": (".risk_mgmt.aggressive_debator", "create_aggressive_debator"),
    "create_conservative_debator": (".risk_mgmt.conservative_debator", "create_conservative_debator"),
    "create_neutral_debator": (".risk_mgmt.neutral_debator", "create_neutral_debator"),
    "create_trader": (".trader.trader", "create_trader"),
    "AgentState": (".utils.agent_states", "AgentState"),
    "InvestDebateState": (".utils.agent_states", "InvestDebateState"),
    "RiskDebateState": (".utils.agent_states", "RiskDebateState"),
    "create_msg_delete": (".utils.agent_utils", "create_msg_delete"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
