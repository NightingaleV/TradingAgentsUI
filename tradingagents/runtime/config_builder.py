"""Validation and immutable effective-config construction for analysis runs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.provider_catalog import provider_metadata, provider_models

from .models import RunRequest


ANALYST_ORDER = ("market", "social", "news", "fundamentals")
CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH")
TICKER_RE = re.compile(r"^[A-Za-z0-9._^=\-]{1,32}$")
DEPTH_ROUNDS = {"Shallow": 1, "Medium": 3, "Deep": 5}


def canonicalize_ticker(value: str) -> tuple[str, str]:
    ticker_input = value.strip() or "SPY"
    if not TICKER_RE.fullmatch(ticker_input):
        raise ValueError("Ticker may contain only letters, numbers, period, underscore, hyphen, ^, or = (32 characters maximum).")
    canonical = normalize_symbol(ticker_input)
    asset_type = "crypto" if canonical.endswith(CRYPTO_SUFFIXES) else "stock"
    return canonical, asset_type


def _optional_int(value: Any, *, positive: bool = False) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    if parsed < (1 if positive else 0):
        raise ValueError("This value must be positive." if positive else "This value cannot be negative.")
    return parsed


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 2:
        raise ValueError("Temperature must be a finite number from 0 to 2.")
    return parsed


def build_run_request(draft: dict[str, Any]) -> RunRequest:
    ticker, asset_type = canonicalize_ticker(str(draft.get("ticker", "SPY")))
    trade_date = str(draft.get("trade_date") or date.today().isoformat())
    try:
        parsed_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("As-of date must use YYYY-MM-DD.") from exc
    if parsed_date > date.today():
        raise ValueError("As-of date cannot be in the future relative to the server.")

    raw_analysts = draft.get("analysts") or []
    analysts = tuple(key for key in ANALYST_ORDER if key in raw_analysts)
    if asset_type == "crypto":
        analysts = tuple(key for key in analysts if key != "fundamentals")
    if not analysts:
        raise ValueError("Select at least one analyst.")

    provider = str(draft.get("llm_provider") or DEFAULT_CONFIG["llm_provider"]).lower()
    metadata = provider_metadata(provider)
    backend_url = str(draft.get("backend_url") or metadata.backend_url or "").strip() or None
    if provider == "openai_compatible" and not backend_url:
        raise ValueError("A backend URL is required for an OpenAI-compatible endpoint.")
    if backend_url:
        parsed = urlparse(backend_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must start with http:// or https:// and include a host.")

    quick = str(draft.get("quick_think_llm") or "").strip()
    deep = str(draft.get("deep_think_llm") or "").strip()
    if not quick or quick == "custom":
        quick = str(draft.get("custom_quick_model") or "").strip()
    if not deep or deep == "custom":
        deep = str(draft.get("custom_deep_model") or "").strip()
    if not quick or not deep:
        raise ValueError("Quick and deep model IDs are required.")

    depth = str(draft.get("research_depth") or "Shallow")
    rounds = DEPTH_ROUNDS.get(depth, 1)
    debate_rounds = int(draft.get("max_debate_rounds") or rounds)
    risk_rounds = int(draft.get("max_risk_discuss_rounds") or rounds)
    if not 1 <= debate_rounds <= 10 or not 1 <= risk_rounds <= 10:
        raise ValueError("Debate and risk rounds must be between 1 and 10.")

    language = str(draft.get("output_language") or "English").strip()
    if language == "Custom":
        language = str(draft.get("custom_language") or "").strip()
    if not language:
        raise ValueError("Output language cannot be empty.")

    vendors = copy.deepcopy(DEFAULT_CONFIG.get("data_vendors", {}))
    vendors.update(draft.get("data_vendors") or {})
    allowed_vendors = {
        "core_stock_apis": {"yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"},
        "technical_indicators": {"yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"},
        "fundamental_data": {"yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"},
        "news_data": {"yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"},
        "macro_data": {"fred"},
        "prediction_markets": {"polymarket"},
    }
    for category, vendor in vendors.items():
        if category in allowed_vendors and vendor not in allowed_vendors[category]:
            raise ValueError(f"Unsupported vendor chain for {category}: {vendor}")

    benchmark = str(draft.get("benchmark_ticker") or "").strip() or None
    if benchmark and not TICKER_RE.fullmatch(benchmark):
        raise ValueError("Benchmark ticker contains unsupported characters.")

    return RunRequest(
        ticker_input=str(draft.get("ticker", ticker)).strip() or "SPY",
        ticker=ticker,
        trade_date=trade_date,
        asset_type=asset_type,
        analysts=analysts,
        output_language=language,
        llm_provider=provider,
        quick_think_llm=quick,
        deep_think_llm=deep,
        backend_url=backend_url,
        max_debate_rounds=debate_rounds,
        max_risk_discuss_rounds=risk_rounds,
        checkpoint_enabled=bool(draft.get("checkpoint_enabled", True)),
        google_thinking_level=(str(draft.get("google_thinking_level") or "").strip() or None),
        openai_reasoning_effort=(str(draft.get("openai_reasoning_effort") or "").strip() or None),
        anthropic_effort=(str(draft.get("anthropic_effort") or "").strip() or None),
        temperature=_optional_float(draft.get("temperature")),
        llm_max_retries=_optional_int(draft.get("llm_max_retries")),
        max_tokens=_optional_int(draft.get("max_tokens"), positive=True),
        benchmark_ticker=normalize_symbol(benchmark) if benchmark else None,
        data_vendors=vendors,
    )


def effective_graph_config(request: RunRequest) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in request.to_dict().items():
        if key in config and key not in {"ticker", "ticker_input", "trade_date", "asset_type", "analysts"}:
            config[key] = copy.deepcopy(value)
    config["selected_analysts"] = list(request.analysts)
    config["data_vendors"] = copy.deepcopy(request.data_vendors)
    return config


def request_hash(request: RunRequest) -> str:
    payload = request.to_dict()
    payload.pop("ticker_input", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def model_choices(provider: str, mode: str) -> list[dict[str, str]]:
    return [{"label": label, "value": value} for label, value in provider_models(provider, mode)]
