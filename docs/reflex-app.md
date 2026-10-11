# Reflex web console

This fork ships a durable browser console on top of the TradingAgents graph. It is a
Reflex (React/Next.js + FastAPI) app that talks to a single-concurrency worker process
through a SQLite job store. The browser never owns the lifetime of an analysis: you can
close the tab, come back later, and find the run still queued, running, failed, or
resumable.

The console is a research and decision desk. It runs the graph, presents the analyst
reports, the bull/bear and risk debates, the trader proposal, and the final five-tier
rating. It does not connect to a broker, place an order, or simulate an exchange. The
UI never labels an action as an order execution.

## Layout

```
tradingagents/
├── runtime/
│   ├── models.py            # RunRequest, RunEvent, status/event types
│   ├── config_builder.py    # deep-copy config precedence + validation
│   ├── analysis_runner.py   # full graph lifecycle, emits normalized events
│   ├── background_runner.py # memory-refresh and evaluation jobs
│   ├── stats.py             # reusable LLM/tool/token metrics
│   └── worker.py            # single-concurrency SQLite queue consumer
├── persistence/
│   ├── database.py          # SQLite connection + migrations
│   ├── run_repository.py    # run/event/report/job persistence
│   └── secret_store.py      # write-only web secret store
└── web/
    ├── app.py               # Reflex App + routes
    ├── state.py             # per-page AppState (dashboard, new analysis, ...)
    ├── pages.py             # page composition
    └── components.py        # reused UI blocks
```

All routes are registered in `tradingagents/web/app.py`:

| Route | Page |
|---|---|
| `/` | Dashboard — readiness, active runs, recent decisions |
| `/new-analysis` | New analysis form |
| `/runs` | Run history with filters |
| `/runs/[run_id]` | Run detail with live progress |
| `/portfolio` | Saved reusable portfolio book |
| `/memory` | Decision-memory journal |
| `/evaluation` | Multi-cell decision evaluation |
| `/settings` | Effective config, secrets status, health |

## How it runs

`web` serves the Reflex app on port 8501. `worker` claims queued jobs from SQLite, runs
each one in an isolated child process, and heartbeats its lease back to the database so
the dashboard can tell "queued behind a run" from "worker is down". The two processes
communicate only through SQLite and the shared artifact volume.

A run request is stored as an immutable, secret-free config snapshot. Secrets are loaded
from the Compose `.env` (or the write-only web secrets file) inside each isolated run
process, so credentials never appear in job records, events, or logs. Reports, final
state JSON, and a redacted activity log are written under each run's artifact root.

Providers, quick/deep models, analyst selection, research depth, debate rounds, and the
checkpoint toggle are all configurable from the form. A completed run updates the
portfolio (if included), appends the decision to the memory log, and clears its own
checkpoint.

## Configuration

Env vars are read from `.env` (see `.env.example`). The two worth knowing beyond the
normal `TRADINGAGENTS_*` settings:

- `REFLEX_API_URL` / `REFLEX_DEPLOY_URL` — set both to the public origin of the browser
  when running behind a private-network hostname or an authenticated TLS reverse proxy.
  Local Compose needs no change.
- `TRADINGAGENTS_WEB_BIND` — host bind for the published web port. Defaults to
  `127.0.0.1`; use `0.0.0.0` only on a trusted private network.

The default port bind is loopback-only. This console is built for one trusted operator,
not public multi-user exposure.

## Concurrency caveats

The worker runs one analysis at a time. Running a CLI analysis and a web analysis at the
same time is still possible and they share the same memory log, so until file locking is
added, keep to one active analysis across both entry points.