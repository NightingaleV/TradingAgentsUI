"""Reflex state backed exclusively by durable application services."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import reflex as rx

from tradingagents.default_config import DEFAULT_CONFIG, _ENV_OVERRIDES
from tradingagents.llm_clients.provider_catalog import (
    credential_status,
    list_providers,
    provider_metadata,
    provider_models,
)
from tradingagents.persistence.database import database_path, webui_root
from tradingagents.persistence.run_repository import RunRepository
from tradingagents.persistence.secret_store import KNOWN_SECRET_NAMES, load_secrets, store_secret
from tradingagents.runtime.config_builder import build_run_request, request_hash


ANALYST_LABELS = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
REPORT_TITLES = {
    "market_report": "Market Analyst",
    "sentiment_report": "Sentiment Analyst",
    "news_report": "News Analyst",
    "fundamentals_report": "Fundamentals Analyst",
    "bull_history": "Bull Researcher",
    "bear_history": "Bear Researcher",
    "research_manager_decision": "Research Manager decision",
    "investment_plan": "Research plan",
    "trader_investment_plan": "Trader transaction proposal",
    "aggressive_history": "Aggressive risk view",
    "conservative_history": "Conservative risk view",
    "neutral_history": "Neutral risk view",
    "portfolio_manager_decision": "Portfolio Manager decision",
    "final_trade_decision": "Final portfolio decision",
}
REPORT_ORDER = tuple(REPORT_TITLES)
PROVIDER_LABEL_TO_KEY = {item["label"]: item["key"] for item in list_providers()}
PROVIDER_KEY_TO_LABEL = {value: key for key, value in PROVIDER_LABEL_TO_KEY.items()}


def _repo() -> RunRepository:
    return RunRepository()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration(run: dict[str, Any]) -> str:
    start = _parse_time(run.get("started_at") or run.get("created_at"))
    end = _parse_time(run.get("finished_at")) or datetime.now(timezone.utc)
    if not start:
        return "—"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    seconds = max(0, int((end - start).total_seconds()))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _run_view(run: dict[str, Any]) -> dict[str, Any]:
    config = run.get("config", {})
    analysts = config.get("analysts", [])
    stage_index = {"Analysts": 0, "Research": 1, "Trader": 2, "Risk": 3, "Portfolio": 4}.get(run.get("stage"), -1)
    return {
        **run,
        "signal": run.get("signal") or "",
        "error_message": run.get("error_message") or "",
        "status_label": str(run.get("status", "unknown")).replace("_", " ").upper(),
        "signal_label": run.get("signal") or "PENDING",
        "provider": config.get("llm_provider", "—"),
        "models": f"{config.get('quick_think_llm', '—')} / {config.get('deep_think_llm', '—')}",
        "analysts_label": ", ".join(ANALYST_LABELS.get(item, item) for item in analysts),
        "depth_label": f"{config.get('max_debate_rounds', 1)} / {config.get('max_risk_discuss_rounds', 1)} rounds",
        "duration": _duration(run),
        "created_label": (run.get("created_at") or "").replace("T", " ")[:16],
        "trade_date_label": run.get("trade_date") or "—",
        "active_label": run.get("active_agent") or run.get("stage") or "Queued",
        "stage_index": stage_index,
        "href": f"/runs/{run['id']}",
    }


def _model_labels(provider: str, mode: str) -> tuple[list[str], dict[str, str]]:
    options = provider_models(provider, mode)
    labels = [label for label, _ in options]
    mapping = {label: value for label, value in options}
    return labels, mapping


def _label_for_model(provider: str, mode: str, value: str) -> str:
    for label, model in provider_models(provider, mode):
        if model == value:
            return label
    return "Custom model ID"


class AppState(rx.State):
    # Shared app data.
    dashboard_counts: dict[str, int] = {"active": 0, "queued": 0, "completed_30d": 0, "failed_today": 0}
    chart_data: list[dict[str, Any]] = []
    active_runs: list[dict[str, Any]] = []
    recent_runs: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    announcement: str = ""
    announcement_checked: bool = False
    app_error: str = ""
    toast_message: str = ""

    # New-analysis draft.
    ticker: str = "SPY"
    trade_date: str = date.today().isoformat()
    output_language: str = "English"
    custom_language: str = ""
    analysts: list[str] = ["market", "social", "news", "fundamentals"]
    research_depth: str = "Shallow"
    llm_provider: str = str(DEFAULT_CONFIG["llm_provider"])
    provider_label: str = PROVIDER_KEY_TO_LABEL.get(str(DEFAULT_CONFIG["llm_provider"]), str(DEFAULT_CONFIG["llm_provider"]))
    provider_options: list[str] = list(PROVIDER_LABEL_TO_KEY)
    backend_url: str = str(DEFAULT_CONFIG.get("backend_url") or provider_metadata(str(DEFAULT_CONFIG["llm_provider"])).backend_url or "")
    quick_think_llm: str = str(DEFAULT_CONFIG["quick_think_llm"])
    deep_think_llm: str = str(DEFAULT_CONFIG["deep_think_llm"])
    quick_model_label: str = ""
    deep_model_label: str = ""
    quick_model_options: list[str] = []
    deep_model_options: list[str] = []
    custom_quick_model: str = ""
    custom_deep_model: str = ""
    reasoning_control: str = "medium"
    checkpoint_enabled: bool = True
    advanced_open: bool = False
    max_debate_rounds: str = "1"
    max_risk_discuss_rounds: str = "1"
    temperature: str = ""
    llm_max_retries: str = ""
    max_tokens: str = ""
    benchmark_ticker: str = ""
    core_vendor: str = "yfinance"
    technical_vendor: str = "yfinance"
    fundamental_vendor: str = "yfinance"
    news_vendor: str = "yfinance"
    review_ready: bool = False
    review_config: dict[str, Any] = {}
    submission_token: str = ""
    form_error: str = ""
    credential_hint: str = ""

    # Run history filters.
    filter_ticker: str = ""
    filter_status: str = ""
    filter_signal: str = ""
    filter_provider: str = ""
    filter_date_from: str = ""
    filter_date_to: str = ""
    filter_created_from: str = ""
    filter_created_to: str = ""

    # Run detail.
    selected_run_id: str = ""
    current_run: dict[str, Any] = {}
    agent_statuses: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    overview_reports: list[dict[str, Any]] = []
    debate_reports: list[dict[str, Any]] = []
    activity: list[dict[str, Any]] = []
    config_rows: list[dict[str, str]] = []
    artifacts: list[dict[str, str]] = []
    can_resume: bool = False
    last_event_sequence: int = 0

    # Memory.
    memory_entries: list[dict[str, Any]] = []
    memory_ticker: str = ""
    memory_status: str = ""
    memory_rating: str = ""
    memory_date_from: str = ""
    memory_date_to: str = ""

    # Settings.
    settings_rows: list[dict[str, str]] = []
    credentials: list[dict[str, Any]] = []
    secret_name: str = "OPENAI_API_KEY"
    secret_value: str = ""
    secret_names: list[str] = sorted(KNOWN_SECRET_NAMES)

    @rx.event
    def set_ticker(self, value: str):
        self.ticker = value
        self.review_ready = False

    @rx.event
    def set_trade_date(self, value: str):
        self.trade_date = value
        self.review_ready = False

    @rx.event
    def set_output_language(self, value: str):
        self.output_language = value
        self.review_ready = False

    @rx.event
    def set_custom_language(self, value: str):
        self.custom_language = value
        self.review_ready = False

    @rx.event
    def set_checkpoint_enabled(self, value: bool):
        self.checkpoint_enabled = value
        self.review_ready = False

    @rx.event
    def set_max_debate_rounds(self, value: str):
        self.max_debate_rounds = value
        self.review_ready = False

    @rx.event
    def set_max_risk_discuss_rounds(self, value: str):
        self.max_risk_discuss_rounds = value
        self.review_ready = False

    @rx.event
    def set_temperature(self, value: str):
        self.temperature = value
        self.review_ready = False

    @rx.event
    def set_llm_max_retries(self, value: str):
        self.llm_max_retries = value
        self.review_ready = False

    @rx.event
    def set_max_tokens(self, value: str):
        self.max_tokens = value
        self.review_ready = False

    @rx.event
    def set_benchmark_ticker(self, value: str):
        self.benchmark_ticker = value
        self.review_ready = False

    @rx.event
    def set_core_vendor(self, value: str):
        self.core_vendor = value
        self.review_ready = False

    @rx.event
    def set_technical_vendor(self, value: str):
        self.technical_vendor = value
        self.review_ready = False

    @rx.event
    def set_fundamental_vendor(self, value: str):
        self.fundamental_vendor = value
        self.review_ready = False

    @rx.event
    def set_news_vendor(self, value: str):
        self.news_vendor = value
        self.review_ready = False

    @rx.event
    def set_filter_ticker(self, value: str):
        self.filter_ticker = value

    @rx.event
    def set_filter_provider(self, value: str):
        self.filter_provider = value

    @rx.event
    def set_filter_date_from(self, value: str):
        self.filter_date_from = value

    @rx.event
    def set_filter_date_to(self, value: str):
        self.filter_date_to = value

    @rx.event
    def set_filter_created_from(self, value: str):
        self.filter_created_from = value

    @rx.event
    def set_filter_created_to(self, value: str):
        self.filter_created_to = value

    @rx.event
    def set_memory_ticker(self, value: str):
        self.memory_ticker = value

    @rx.event
    def set_memory_date_from(self, value: str):
        self.memory_date_from = value

    @rx.event
    def set_memory_date_to(self, value: str):
        self.memory_date_to = value

    @rx.event
    def set_secret_name(self, value: str):
        self.secret_name = value

    @rx.event
    def set_secret_value(self, value: str):
        self.secret_value = value

    @rx.event
    def load_dashboard(self):
        self.selected_run_id = ""
        if self.announcement:
            self.announcement = re.sub(r"\[/?(?:bold|link(?:=[^\]]+)?)\]", "", self.announcement).strip(" ·")
        repository = _repo()
        self.dashboard_counts = repository.dashboard_counts()
        all_runs = repository.list_runs(limit=30)
        self.active_runs = [_run_view(run) for run in all_runs if run["status"] in {"queued", "running", "cancel_requested"}][:5]
        self.recent_runs = [_run_view(run) for run in all_runs if run["status"] == "completed"][:5]
        self.chart_data = repository.seven_day_volume()
        self._load_health(repository)
        if not self.announcement_checked:
            self.announcement_checked = True
            try:
                import requests
                response = requests.get("https://api.tauric.ai/v1/announcements", timeout=1)
                if response.ok:
                    messages = response.json().get("announcements", [])
                    rendered = " · ".join(str(message) for message in messages[:2])
                    self.announcement = re.sub(r"\[/?(?:bold|link(?:=[^\]]+)?)\]", "", rendered).strip(" ·")
            except Exception:
                self.announcement = ""

    def _load_health(self, repository: RunRepository | None = None) -> None:
        repository = repository or _repo()
        lease = repository.worker_lease()
        heartbeat = _parse_time(lease.get("heartbeat_at") if lease else None)
        worker_online = False
        if heartbeat:
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            worker_online = (datetime.now(timezone.utc) - heartbeat).total_seconds() < 12
        root = webui_root()
        root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(root)
        secrets = load_secrets()
        provider = self.llm_provider or DEFAULT_CONFIG["llm_provider"]
        credential = credential_status(provider, secrets)
        ollama_endpoint = provider_metadata("ollama").backend_url or "http://localhost:11434/v1"
        ollama_ok = False
        if provider == "ollama":
            try:
                request = Request(f"{ollama_endpoint.rstrip('/')}/models", method="GET")
                with urlopen(request, timeout=1.25) as response:
                    ollama_ok = 200 <= response.status < 300
            except (OSError, URLError, ValueError):
                ollama_ok = False
        self.health = {
            "worker_online": worker_online,
            "worker_label": "Online" if worker_online else "Unavailable",
            "worker_note": f"Active: {lease.get('active_run_id')[:8]}" if lease and lease.get("active_run_id") else "Waiting for heartbeat",
            "database_ok": os.access(database_path().parent, os.W_OK),
            "database_path": str(database_path()),
            "storage_ok": os.access(root, os.W_OK),
            "storage_free": f"{usage.free / (1024 ** 3):.1f} GB free",
            "provider": provider,
            "credential_ok": credential["configured"] or not credential["required"],
            "credential_label": "Configured" if credential["configured"] else ("Optional" if not credential["required"] else "Missing"),
            "credential_env": credential.get("env") or "Credential chain / keyless",
            "queue": repository.dashboard_counts()["queued"],
            "ollama_endpoint": ollama_endpoint,
            "ollama_ok": ollama_ok,
            "ollama_label": "Reachable" if ollama_ok else ("Unavailable" if provider == "ollama" else "Not selected"),
            "version": _app_version(),
            "commit": _repository_commit(),
        }

    @rx.event
    def load_new_analysis(self):
        self.selected_run_id = ""
        settings = _repo().get_settings()
        self.llm_provider = str(settings.get("llm_provider", DEFAULT_CONFIG["llm_provider"]))
        self.provider_label = PROVIDER_KEY_TO_LABEL.get(self.llm_provider, self.llm_provider)
        self.backend_url = str(settings.get("backend_url") or provider_metadata(self.llm_provider).backend_url or "")
        self.quick_think_llm = str(settings.get("quick_think_llm", DEFAULT_CONFIG["quick_think_llm"]))
        self.deep_think_llm = str(settings.get("deep_think_llm", DEFAULT_CONFIG["deep_think_llm"]))
        self.output_language = str(settings.get("output_language", DEFAULT_CONFIG["output_language"]))
        self.analysts = list(settings.get("selected_analysts", ["market", "social", "news", "fundamentals"]))
        self.research_depth = str(settings.get("research_depth", "Shallow"))
        default_rounds = {"Shallow": "1", "Medium": "3", "Deep": "5"}.get(self.research_depth, "1")
        self.max_debate_rounds = str(settings.get("max_debate_rounds", default_rounds))
        self.max_risk_discuss_rounds = str(settings.get("max_risk_discuss_rounds", default_rounds))
        self.checkpoint_enabled = bool(settings.get("checkpoint_enabled", True))
        self.temperature = "" if settings.get("temperature") is None else str(settings["temperature"])
        self.llm_max_retries = "" if settings.get("llm_max_retries") is None else str(settings["llm_max_retries"])
        self.max_tokens = "" if settings.get("max_tokens") is None else str(settings["max_tokens"])
        self.benchmark_ticker = str(settings.get("benchmark_ticker") or "")
        vendors = settings.get("data_vendors") or {}
        self.core_vendor = str(vendors.get("core_stock_apis", "yfinance"))
        self.technical_vendor = str(vendors.get("technical_indicators", "yfinance"))
        self.fundamental_vendor = str(vendors.get("fundamental_data", "yfinance"))
        self.news_vendor = str(vendors.get("news_data", "yfinance"))
        reasoning_key = {
            "google": "google_thinking_level",
            "openai": "openai_reasoning_effort",
            "anthropic": "anthropic_effort",
        }.get(self.llm_provider)
        self.reasoning_control = str(settings.get(reasoning_key, "medium") or "medium") if reasoning_key else "medium"
        self._refresh_model_options()
        self.review_ready = False
        self.form_error = ""

    def _refresh_model_options(self) -> None:
        quick_labels, _ = _model_labels(self.llm_provider, "quick")
        deep_labels, _ = _model_labels(self.llm_provider, "deep")
        self.quick_model_options = quick_labels
        self.deep_model_options = deep_labels
        self.quick_model_label = _label_for_model(self.llm_provider, "quick", self.quick_think_llm)
        self.deep_model_label = _label_for_model(self.llm_provider, "deep", self.deep_think_llm)
        if self.quick_model_label == "Custom model ID":
            self.custom_quick_model = self.quick_think_llm
        if self.deep_model_label == "Custom model ID":
            self.custom_deep_model = self.deep_think_llm

    @rx.event
    def set_provider(self, label: str):
        provider = PROVIDER_LABEL_TO_KEY.get(label, label)
        self.provider_label = label
        self.llm_provider = provider
        metadata = provider_metadata(provider)
        self.backend_url = metadata.backend_url or ""
        quick = provider_models(provider, "quick")
        deep = provider_models(provider, "deep")
        self.quick_think_llm = quick[0][1]
        self.deep_think_llm = deep[0][1]
        self._refresh_model_options()
        repository = _repo()
        repository.set_setting("llm_provider", provider)
        repository.set_setting("backend_url", self.backend_url)
        repository.set_setting("quick_think_llm", self.quick_think_llm)
        repository.set_setting("deep_think_llm", self.deep_think_llm)
        self.review_ready = False

    @rx.event
    def set_backend_url(self, value: str):
        self.backend_url = value
        _repo().set_setting("backend_url", value.strip() or None)
        self.review_ready = False

    @rx.event
    def set_custom_quick_model(self, value: str):
        self.custom_quick_model = value
        if self.quick_model_label == "Custom model ID":
            self.quick_think_llm = value.strip() or "custom"
            if value.strip():
                _repo().set_setting("quick_think_llm", value.strip())
        self.review_ready = False

    @rx.event
    def set_custom_deep_model(self, value: str):
        self.custom_deep_model = value
        if self.deep_model_label == "Custom model ID":
            self.deep_think_llm = value.strip() or "custom"
            if value.strip():
                _repo().set_setting("deep_think_llm", value.strip())
        self.review_ready = False

    @rx.event
    def set_quick_model_choice(self, label: str):
        self.quick_model_label = label
        mapping = dict(provider_models(self.llm_provider, "quick"))
        self.quick_think_llm = mapping.get(label, "custom")
        if self.quick_think_llm != "custom":
            _repo().set_setting("quick_think_llm", self.quick_think_llm)
        self.review_ready = False

    @rx.event
    def set_deep_model_choice(self, label: str):
        self.deep_model_label = label
        mapping = dict(provider_models(self.llm_provider, "deep"))
        self.deep_think_llm = mapping.get(label, "custom")
        if self.deep_think_llm != "custom":
            _repo().set_setting("deep_think_llm", self.deep_think_llm)
        self.review_ready = False

    @rx.event
    def toggle_analyst(self, key: str, checked: bool):
        values = list(self.analysts)
        if checked and key not in values:
            values.append(key)
        if not checked and key in values:
            values.remove(key)
        self.analysts = [item for item in ANALYST_LABELS if item in values]
        self.review_ready = False

    @rx.event
    def set_depth(self, value: str | list[str]):
        selected = value[0] if isinstance(value, list) else value
        self.research_depth = selected
        rounds = {"Shallow": "1", "Medium": "3", "Deep": "5"}[selected]
        self.max_debate_rounds = rounds
        self.max_risk_discuss_rounds = rounds
        self.review_ready = False

    @rx.event
    def set_reasoning_control(self, value: str | list[str]):
        self.reasoning_control = value[0] if isinstance(value, list) else value
        self.review_ready = False

    def _draft(self) -> dict[str, Any]:
        reasoning = self.reasoning_control or None
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "output_language": self.output_language,
            "custom_language": self.custom_language,
            "analysts": self.analysts,
            "research_depth": self.research_depth,
            "llm_provider": self.llm_provider,
            "backend_url": self.backend_url,
            "quick_think_llm": self.quick_think_llm,
            "deep_think_llm": self.deep_think_llm,
            "custom_quick_model": self.custom_quick_model,
            "custom_deep_model": self.custom_deep_model,
            "google_thinking_level": reasoning if self.llm_provider == "google" else None,
            "openai_reasoning_effort": reasoning if self.llm_provider == "openai" else None,
            "anthropic_effort": reasoning if self.llm_provider == "anthropic" else None,
            "checkpoint_enabled": self.checkpoint_enabled,
            "max_debate_rounds": self.max_debate_rounds,
            "max_risk_discuss_rounds": self.max_risk_discuss_rounds,
            "temperature": self.temperature,
            "llm_max_retries": self.llm_max_retries,
            "max_tokens": self.max_tokens,
            "benchmark_ticker": self.benchmark_ticker,
            "data_vendors": {
                "core_stock_apis": self.core_vendor,
                "technical_indicators": self.technical_vendor,
                "fundamental_data": self.fundamental_vendor,
                "news_data": self.news_vendor,
            },
        }

    @rx.event
    def review_configuration(self):
        try:
            request = build_run_request(self._draft())
        except (ValueError, TypeError) as exc:
            self.form_error = str(exc)
            self.review_ready = False
            return
        self.review_config = request.to_dict()
        self.submission_token = str(uuid.uuid4())
        credential = credential_status(request.llm_provider, load_secrets())
        self.credential_hint = "" if credential["configured"] or not credential["required"] else f"{credential['env']} is required before this run can be queued."
        self.form_error = ""
        self.review_ready = True

    @rx.event
    def queue_analysis(self):
        if not self.review_ready or not self.review_config:
            self.form_error = "Review the configuration before queueing."
            return
        request = build_run_request(self.review_config)
        credential = credential_status(request.llm_provider, load_secrets())
        if credential["required"] and not credential["configured"]:
            self.form_error = f"{credential['env']} is required. Add it in Settings or the Compose .env file."
            return
        repository = _repo()
        run, _ = repository.create_run(
            request.to_dict(),
            request_hash(request),
            self.submission_token or str(uuid.uuid4()),
            app_version=_app_version(),
            repository_commit=_repository_commit(),
        )
        for key, value in {
            "llm_provider": request.llm_provider,
            "quick_think_llm": request.quick_think_llm,
            "deep_think_llm": request.deep_think_llm,
            "backend_url": request.backend_url,
            "output_language": request.output_language,
            "selected_analysts": list(request.analysts),
            "research_depth": self.research_depth,
            "checkpoint_enabled": request.checkpoint_enabled,
            "max_debate_rounds": request.max_debate_rounds,
            "max_risk_discuss_rounds": request.max_risk_discuss_rounds,
            "temperature": request.temperature,
            "llm_max_retries": request.llm_max_retries,
            "max_tokens": request.max_tokens,
            "benchmark_ticker": request.benchmark_ticker,
            "data_vendors": request.data_vendors,
            "google_thinking_level": request.google_thinking_level,
            "openai_reasoning_effort": request.openai_reasoning_effort,
            "anthropic_effort": request.anthropic_effort,
        }.items():
            repository.set_setting(key, value)
        return rx.redirect(f"/runs/{run['id']}")

    @rx.event
    def load_runs(self):
        self.selected_run_id = ""
        records = _repo().list_runs(
            limit=250,
            ticker=self.filter_ticker,
            status=self.filter_status,
            signal=self.filter_signal,
            provider=self.filter_provider,
            date_from=self.filter_date_from,
            date_to=self.filter_date_to,
            created_from=self.filter_created_from,
            created_to=self.filter_created_to,
        )
        self.runs = [_run_view(run) for run in records]

    @rx.event
    def set_status_filter(self, value: str):
        self.filter_status = "" if value == "all" else value

    @rx.event
    def set_signal_filter(self, value: str):
        self.filter_signal = "" if value == "all" else value

    @rx.event
    def clear_run_filters(self):
        self.filter_ticker = ""
        self.filter_status = ""
        self.filter_signal = ""
        self.filter_provider = ""
        self.filter_date_from = ""
        self.filter_date_to = ""
        self.filter_created_from = ""
        self.filter_created_to = ""
        self.load_runs()

    @rx.event
    def load_run(self):
        route_id = self.router.page.params.get("run_id", "") or self.selected_run_id
        if not route_id:
            return
        self.selected_run_id = route_id
        repository = _repo()
        run = repository.get_run(route_id)
        if not run:
            self.app_error = "Run not found."
            self.current_run = {}
            return
        view = _run_view(run)
        view["created_full"] = (run.get("created_at") or "—").replace("T", " ")
        view["started_full"] = (run.get("started_at") or "—").replace("T", " ")
        view["finished_full"] = (run.get("finished_at") or "—").replace("T", " ")
        view["resumed_label"] = "Resumed from checkpoint" if run.get("resumed_from_checkpoint") else "Fresh analysis"
        view["is_active"] = run["status"] in {"queued", "running", "cancel_requested"}
        view["is_completed"] = run["status"] == "completed"
        view["is_failed"] = run["status"] in {"failed", "cancelled"}
        self.current_run = view
        events = repository.list_events(route_id, limit=1000)
        latest_status: dict[str, dict[str, Any]] = {}
        activity: list[dict[str, Any]] = []
        for event in events:
            payload = event.get("payload", {})
            if event["type"] == "agent_status":
                latest_status[event.get("agent") or payload.get("display_name", "Agent")] = {
                    "name": payload.get("display_name") or event.get("agent") or "Agent",
                    "team": payload.get("team") or "Agent team",
                    "status": payload.get("status", "pending"),
                }
            if event["type"] in {"message", "tool_call", "run_status", "checkpoint", "error"}:
                if event["type"] == "message":
                    summary = str(payload.get("content", ""))[:320]
                elif event["type"] == "tool_call":
                    summary = f"{payload.get('tool_name', 'Tool')} · {json.dumps(payload.get('arguments', {}), default=str)[:240]}"
                else:
                    summary = str(payload.get("message") or payload.get("public_error_type") or event["type"]).replace("_", " ")
                activity.append({
                    "sequence": event["sequence"],
                    "time": event["created_at"][11:19],
                    "type": event["type"].replace("_", " ").title(),
                    "agent": event.get("agent") or payload.get("source_class") or "System",
                    "summary": summary,
                })
        wall_times = run.get("analyst_wall_times", {})
        analyst_by_name = {label: key for key, label in ANALYST_LABELS.items()}
        self.agent_statuses = []
        for status in latest_status.values():
            elapsed = wall_times.get(analyst_by_name.get(status["name"], ""))
            status["duration"] = f"{float(elapsed):.1f}s" if elapsed is not None else ""
            self.agent_statuses.append(status)
        report_rows = repository.list_reports(route_id)
        report_map = {row["report_key"]: row for row in report_rows}
        self.reports = [
            {"key": key, "title": REPORT_TITLES[key], "producer": report_map[key]["producer"], "content": report_map[key]["content"], "revision": str(report_map[key]["revision"])}
            for key in REPORT_ORDER if key in report_map
        ]
        overview_order = (
            "final_trade_decision", "portfolio_manager_decision", "trader_investment_plan",
            "research_manager_decision", "investment_plan",
        )
        self.overview_reports = [
            next(row for row in self.reports if row["key"] == key)
            for key in overview_order
            if any(row["key"] == key for row in self.reports)
        ]
        self.debate_reports = [row for row in self.reports if row["key"] in {"bull_history", "bear_history", "aggressive_history", "conservative_history", "neutral_history"}]
        self.activity = list(reversed(activity[-200:]))
        self.last_event_sequence = events[-1]["sequence"] if events else 0
        config = run.get("config", {})
        self.config_rows = [
            {"label": key.replace("_", " ").title(), "value": ", ".join(value) if isinstance(value, list) else json.dumps(value) if isinstance(value, dict) else str(value) if value is not None else "—"}
            for key, value in config.items() if not key.startswith("_")
        ]
        artifact_specs = [
            ("complete_report", "Complete report", "Markdown", run.get("complete_report_path")),
            ("report_zip", "Report tree", "ZIP archive", run.get("report_zip_path")),
            ("final_state", "Final state", "JSON", run.get("final_state_path")),
            ("activity_log", "Activity log", "Redacted JSONL", run.get("activity_log_path")),
            ("diagnostic", "Diagnostic log", "Redacted traceback", run.get("diagnostic_path")),
        ]
        self.artifacts = [{"kind": kind, "label": label, "format": fmt, "path": str(path)} for kind, label, fmt, path in artifact_specs if path and Path(path).exists()]
        self.can_resume = self._checkpoint_available(run)
        self.app_error = ""

    def _checkpoint_available(self, run: dict[str, Any]) -> bool:
        if not run.get("checkpoint_enabled"):
            return False
        try:
            from tradingagents.graph.checkpointer import checkpoint_step
            config = run.get("config", {})
            signature = "|".join([
                "analysts=" + ",".join(config.get("analysts", [])),
                f"debate={config.get('max_debate_rounds', 1)}",
                f"risk={config.get('max_risk_discuss_rounds', 1)}",
                f"asset={run.get('asset_type', 'stock')}",
            ])
            return checkpoint_step(DEFAULT_CONFIG["data_cache_dir"], run["ticker"], run["trade_date"], signature) is not None
        except Exception:
            return False

    @rx.event
    def poll(self, _value: str = ""):
        if self.selected_run_id:
            self.load_run()
        else:
            self.load_dashboard()

    @rx.event
    def cancel_run(self):
        if self.selected_run_id:
            _repo().request_cancel(self.selected_run_id)
            self.load_run()

    def _recover(self, mode: str):
        if not self.selected_run_id:
            return
        run = _repo().retry_from(self.selected_run_id, mode, str(uuid.uuid4()))
        return rx.redirect(f"/runs/{run['id']}")

    @rx.event
    def resume_run(self):
        if not self.can_resume:
            self.app_error = "No compatible checkpoint is available for this run."
            return
        return self._recover("resume")

    @rx.event
    def retry_run(self):
        return self._recover("retry")

    @rx.event
    def start_fresh(self):
        return self._recover("start_fresh")

    @rx.event
    def run_again(self):
        return self._recover("rerun")

    @rx.event
    def download_artifact(self, kind: str):
        run = _repo().get_run(self.selected_run_id) if self.selected_run_id else None
        if not run:
            return
        columns = {
            "complete_report": "complete_report_path",
            "report_zip": "report_zip_path",
            "final_state": "final_state_path",
            "activity_log": "activity_log_path",
            "diagnostic": "diagnostic_path",
        }
        target_value = run.get(columns.get(kind, ""))
        if not target_value:
            return
        root = Path(run["artifact_root"]).resolve()
        target = Path(target_value).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            self.app_error = "The requested artifact path is invalid."
            return
        mime = "application/zip" if target.suffix == ".zip" else "application/json" if target.suffix == ".json" else "text/plain"
        return rx.download(data=target.read_bytes(), filename=target.name, mime_type=mime)

    @rx.event
    def load_memory(self):
        from tradingagents.agents.utils.memory import TradingMemoryLog

        self.selected_run_id = ""
        entries = TradingMemoryLog(DEFAULT_CONFIG).load_entries()
        filtered = []
        for entry in reversed(entries):
            if self.memory_ticker and self.memory_ticker.upper() not in entry.get("ticker", "").upper():
                continue
            if self.memory_status == "pending" and not entry.get("pending"):
                continue
            if self.memory_status == "resolved" and entry.get("pending"):
                continue
            if self.memory_rating and entry.get("rating") != self.memory_rating:
                continue
            entry_date = str(entry.get("date") or "")
            if self.memory_date_from and entry_date < self.memory_date_from:
                continue
            if self.memory_date_to and entry_date > self.memory_date_to:
                continue
            item = dict(entry)
            item["status"] = "Pending" if entry.get("pending") else "Resolved"
            item["raw_label"] = entry.get("raw") or "Awaiting full 5-day window"
            item["alpha_label"] = entry.get("alpha") or "—"
            item["resolved_label"] = entry.get("resolved") or "Not resolved"
            filtered.append(item)
        self.memory_entries = filtered

    @rx.event
    def set_memory_status_filter(self, value: str):
        self.memory_status = "" if value == "all" else value

    @rx.event
    def set_memory_rating_filter(self, value: str):
        self.memory_rating = "" if value == "all" else value

    @rx.event
    def load_settings(self):
        self.selected_run_id = ""
        repository = _repo()
        settings = repository.get_settings()
        reverse_env = {config_key: env for env, config_key in _ENV_OVERRIDES.items()}
        keys = [
            "llm_provider", "quick_think_llm", "deep_think_llm", "backend_url",
            "output_language", "max_debate_rounds", "max_risk_discuss_rounds",
            "checkpoint_enabled", "temperature", "llm_max_retries", "max_tokens",
            "benchmark_ticker", "news_article_limit", "global_news_article_limit",
        ]
        rows = []
        for key in keys:
            if key in settings:
                value, source = settings[key], "Web setting"
            elif reverse_env.get(key) and os.getenv(reverse_env[key]):
                value, source = DEFAULT_CONFIG.get(key), reverse_env[key]
            else:
                value, source = DEFAULT_CONFIG.get(key), "Built-in default"
            rows.append({"label": key.replace("_", " ").title(), "value": str(value) if value is not None else "Provider default", "source": source})
        self.settings_rows = rows
        secrets = load_secrets()
        self.credentials = []
        for item in list_providers():
            status = credential_status(item["key"], secrets)
            self.credentials.append({
                "provider": item["label"],
                "env": status.get("env") or "Credential chain / keyless",
                "status": "Configured" if status["configured"] else ("Optional" if not item["credential_required"] else "Missing"),
                "source": status["source"],
            })
        for label, env_name in (
            ("Alpha Vantage data", "ALPHA_VANTAGE_API_KEY"),
            ("FRED macro data", "FRED_API_KEY"),
            ("Reddit data", "REDDIT_CLIENT_ID"),
        ):
            configured = bool(secrets.get(env_name) or os.getenv(env_name))
            self.credentials.append({
                "provider": label,
                "env": env_name,
                "status": "Configured" if configured else "Optional",
                "source": "web secret" if secrets.get(env_name) else ("environment" if os.getenv(env_name) else "missing"),
            })
        self._load_health(repository)

    @rx.event
    def save_secret(self):
        value = self.secret_value.strip()
        if self.secret_name not in KNOWN_SECRET_NAMES or not value:
            self.app_error = "Choose a supported credential name and enter a value."
            return
        store_secret(self.secret_name, value)
        self.secret_value = ""
        self.toast_message = f"{self.secret_name} saved. The value will not be shown again."
        self.app_error = ""
        self.load_settings()


def _app_version() -> str:
    try:
        return importlib.metadata.version("tradingagents")
    except importlib.metadata.PackageNotFoundError:
        return "0.4.0"


def _repository_commit() -> str:
    configured = os.getenv("TRADINGAGENTS_COMMIT")
    if configured:
        return configured[:12]
    try:
        return subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], text=True, stderr=subprocess.DEVNULL, timeout=1).strip()
    except Exception:
        return "unknown"
