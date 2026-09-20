"""Transactional repository for runs, events, reports, settings, and worker lease."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import connect, database_path, ensure_database, webui_root

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RUN_STATUSES = {"queued", "running", "cancel_requested", *TERMINAL_STATUSES}
WEB_SETTING_ALLOWLIST = {
    "llm_provider",
    "quick_think_llm",
    "deep_think_llm",
    "backend_url",
    "output_language",
    "selected_analysts",
    "research_depth",
    "checkpoint_enabled",
    "max_debate_rounds",
    "max_risk_discuss_rounds",
    "temperature",
    "llm_max_retries",
    "max_tokens",
    "benchmark_ticker",
    "data_vendors",
    "google_thinking_level",
    "openai_reasoning_effort",
    "anthropic_effort",
    "portfolio",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    for key in ("config_json", "payload_json", "value_json", "analyst_wall_times_json"):
        if key in value and isinstance(value[key], str):
            try:
                value[key.removesuffix("_json") if key != "payload_json" else "payload"] = json.loads(value[key])
            except json.JSONDecodeError:
                value[key.removesuffix("_json")] = {}
    for key in ("checkpoint_enabled", "resumed_from_checkpoint"):
        if key in value:
            value[key] = bool(value[key])
    return value


class RunRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or database_path())
        ensure_database(self.path)

    def create_run(
        self,
        request: dict[str, Any],
        config_hash: str,
        submission_token: str,
        *,
        parent_run_id: str | None = None,
        recovery_mode: str = "fresh",
        app_version: str = "unknown",
        repository_commit: str = "unknown",
    ) -> tuple[dict[str, Any], bool]:
        """Create a queued run exactly once; return ``(run, created)``."""
        run_id = str(uuid.uuid4())
        now = utc_now()
        config = dict(request)
        config["_recovery_mode"] = recovery_mode
        artifact_root = webui_root() / "runs" / run_id
        artifact_root.mkdir(parents=True, exist_ok=True)
        with connect(self.path) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO runs(
                        id, parent_run_id, submission_token, ticker_input, ticker,
                        asset_type, trade_date, status, stage, config_json, config_hash,
                        checkpoint_enabled, created_at, artifact_root, app_version,
                        repository_commit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 'Queued', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        parent_run_id,
                        submission_token,
                        request.get("ticker_input", request["ticker"]),
                        request["ticker"],
                        request["asset_type"],
                        request["trade_date"],
                        json.dumps(config, sort_keys=True),
                        config_hash,
                        int(bool(request.get("checkpoint_enabled"))),
                        now,
                        str(artifact_root),
                        app_version,
                        repository_commit,
                    ),
                )
                connection.commit()
                created = True
            except sqlite3.IntegrityError:
                connection.rollback()
                created = False
                row = connection.execute(
                    "SELECT * FROM runs WHERE submission_token = ?", (submission_token,)
                ).fetchone()
                return _decode_row(row), created
        return self.get_run(run_id), created

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with connect(self.path) as connection:
            return _decode_row(connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())

    def list_runs(
        self,
        *,
        limit: int = 100,
        ticker: str = "",
        status: str = "",
        signal: str = "",
        provider: str = "",
        date_from: str = "",
        date_to: str = "",
        created_from: str = "",
        created_to: str = "",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if ticker:
            clauses.append("ticker LIKE ?")
            params.append(f"%{ticker.strip().upper()}%")
        if status:
            clauses.append("status = ?")
            params.append(status)
        if signal:
            clauses.append("signal = ?")
            params.append(signal)
        if provider:
            clauses.append("json_extract(config_json, '$.llm_provider') = ?")
            params.append(provider)
        if date_from:
            clauses.append("trade_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("trade_date <= ?")
            params.append(date_to)
        if created_from:
            clauses.append("date(created_at) >= ?")
            params.append(created_from)
        if created_to:
            clauses.append("date(created_at) <= ?")
            params.append(created_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def dashboard_counts(self) -> dict[str, int]:
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with connect(self.path) as connection:
            rows = connection.execute("SELECT status, COUNT(*) count FROM runs GROUP BY status").fetchall()
            counts = {row["status"]: row["count"] for row in rows}
            completed_30 = connection.execute(
                "SELECT COUNT(*) FROM runs WHERE status = 'completed' AND created_at >= datetime('now', '-30 days')"
            ).fetchone()[0]
            failed_today = connection.execute(
                "SELECT COUNT(*) FROM runs WHERE status = 'failed' AND created_at >= ?", (since,)
            ).fetchone()[0]
        return {
            "active": counts.get("running", 0) + counts.get("cancel_requested", 0),
            "queued": counts.get("queued", 0),
            "completed_30d": completed_30,
            "failed_today": failed_today,
        }

    def seven_day_volume(self) -> list[dict[str, Any]]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE days(day) AS (
                    SELECT date('now', '-6 days')
                    UNION ALL SELECT date(day, '+1 day') FROM days WHERE day < date('now')
                )
                SELECT days.day, COUNT(r.id) total,
                       SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) completed
                FROM days LEFT JOIN runs r ON date(r.created_at) = days.day
                GROUP BY days.day ORDER BY days.day
                """
            ).fetchall()
        return [{"day": row["day"][5:], "runs": row["total"], "completed": row["completed"] or 0} for row in rows]

    def get_settings(self) -> dict[str, Any]:
        with connect(self.path) as connection:
            rows = connection.execute("SELECT key, value_json FROM web_settings ORDER BY key").fetchall()
        settings: dict[str, Any] = {}
        for row in rows:
            if row["key"] not in WEB_SETTING_ALLOWLIST:
                continue
            try:
                settings[row["key"]] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                continue
        return settings

    def set_setting(self, key: str, value: Any) -> None:
        if key not in WEB_SETTING_ALLOWLIST:
            raise ValueError(f"Web setting is not allowed: {key}")
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO web_settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, sort_keys=True), utc_now()),
            )

    def delete_setting(self, key: str) -> None:
        """Remove an optional local default without touching run snapshots."""
        if key not in WEB_SETTING_ALLOWLIST:
            raise ValueError(f"Web setting is not allowed: {key}")
        with connect(self.path) as connection:
            connection.execute("DELETE FROM web_settings WHERE key = ?", (key,))

    def claim_next_run(self, worker_id: str) -> dict[str, Any] | None:
        with connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            now = utc_now()
            connection.execute(
                """UPDATE runs SET status='running', stage='Initializing', active_agent=NULL,
                   started_at=?, heartbeat_at=?, worker_id=? WHERE id=? AND status='queued'""",
                (now, now, worker_id, row["id"]),
            )
            connection.commit()
        return self.get_run(row["id"])

    def emit_event(self, run_id: str, event_type: str, payload: dict[str, Any], agent: str | None = None) -> int:
        now = utc_now()
        with connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO run_events(run_id, sequence, created_at, type, agent, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, sequence, now, event_type, agent, json.dumps(payload, default=str, sort_keys=True)),
            )
            connection.commit()
        return sequence

    def list_events(self, run_id: str, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
                (run_id, after, max(1, min(limit, 2000))),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def upsert_report(self, run_id: str, report_key: str, producer: str, content: str) -> int:
        now = utc_now()
        with connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT content, revision FROM run_reports WHERE run_id=? AND report_key=?",
                (run_id, report_key),
            ).fetchone()
            if existing and existing["content"] == content:
                connection.commit()
                return existing["revision"]
            revision = (existing["revision"] + 1) if existing else 1
            connection.execute(
                """
                INSERT INTO run_reports(run_id, report_key, producer, content, revision, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, report_key) DO UPDATE SET
                    producer=excluded.producer, content=excluded.content,
                    revision=excluded.revision, updated_at=excluded.updated_at
                """,
                (run_id, report_key, producer, content, revision, now),
            )
            connection.commit()
        return revision

    def list_reports(self, run_id: str) -> list[dict[str, Any]]:
        with connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM run_reports WHERE run_id=? ORDER BY updated_at", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_projection(
        self,
        run_id: str,
        *,
        stage: str | None = None,
        active_agent: str | None = None,
        stats: dict[str, int] | None = None,
        checkpoint_step: int | None = None,
        resumed: bool | None = None,
        analyst_wall_times: dict[str, float] | None = None,
    ) -> None:
        fields: list[str] = ["heartbeat_at = ?"]
        params: list[Any] = [utc_now()]
        if stage is not None:
            fields.append("stage = ?")
            params.append(stage)
        if active_agent is not None:
            fields.append("active_agent = ?")
            params.append(active_agent)
        if checkpoint_step is not None:
            fields.append("checkpoint_step = ?")
            params.append(checkpoint_step)
        if resumed is not None:
            fields.append("resumed_from_checkpoint = ?")
            params.append(int(resumed))
        if stats:
            for key in ("llm_calls", "tool_calls", "tokens_in", "tokens_out"):
                if key in stats:
                    fields.append(f"{key} = ?")
                    params.append(int(stats[key]))
        if analyst_wall_times is not None:
            fields.append("analyst_wall_times_json = ?")
            params.append(json.dumps(analyst_wall_times, sort_keys=True))
        params.append(run_id)
        with connect(self.path) as connection:
            connection.execute(f"UPDATE runs SET {', '.join(fields)} WHERE id = ?", params)

    def cancellation_requested(self, run_id: str) -> bool:
        with connect(self.path) as connection:
            row = connection.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        return bool(row and row["status"] == "cancel_requested")

    def request_cancel(self, run_id: str) -> bool:
        with connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not current or current["status"] not in {"queued", "running"}:
                connection.commit()
                return False
            if current["status"] == "queued":
                cursor = connection.execute(
                    "UPDATE runs SET status='cancelled', stage='Queued', finished_at=? WHERE id=?",
                    (utc_now(), run_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE runs SET status='cancel_requested' WHERE id=?", (run_id,)
                )
            connection.commit()
        return cursor.rowcount > 0

    def heartbeat_worker(self, worker_id: str, *, pid: int, active_run_id: str | None) -> bool:
        now = utc_now()
        with connect(self.path) as connection:
            cursor = connection.execute(
                """UPDATE worker_lease SET pid=?, active_run_id=?, heartbeat_at=?
                   WHERE singleton=1 AND worker_id=?""",
                (pid, active_run_id, now, worker_id),
            )
            if cursor.rowcount and active_run_id:
                connection.execute("UPDATE runs SET heartbeat_at=? WHERE id=?", (now, active_run_id))
        return cursor.rowcount == 1

    def acquire_worker_lease(self, worker_id: str, *, pid: int, stale_seconds: int = 15) -> bool:
        """Acquire the singleton lease without pre-empting a live worker."""
        with connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            lease = connection.execute("SELECT * FROM worker_lease WHERE singleton=1").fetchone()
            heartbeat = None
            if lease and lease["heartbeat_at"]:
                try:
                    heartbeat = datetime.fromisoformat(lease["heartbeat_at"].replace("Z", "+00:00"))
                    if heartbeat.tzinfo is None:
                        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
                except ValueError:
                    heartbeat = None
            fresh = bool(heartbeat and (datetime.now(timezone.utc) - heartbeat).total_seconds() < stale_seconds)
            if lease and lease["worker_id"] != worker_id and fresh:
                connection.commit()
                return False
            now = utc_now()
            connection.execute(
                """INSERT INTO worker_lease(singleton, worker_id, pid, active_run_id, started_at, heartbeat_at)
                   VALUES (1, ?, ?, NULL, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET worker_id=excluded.worker_id,
                   pid=excluded.pid, active_run_id=NULL, started_at=excluded.started_at,
                   heartbeat_at=excluded.heartbeat_at""",
                (worker_id, pid, now, now),
            )
            connection.commit()
        return True

    def worker_lease(self) -> dict[str, Any] | None:
        with connect(self.path) as connection:
            row = connection.execute("SELECT * FROM worker_lease WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def fail_stale_running(self, stale_seconds: int = 30) -> int:
        """Reconcile jobs abandoned by a previous worker process."""
        with connect(self.path) as connection:
            cursor = connection.execute(
                """
                UPDATE runs SET status='failed', finished_at=?, active_agent=NULL,
                    error_type='StaleWorkerLease',
                    error_message='The worker stopped while this run was active. Resume from its checkpoint when available.'
                WHERE status IN ('running','cancel_requested')
                  AND (heartbeat_at IS NULL OR datetime(heartbeat_at) < datetime('now', ?))
                """,
                (utc_now(), f"-{int(stale_seconds)} seconds"),
            )
        return cursor.rowcount

    def complete_run(self, run_id: str, signal: str, stats: dict[str, int], artifacts: dict[str, str], wall_times: dict[str, float]) -> None:
        now = utc_now()
        with connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE runs SET status='completed', stage='Portfolio', active_agent=NULL,
                    signal=?, finished_at=?, heartbeat_at=?, llm_calls=?, tool_calls=?,
                    tokens_in=?, tokens_out=?, analyst_wall_times_json=?,
                    final_state_path=?, complete_report_path=?, report_zip_path=?, activity_log_path=?
                WHERE id=?
                """,
                (
                    signal, now, now, stats.get("llm_calls", 0), stats.get("tool_calls", 0),
                    stats.get("tokens_in", 0), stats.get("tokens_out", 0),
                    json.dumps(wall_times, sort_keys=True), artifacts.get("final_state"),
                    artifacts.get("complete_report"), artifacts.get("report_zip"),
                    artifacts.get("activity_log"), run_id,
                ),
            )
            connection.commit()

    def finish_cancelled(self, run_id: str, stats: dict[str, int], activity_path: str | None = None) -> None:
        now = utc_now()
        with connect(self.path) as connection:
            connection.execute(
                """UPDATE runs SET status='cancelled', finished_at=?, heartbeat_at=?,
                   llm_calls=?, tool_calls=?, tokens_in=?, tokens_out=?, active_agent=NULL,
                   activity_log_path=? WHERE id=?""",
                (now, now, stats.get("llm_calls", 0), stats.get("tool_calls", 0), stats.get("tokens_in", 0), stats.get("tokens_out", 0), activity_path, run_id),
            )

    def fail_run(
        self,
        run_id: str,
        error_type: str,
        message: str,
        diagnostic_path: str | None = None,
        activity_path: str | None = None,
    ) -> None:
        now = utc_now()
        with connect(self.path) as connection:
            connection.execute(
                """UPDATE runs SET status='failed', finished_at=?, heartbeat_at=?, active_agent=NULL,
                   error_type=?, error_message=?, diagnostic_path=?, activity_log_path=? WHERE id=?""",
                (now, now, error_type, message[:2000], diagnostic_path, activity_path, run_id),
            )

    def retry_from(self, run_id: str, mode: str, submission_token: str) -> dict[str, Any]:
        original = self.get_run(run_id)
        if not original:
            raise ValueError("Run not found")
        request = dict(original["config"])
        request.pop("_recovery_mode", None)
        new_run, _ = self.create_run(
            request,
            original["config_hash"],
            submission_token,
            parent_run_id=run_id,
            recovery_mode=mode,
            app_version=original.get("app_version") or "unknown",
            repository_commit=original.get("repository_commit") or "unknown",
        )
        return new_run
