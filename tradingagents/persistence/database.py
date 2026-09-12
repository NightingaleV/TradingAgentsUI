"""SQLite setup and explicit migrations for durable web-console state."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1


def tradingagents_home() -> Path:
    return Path(os.getenv("TRADINGAGENTS_HOME", Path.home() / ".tradingagents")).expanduser()


def webui_root() -> Path:
    return Path(os.getenv("TRADINGAGENTS_WEBUI_DIR", tradingagents_home() / "webui")).expanduser()


def database_path() -> Path:
    return Path(os.getenv("TRADINGAGENTS_WEB_DB", webui_root() / "tradingagents_web.db")).expanduser()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path or database_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def ensure_database(path: str | Path | None = None) -> Path:
    db_path = Path(path or database_path())
    with connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                parent_run_id TEXT REFERENCES runs(id),
                submission_token TEXT NOT NULL UNIQUE,
                ticker_input TEXT NOT NULL,
                ticker TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','running','cancel_requested','cancelled','completed','failed')),
                stage TEXT NOT NULL DEFAULT 'Queued',
                active_agent TEXT,
                signal TEXT,
                config_json TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                checkpoint_enabled INTEGER NOT NULL DEFAULT 0,
                resumed_from_checkpoint INTEGER NOT NULL DEFAULT 0,
                checkpoint_step INTEGER,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                heartbeat_at TEXT,
                llm_calls INTEGER NOT NULL DEFAULT 0,
                tool_calls INTEGER NOT NULL DEFAULT 0,
                tokens_in INTEGER NOT NULL DEFAULT 0,
                tokens_out INTEGER NOT NULL DEFAULT 0,
                analyst_wall_times_json TEXT NOT NULL DEFAULT '{}',
                error_type TEXT,
                error_message TEXT,
                diagnostic_path TEXT,
                artifact_root TEXT,
                final_state_path TEXT,
                complete_report_path TEXT,
                report_zip_path TEXT,
                activity_log_path TEXT,
                app_version TEXT,
                repository_commit TEXT,
                worker_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_runs_status_created ON runs(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_runs_ticker_date ON runs(ticker, trade_date);
            CREATE INDEX IF NOT EXISTS idx_runs_signal ON runs(signal);

            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(id),
                sequence INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                type TEXT NOT NULL,
                agent TEXT,
                payload_json TEXT NOT NULL,
                UNIQUE(run_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS idx_run_events_sequence ON run_events(run_id, sequence);

            CREATE TABLE IF NOT EXISTS run_reports (
                run_id TEXT NOT NULL REFERENCES runs(id),
                report_key TEXT NOT NULL,
                producer TEXT NOT NULL,
                content TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, report_key)
            );

            CREATE TABLE IF NOT EXISTS web_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS worker_lease (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                worker_id TEXT NOT NULL,
                pid INTEGER,
                active_run_id TEXT,
                started_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL
            );

            INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
            """
        )
    (webui_root() / "runs").mkdir(parents=True, exist_ok=True)
    return db_path
