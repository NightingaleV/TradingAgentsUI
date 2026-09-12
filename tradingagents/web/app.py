"""TradingAgents durable Reflex research console."""

import reflex as rx

from .pages import (
    dashboard_page,
    memory_page,
    new_analysis_page,
    run_detail_page,
    runs_page,
    settings_page,
)
from .state import AppState


app = rx.App(
    stylesheets=["/styles.css"],
    html_lang="en",
    head_components=[rx.el.link(rel="icon", href="/favicon.svg", type="image/svg+xml")],
)

app.add_page(
    dashboard_page,
    route="/",
    title="TradingAgents · Research desk",
    on_load=AppState.load_dashboard,
)
app.add_page(
    new_analysis_page,
    route="/new-analysis",
    title="New analysis · TradingAgents",
    on_load=AppState.load_new_analysis,
)
app.add_page(
    run_detail_page,
    route="/runs/[run_id]",
    title="Analysis run · TradingAgents",
    on_load=AppState.load_run,
)
app.add_page(
    runs_page,
    route="/runs",
    title="Run history · TradingAgents",
    on_load=AppState.load_runs,
)
app.add_page(
    memory_page,
    route="/memory",
    title="Decision memory · TradingAgents",
    on_load=AppState.load_memory,
)
app.add_page(
    settings_page,
    route="/settings",
    title="Settings & health · TradingAgents",
    on_load=AppState.load_settings,
)
