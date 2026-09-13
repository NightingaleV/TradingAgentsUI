"""Complete streaming lifecycle for durable TradingAgents analyses."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import traceback
from pathlib import Path
from typing import Any

from tradingagents.graph.analyst_execution import AnalystWallTimeTracker, build_analyst_execution_plan
from tradingagents.graph.checkpointer import checkpoint_step, clear_checkpoint
from tradingagents.reporting import write_report_tree

from .config_builder import effective_graph_config
from .models import EventSink, RunEvent, RunRequest, RunResult
from .stats import StatsCallbackHandler


REPORT_PRODUCERS = {
    "market_report": "Market Analyst",
    "sentiment_report": "Sentiment Analyst",
    "news_report": "News Analyst",
    "fundamentals_report": "Fundamentals Analyst",
    "bull_history": "Bull Researcher",
    "bear_history": "Bear Researcher",
    "research_manager_decision": "Research Manager",
    "investment_plan": "Research Manager",
    "trader_investment_plan": "Trader",
    "aggressive_history": "Aggressive Analyst",
    "conservative_history": "Conservative Analyst",
    "neutral_history": "Neutral Analyst",
    "portfolio_manager_decision": "Portfolio Manager",
    "final_trade_decision": "Portfolio Manager",
}
ANALYST_REPORTS = {
    "market": ("Market Analyst", "market_report"),
    "social": ("Sentiment Analyst", "sentiment_report"),
    "news": ("News Analyst", "news_report"),
    "fundamentals": ("Fundamentals Analyst", "fundamentals_report"),
}
FIXED_AGENTS = (
    "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
    "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager",
)
SECRET_NAME = re.compile(r"(?:KEY|TOKEN|PASSWORD|AUTHORIZATION|SECRET)", re.IGNORECASE)


class RunCancelled(RuntimeError):
    pass


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _jsonable(value.dict())
    return str(value)


def _redact(value: Any) -> Any:
    known_values = {
        env_value
        for env_name, env_value in os.environ.items()
        if env_value and SECRET_NAME.search(env_name) and len(env_value) >= 6
    }
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_NAME.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    text = str(value)
    for secret in known_values:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+", r"\1[REDACTED]", text)
    return text


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return str(content.get("text") or "").strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts).strip()
    return str(content).strip() if content else ""


class _Projection:
    def __init__(self, request: RunRequest, sink: EventSink, run_id: str, tracker: AnalystWallTimeTracker):
        self.request = request
        self.sink = sink
        self.run_id = run_id
        self.tracker = tracker
        self.statuses: dict[str, str] = {}
        self.report_content: dict[str, str] = {}
        self.message_ids: set[str] = set()
        self.debate_content: dict[str, str] = {}
        self.warning_ids: set[tuple[str, str]] = set()
        self.skipped_agents: set[str] = set()
        for analyst in request.analysts:
            self._status(ANALYST_REPORTS[analyst][0], "pending", "Analyst Team")
        for agent in FIXED_AGENTS:
            team = (
                "Research Team" if agent in FIXED_AGENTS[:3]
                else "Trading Team" if agent == "Trader"
                else "Risk Management" if agent in FIXED_AGENTS[4:7]
                else "Portfolio Management"
            )
            self._status(agent, "pending", team)

    def _status(self, agent: str, status: str, team: str | None = None) -> None:
        # A policy-filtered turn is a deliberate non-fatal skip.  Later graph
        # snapshots still contain earlier agent output, so do not overwrite the
        # explanatory status with "completed" while projecting those snapshots.
        if agent in self.skipped_agents and status != "skipped":
            return
        if self.statuses.get(agent) == status:
            return
        self.statuses[agent] = status
        self.sink.emit(
            self.run_id,
            RunEvent("agent_status", {"display_name": agent, "team": team or "", "status": status}, agent),
        )

    @staticmethod
    def _team_for(agent: str) -> str:
        if agent in FIXED_AGENTS[:3]:
            return "Research Team"
        if agent == "Trader":
            return "Trading Team"
        if agent in FIXED_AGENTS[4:7]:
            return "Risk Management"
        return "Portfolio Management"

    def _warnings(self, chunk: dict[str, Any]) -> None:
        for warning in chunk.get("pipeline_warnings", []) or []:
            if not isinstance(warning, dict):
                continue
            agent = str(warning.get("agent") or "Agent")
            kind = str(warning.get("kind") or "warning")
            warning_id = (agent, kind)
            if warning_id in self.warning_ids:
                continue
            self.warning_ids.add(warning_id)
            if kind == "content_filter":
                self.skipped_agents.add(agent)
                self._status(agent, "skipped", self._team_for(agent))
            self.sink.emit(
                self.run_id,
                RunEvent(
                    "agent_warning",
                    {"kind": kind, "message": str(warning.get("message") or "Agent warning")},
                    agent,
                ),
            )

    def _report(self, key: str, content: str) -> None:
        content = content.strip()
        if not content or self.report_content.get(key) == content:
            return
        self.report_content[key] = content
        producer = REPORT_PRODUCERS[key]
        revision = self.sink.report(self.run_id, key, producer, content)
        self.sink.emit(
            self.run_id,
            RunEvent("report_update", {"report_key": key, "producer": producer, "revision": revision}, producer),
        )

    def _messages(self, chunk: dict[str, Any]) -> None:
        for message in chunk.get("messages", []) or []:
            message_id = str(getattr(message, "id", "") or "")
            if message_id and message_id in self.message_ids:
                continue
            if message_id:
                self.message_ids.add(message_id)
            source = type(message).__name__
            content = _message_content(message)
            if content:
                self.sink.emit(
                    self.run_id,
                    RunEvent("message", {"source_class": source, "content": _redact(content[:5000])}),
                )
            for tool_call in getattr(message, "tool_calls", []) or []:
                if isinstance(tool_call, dict):
                    name, arguments = tool_call.get("name", "Tool"), tool_call.get("args", {})
                else:
                    name, arguments = getattr(tool_call, "name", "Tool"), getattr(tool_call, "args", {})
                self.sink.emit(
                    self.run_id,
                    RunEvent("tool_call", {"tool_name": name, "arguments": _redact(_jsonable(arguments))}),
                )

    def update(self, chunk: dict[str, Any], stats: dict[str, int]) -> None:
        self._messages(chunk)
        self._warnings(chunk)
        now = time.monotonic()
        first_pending: str | None = None
        for analyst in self.request.analysts:
            agent, report_key = ANALYST_REPORTS[analyst]
            content = str(chunk.get(report_key) or self.report_content.get(report_key) or "").strip()
            if content:
                self._report(report_key, content)
                self.tracker.mark_started(analyst, now)
                self.tracker.mark_completed(analyst, now)
                self._status(agent, "completed", "Analyst Team")
            elif first_pending is None:
                first_pending = analyst
                self.tracker.mark_started(analyst, now)
                self._status(agent, "running", "Analyst Team")
            else:
                self._status(agent, "pending", "Analyst Team")

        stage = "Analysts"
        active = ANALYST_REPORTS[first_pending][0] if first_pending else "Bull Researcher"
        if first_pending is None:
            debate = chunk.get("investment_debate_state") or {}
            bull = str(debate.get("bull_history") or "").strip()
            bear = str(debate.get("bear_history") or "").strip()
            judge = str(debate.get("judge_decision") or "").strip()
            if bull:
                self._report("bull_history", bull)
            if bear:
                self._report("bear_history", bear)
            if judge:
                self._report("research_manager_decision", judge)
            if chunk.get("investment_plan"):
                self._report("investment_plan", str(chunk["investment_plan"]))
            if not judge:
                stage = "Research"
                latest = "Bear Researcher" if len(bear) > len(self.debate_content.get("bear", "")) else "Bull Researcher"
                self.debate_content.update({"bull": bull, "bear": bear})
                active = latest
                self._status("Bull Researcher", "running" if latest == "Bull Researcher" else "completed" if bull else "pending", "Research Team")
                self._status("Bear Researcher", "running" if latest == "Bear Researcher" else "completed" if bear else "pending", "Research Team")
                self._status("Research Manager", "pending", "Research Team")
                if bull or bear:
                    self.sink.emit(self.run_id, RunEvent("debate_update", {"debate_kind": "research", "speaker": latest, "count": int(debate.get("count") or 0)}, latest))
            else:
                for agent in ("Bull Researcher", "Bear Researcher", "Research Manager"):
                    self._status(agent, "completed", "Research Team")
                trader = str(chunk.get("trader_investment_plan") or "").strip()
                if not trader:
                    stage, active = "Trader", "Trader"
                    self._status("Trader", "running", "Trading Team")
                else:
                    self._report("trader_investment_plan", trader)
                    self._status("Trader", "completed", "Trading Team")
                    risk = chunk.get("risk_debate_state") or {}
                    risk_values = {
                        "Aggressive Analyst": ("aggressive_history", str(risk.get("aggressive_history") or "").strip()),
                        "Conservative Analyst": ("conservative_history", str(risk.get("conservative_history") or "").strip()),
                        "Neutral Analyst": ("neutral_history", str(risk.get("neutral_history") or "").strip()),
                    }
                    for agent, (key, content) in risk_values.items():
                        if content:
                            self._report(key, content)
                    risk_judge = str(risk.get("judge_decision") or "").strip()
                    if not risk_judge:
                        stage = "Risk"
                        speaker = str(risk.get("latest_speaker") or "Aggressive Analyst")
                        active = speaker if speaker in risk_values else "Aggressive Analyst"
                        for agent, (_, content) in risk_values.items():
                            self._status(agent, "running" if agent == active else "completed" if content else "pending", "Risk Management")
                        if any(content for _, content in risk_values.values()):
                            self.sink.emit(self.run_id, RunEvent("debate_update", {"debate_kind": "risk", "speaker": active, "count": int(risk.get("count") or 0)}, active))
                    else:
                        self._report("portfolio_manager_decision", risk_judge)
                        for agent in risk_values:
                            self._status(agent, "completed", "Risk Management")
                        final_decision = str(chunk.get("final_trade_decision") or "").strip()
                        if final_decision:
                            self._report("final_trade_decision", final_decision)
                            self._status("Portfolio Manager", "completed", "Portfolio Management")
                            stage, active = "Portfolio", ""
                        else:
                            self._status("Portfolio Manager", "running", "Portfolio Management")
                            stage, active = "Portfolio", "Portfolio Manager"

        wall_times = self.tracker.get_wall_times()
        self.sink.project(self.run_id, stage=stage, active_agent=active, stats=stats, analyst_wall_times=wall_times)
        self.sink.emit(self.run_id, RunEvent("stats", {**stats, "analyst_wall_times": wall_times}))


class AnalysisRunner:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)

    def run(self, run_id: str, request: RunRequest, sink: EventSink) -> RunResult:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        self.artifact_root.mkdir(parents=True, exist_ok=True)
        stats = StatsCallbackHandler()
        config = effective_graph_config(request)
        tracker = AnalystWallTimeTracker(build_analyst_execution_plan(request.analysts))
        projection = _Projection(request, sink, run_id, tracker)
        sink.emit(run_id, RunEvent("run_status", {"status": "running", "stage": "Initializing", "message": "Preparing isolated analysis runtime"}))

        graph = TradingAgentsGraph(
            selected_analysts=request.analysts,
            config=config,
            callbacks=[stats],
        )
        graph.ticker = request.ticker
        recovery_mode = getattr(request, "_recovery_mode", None)
        raw_config = getattr(sink, "run_config", {})
        recovery_mode = raw_config.get("_recovery_mode", recovery_mode or "fresh")
        if recovery_mode == "start_fresh" and request.checkpoint_enabled:
            clear_checkpoint(config["data_cache_dir"], request.ticker, request.trade_date, graph.run_signature(request.asset_type))
        graph.resolve_pending_entries(request.ticker)
        past_context = graph.memory_log.get_past_context(request.ticker, as_of=graph.memory_as_of(request.trade_date))
        instrument_context = graph.resolve_instrument_context(request.ticker, request.asset_type)
        init_state = graph.propagator.create_initial_state(
            request.ticker,
            request.trade_date,
            asset_type=request.asset_type,
            past_context=past_context,
            instrument_context=instrument_context,
        )
        args = graph.propagator.get_graph_args(callbacks=[stats])
        checkpoint_tid = None
        checkpoint_allowed = request.checkpoint_enabled and recovery_mode != "retry"
        if checkpoint_allowed:
            checkpoint_tid = graph.begin_checkpoint(request.ticker, request.trade_date, request.asset_type)
            if checkpoint_tid:
                args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = checkpoint_tid
        resumed = graph.resuming
        step = checkpoint_step(config["data_cache_dir"], request.ticker, request.trade_date, graph.run_signature(request.asset_type)) if checkpoint_allowed else None
        sink.project(run_id, resumed=resumed, checkpoint_step=step)
        sink.emit(run_id, RunEvent("checkpoint", {"enabled": checkpoint_allowed, "resumed": resumed, "step": step}))

        final_state: dict[str, Any] = {}
        started = time.monotonic()
        try:
            graph_input = graph.checkpoint_input(init_state) if checkpoint_allowed else init_state
            for chunk in graph.graph.stream(graph_input, **args):
                final_state.update(chunk)
                projection.update(final_state, stats.get_stats())
                if sink.cancellation_requested(run_id):
                    raise RunCancelled("Cancellation requested; stopped after the current graph operation.")
        finally:
            if checkpoint_allowed:
                graph.end_checkpoint()

        if not final_state.get("final_trade_decision"):
            raise RuntimeError("The graph ended without a final portfolio decision.")
        signal = graph.process_signal(final_state["final_trade_decision"])
        final_state_path = self.artifact_root / "final_state.json"
        final_state_path.write_text(json.dumps(_jsonable(final_state), indent=2, ensure_ascii=False), encoding="utf-8")
        reports_root = self.artifact_root / "reports"
        complete_report = write_report_tree(final_state, request.ticker, reports_root)
        report_zip = Path(shutil.make_archive(str(self.artifact_root / "report_tree"), "zip", reports_root))
        graph.curr_state = final_state
        graph.log_state(request.trade_date, final_state)
        graph.memory_log.store_decision(request.ticker, request.trade_date, final_state["final_trade_decision"])
        graph.clear_checkpoint_on_success(request.ticker, request.trade_date, request.asset_type)
        elapsed = int(time.monotonic() - started)
        final_stats = stats.get_stats()
        final_stats["elapsed_seconds"] = elapsed
        sink.emit(run_id, RunEvent("artifact", {"kind": "final_state", "path": "final_state.json", "size": final_state_path.stat().st_size}))
        sink.emit(run_id, RunEvent("artifact", {"kind": "complete_report", "path": "reports/complete_report.md", "size": complete_report.stat().st_size}))
        sink.emit(run_id, RunEvent("artifact", {"kind": "report_tree", "path": "report_tree.zip", "size": report_zip.stat().st_size}))
        sink.emit(run_id, RunEvent("run_status", {"status": "completed", "stage": "Portfolio", "message": f"Completed with rating {signal}"}))
        return RunResult(
            final_state=_jsonable(final_state),
            signal=signal,
            artifacts={"final_state": str(final_state_path), "complete_report": str(complete_report), "report_zip": str(report_zip)},
            metrics=final_stats,
            resumed=resumed,
        )
