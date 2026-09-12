"""Typed contracts for durable analysis execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol


AnalystKey = Literal["market", "social", "news", "fundamentals"]
AssetType = Literal["stock", "crypto"]


@dataclass(frozen=True)
class RunRequest:
    ticker_input: str
    ticker: str
    trade_date: str
    asset_type: AssetType
    analysts: tuple[AnalystKey, ...]
    output_language: str
    llm_provider: str
    quick_think_llm: str
    deep_think_llm: str
    backend_url: str | None
    max_debate_rounds: int
    max_risk_discuss_rounds: int
    checkpoint_enabled: bool
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    temperature: float | None = None
    llm_max_retries: int | None = None
    max_tokens: int | None = None
    benchmark_ticker: str | None = None
    data_vendors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["analysts"] = list(self.analysts)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunRequest":
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        filtered = {key: item for key, item in value.items() if key in allowed}
        filtered["analysts"] = tuple(filtered.get("analysts", ()))
        return cls(**filtered)


@dataclass(frozen=True)
class RunEvent:
    type: str
    payload: dict[str, Any]
    agent: str | None = None


@dataclass(frozen=True)
class RunResult:
    final_state: dict[str, Any]
    signal: str
    artifacts: dict[str, str]
    metrics: dict[str, int]
    resumed: bool


class EventSink(Protocol):
    def emit(self, run_id: str, event: RunEvent) -> int: ...
    def cancellation_requested(self, run_id: str) -> bool: ...
    def report(self, run_id: str, report_key: str, producer: str, content: str) -> int: ...
    def project(self, run_id: str, **updates: Any) -> None: ...
