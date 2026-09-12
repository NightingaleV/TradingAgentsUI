"""Single-concurrency SQLite queue worker with per-run process isolation."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import socket
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from tradingagents.persistence.run_repository import RunRepository
from tradingagents.persistence.secret_store import load_secrets

from .analysis_runner import AnalysisRunner, RunCancelled, _redact
from .models import RunEvent, RunRequest


class RepositorySink:
    def __init__(self, repository: RunRepository, run_config: dict[str, Any]):
        self.repository = repository
        self.run_config = run_config

    def emit(self, run_id: str, event: RunEvent) -> int:
        return self.repository.emit_event(run_id, event.type, event.payload, event.agent)

    def cancellation_requested(self, run_id: str) -> bool:
        return self.repository.cancellation_requested(run_id)

    def report(self, run_id: str, report_key: str, producer: str, content: str) -> int:
        return self.repository.upsert_report(run_id, report_key, producer, content)

    def project(self, run_id: str, **updates: Any) -> None:
        self.repository.update_projection(run_id, **updates)


def _public_error(exc: BaseException) -> tuple[str, str]:
    text = str(_redact(str(exc)))
    missing = re.search(r"([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN))", text)
    if missing:
        return "MissingCredential", f"{missing.group(1)} is required for this provider. Add it in Settings or the Compose .env file."
    lowered = text.lower()
    if "rate limit" in lowered or "429" in lowered:
        return "ProviderRateLimit", "The model provider rate-limited this run. Retry later or increase the retry budget."
    if "connection" in lowered or "unreachable" in lowered or "timed out" in lowered:
        return "EndpointUnavailable", f"The configured provider or data endpoint could not be reached: {text[:500]}"
    return type(exc).__name__, text[:1000] or "The analysis failed. Download the diagnostic log for details."


def _write_activity(repository: RunRepository, run_id: str, root: Path) -> Path:
    path = root / "activity.log"
    lines = []
    for event in repository.list_events(run_id, limit=2000):
        lines.append(json.dumps({
            "sequence": event["sequence"],
            "created_at": event["created_at"],
            "type": event["type"],
            "agent": event.get("agent"),
            "payload": _redact(event.get("payload", {})),
        }, sort_keys=True, default=str))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def execute_run(run_id: str, db_path: str) -> None:
    repository = RunRepository(db_path)
    run = repository.get_run(run_id)
    if not run:
        return
    config = dict(run["config"])
    request = RunRequest.from_dict(config)
    sink = RepositorySink(repository, config)
    secrets = load_secrets()
    os.environ.update(secrets)
    root = Path(run["artifact_root"])
    root.mkdir(parents=True, exist_ok=True)
    try:
        result = AnalysisRunner(root).run(run_id, request, sink)
        activity = _write_activity(repository, run_id, root)
        artifacts = dict(result.artifacts)
        artifacts["activity_log"] = str(activity)
        current = repository.get_run(run_id) or {}
        repository.complete_run(
            run_id,
            result.signal,
            result.metrics,
            artifacts,
            current.get("analyst_wall_times", {}),
        )
    except RunCancelled as exc:
        repository.emit_event(run_id, "run_status", {"status": "cancelled", "stage": run.get("stage"), "message": str(exc)})
        activity = _write_activity(repository, run_id, root)
        repository.finish_cancelled(run_id, {}, str(activity))
    except BaseException as exc:
        error_type, public_message = _public_error(exc)
        diagnostic = root / "diagnostic.log"
        diagnostic.write_text(str(_redact(traceback.format_exc())), encoding="utf-8")
        active = repository.get_run(run_id) or {}
        active_agent = active.get("active_agent")
        if active_agent:
            repository.emit_event(run_id, "agent_status", {"display_name": active_agent, "team": "", "status": "failed"}, active_agent)
        repository.emit_event(run_id, "error", {"public_error_type": error_type, "message": public_message, "diagnostic_reference": "diagnostic.log"}, active_agent)
        activity = _write_activity(repository, run_id, root)
        repository.fail_run(run_id, error_type, public_message, str(diagnostic), str(activity))


def run_worker(*, once: bool = False, poll_seconds: float = 1.0) -> None:
    repository = RunRepository()
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    context = multiprocessing.get_context("spawn")
    while not repository.acquire_worker_lease(worker_id, pid=os.getpid()):
        if once:
            return
        time.sleep(max(1.0, poll_seconds))
    repository.fail_stale_running()
    while True:
        if not repository.heartbeat_worker(worker_id, pid=os.getpid(), active_run_id=None):
            return
        run = repository.claim_next_run(worker_id)
        if run:
            process = context.Process(target=execute_run, args=(run["id"], str(repository.path)), daemon=False)
            process.start()
            while process.is_alive():
                if not repository.heartbeat_worker(worker_id, pid=os.getpid(), active_run_id=run["id"]):
                    process.terminate()
                    process.join(timeout=5)
                    return
                process.join(timeout=2)
            process.join()
            current = repository.get_run(run["id"])
            if current and current["status"] in {"running", "cancel_requested"}:
                repository.fail_run(run["id"], "WorkerProcessExit", f"The isolated analysis process exited with code {process.exitcode} before recording a result.")
        if once:
            return
        time.sleep(max(0.2, poll_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="TradingAgents durable analysis worker")
    parser.add_argument("--once", action="store_true", help="Claim at most one queued run, then exit")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    run_worker(once=args.once, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
