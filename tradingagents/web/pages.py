"""Page composition for the TradingAgents Reflex console."""

from __future__ import annotations

from datetime import date

import reflex as rx

from .components import (
    ACCENT,
    BORDER,
    MUTED,
    app_shell,
    empty_state,
    field,
    metric_card,
    page_header,
    run_compact_row,
    section_title,
    signal_badge,
    status_badge,
)
from .state import ANALYST_LABELS, AppState


def run_str(key: str) -> rx.Var:
    return AppState.current_run[key].to(str)


def run_int(key: str) -> rx.Var:
    return AppState.current_run[key].to(int)


def run_bool(key: str) -> rx.Var:
    return AppState.current_run[key].to(bool)


def health_line(icon: str, label, value, okay) -> rx.Component:
    return rx.hstack(
        rx.center(rx.icon(icon, size=17, color=rx.cond(okay, ACCENT, "#ffb05c")), class_name="health-icon"),
        rx.vstack(rx.text(label, size="2", weight="medium"), rx.text(value, size="1", color=MUTED), spacing="1", align="start"),
        rx.spacer(),
        rx.cond(okay, rx.icon("circle-check", size=17, color="#69df9d"), rx.icon("triangle-alert", size=17, color="#ffb05c")),
        width="100%", align="center",
    )


def dashboard_page() -> rx.Component:
    new_button = rx.link(
        rx.button(rx.icon("plus", size=17), "New analysis", color_scheme="teal", size="3", radius="large"),
        href="/new-analysis",
    )
    active_panel = rx.card(
        rx.vstack(
            rx.hstack(section_title("LIVE QUEUE", "Active analyses"), rx.spacer(), rx.link("View all", href="/runs", size="2", color=ACCENT), width="100%", align="center"),
            rx.cond(
                AppState.active_runs.length() > 0,
                rx.vstack(rx.foreach(AppState.active_runs, run_compact_row), width="100%", spacing="0"),
                rx.vstack(rx.text("No analyses are active.", size="2", color=MUTED), rx.text("Queue a run to begin the sequential analyst workflow.", size="1", color=MUTED), align="start", padding="2rem 0"),
            ),
            spacing="4", align="start",
        ), class_name="panel dashboard-main-panel",
    )
    health_panel = rx.card(
        rx.vstack(
            section_title("SYSTEM READINESS", "Runtime checks"),
            health_line("radio-tower", "Analysis worker", AppState.health["worker_label"], AppState.health["worker_online"]),
            health_line("database", "Job database", rx.cond(AppState.health["database_ok"], "Writable", "Unavailable"), AppState.health["database_ok"]),
            health_line("hard-drive", "Artifact storage", AppState.health["storage_free"], AppState.health["storage_ok"]),
            health_line("key-round", AppState.health["provider"], AppState.health["credential_label"], AppState.health["credential_ok"]),
            rx.link(rx.button("Open health details", variant="soft", color_scheme="gray", width="100%"), href="/settings", width="100%"),
            spacing="4", align="start",
        ), class_name="panel", width="100%",
    )
    chart_panel = rx.card(
        rx.vstack(
            section_title("7-DAY ACTIVITY", "Analysis throughput", "Queued runs and completed decisions"),
            rx.recharts.area_chart(
                rx.recharts.cartesian_grid(stroke="#233140", vertical=False),
                rx.recharts.x_axis(data_key="day", stroke=MUTED, font_size=12),
                rx.recharts.y_axis(stroke=MUTED, font_size=12, allow_decimals=False),
                rx.recharts.tooltip(content_style={"background": "#101923", "border": f"1px solid {BORDER}", "border_radius": "10px"}),
                rx.recharts.area(data_key="runs", stroke="#77a7ff", fill="#77a7ff", fill_opacity=0.14, type_="monotone"),
                rx.recharts.area(data_key="completed", stroke=ACCENT, fill=ACCENT, fill_opacity=0.16, type_="monotone"),
                data=AppState.chart_data, height=230, width="100%",
            ),
            spacing="4", align="start",
        ), class_name="panel",
    )
    recent_panel = rx.card(
        rx.vstack(
            rx.hstack(section_title("DECISION LOG", "Recent ratings"), rx.spacer(), rx.link("Run history", href="/runs", size="2", color=ACCENT), width="100%", align="center"),
            rx.cond(
                AppState.recent_runs.length() > 0,
                rx.vstack(
                    rx.foreach(
                        AppState.recent_runs,
                        lambda run: rx.link(
                            rx.hstack(
                                rx.vstack(rx.text(run["ticker"], weight="bold"), rx.text(run["trade_date_label"], size="1", color=MUTED), spacing="1", align="start"),
                                rx.spacer(), signal_badge(run["signal"]),
                                padding="0.8rem 0", border_bottom=f"1px solid {BORDER}", width="100%", align="center",
                            ), href=run["href"], width="100%", text_decoration="none",
                        ),
                    ), spacing="0", width="100%",
                ),
                rx.text("Completed decisions will appear here.", size="2", color=MUTED, padding="2rem 0"),
            ),
            spacing="4", align="start",
        ), class_name="panel",
    )
    content = rx.vstack(
        page_header("OPERATIONS / OVERVIEW", "Research desk", "Monitor durable analysis runs and revisit every decision.", new_button),
        rx.cond(AppState.announcement != "", rx.callout(AppState.announcement, icon="megaphone", color_scheme="cyan", size="1", width="100%"), rx.fragment()),
        rx.grid(
            metric_card("activity", "Active runs", AppState.dashboard_counts["active"], "Worker concurrency: 1"),
            metric_card("list-ordered", "Queued", AppState.dashboard_counts["queued"], "Durable SQLite queue", "#77a7ff"),
            metric_card("circle-check", "Completed", AppState.dashboard_counts["completed_30d"], "Last 30 days", "#69df9d"),
            metric_card("triangle-alert", "Failed today", AppState.dashboard_counts["failed_today"], "Checkpoint recovery available", "#ffb05c"),
            columns=rx.breakpoints(initial="1", sm="2", xl="4"), spacing="4", width="100%",
        ),
        rx.grid(active_panel, health_panel, columns=rx.breakpoints(initial="1", lg="3fr 2fr"), spacing="4", width="100%"),
        rx.grid(chart_panel, recent_panel, columns=rx.breakpoints(initial="1", lg="3fr 2fr"), spacing="4", width="100%"),
        class_name="content", align="start",
    )
    return app_shell(content, "dashboard", poll=True)


def form_section(number: str, icon: str, title: str, description: str, body: rx.Component) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.center(rx.text(number, class_name="mono", weight="bold", size="2"), class_name="section-number"),
                rx.center(rx.icon(icon, size=18, color=ACCENT), class_name="metric-icon"),
                rx.vstack(rx.heading(title, size="5"), rx.text(description, size="2", color=MUTED), spacing="1", align="start"),
                align="center",
            ),
            rx.separator(size="4"), body, spacing="5", align="start",
        ), class_name="panel form-section",
    )


def analyst_choice(key: str, icon: str, description: str) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.checkbox(checked=AppState.analysts.contains(key), on_change=lambda checked: AppState.toggle_analyst(key, checked)),
            rx.center(rx.icon(icon, size=17, color=ACCENT), class_name="metric-icon"),
            rx.vstack(rx.text(ANALYST_LABELS[key], size="2", weight="bold"), rx.text(description, size="1", color=MUTED), spacing="1", align="start"),
            align="center",
        ), class_name="analyst-option",
    )


def summary_line(label: str, value) -> rx.Component:
    return rx.hstack(rx.text(label, size="1", color=MUTED), rx.spacer(), rx.text(value, size="2", weight="medium", text_align="right"), width="100%", align="center")


def signal_like_badge(asset_type) -> rx.Component:
    return rx.cond(
        asset_type == "crypto",
        rx.badge(rx.icon("bitcoin", size=13), "CRYPTO", color_scheme="amber", variant="soft"),
        rx.badge(rx.icon("building-2", size=13), "STOCK", color_scheme="blue", variant="soft"),
    )


def new_analysis_page() -> rx.Component:
    instrument = rx.grid(
        field("Ticker", rx.input(value=AppState.ticker, on_change=AppState.set_ticker, placeholder="SPY, 0700.HK, BTC-USD", max_length=32, width="100%"), "Canonicalized and classified on review."),
        field("As-of date", rx.input(type="date", value=AppState.trade_date, on_change=AppState.set_trade_date, max=date.today().isoformat(), width="100%"), "Cannot be later than the server date."),
        field("Output language", rx.select(["English", "Chinese", "Japanese", "Korean", "Hindi", "Spanish", "Portuguese", "French", "German", "Arabic", "Russian", "Custom"], value=AppState.output_language, on_change=AppState.set_output_language, width="100%"), "Reports and final decision only."),
        rx.cond(AppState.output_language == "Custom", field("Custom language", rx.input(value=AppState.custom_language, on_change=AppState.set_custom_language, placeholder="e.g. Turkish", width="100%")), rx.box()),
        columns=rx.breakpoints(initial="1", md="2"), spacing="4", width="100%",
    )
    team = rx.vstack(
        rx.grid(
            analyst_choice("market", "chart-no-axes-combined", "Price action and technical evidence"),
            analyst_choice("social", "messages-square", "News, StockTwits, and Reddit sentiment"),
            analyst_choice("news", "newspaper", "Company, global, macro, and insider context"),
            analyst_choice("fundamentals", "landmark", "Financial statements and valuation"),
            columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
        ),
        field("Research depth", rx.segmented_control.root(
            rx.segmented_control.item("Shallow", value="Shallow"), rx.segmented_control.item("Medium", value="Medium"), rx.segmented_control.item("Deep", value="Deep"),
            value=AppState.research_depth, on_change=AppState.set_depth, width="100%",
        ), "Sets both research and risk debate rounds; advanced fields can override."),
        spacing="4", align="start", width="100%",
    )
    endpoint_field = rx.cond(
        AppState.llm_provider == "azure",
        field(
            "Azure endpoint",
            rx.input(value=AppState.backend_url, on_change=AppState.set_backend_url, placeholder="https://resource.openai.azure.com/openai/v1/", width="100%"),
            "Foundry Models: use the full /openai/v1/ URL. Legacy Azure OpenAI deployments: use the resource root instead.",
        ),
        field(
            "Resolved endpoint",
            rx.input(value=AppState.backend_url, on_change=AppState.set_backend_url, placeholder="Provider default", width="100%"),
            "Resolved by the worker, never by browser JavaScript.",
        ),
    )
    models = rx.vstack(
        rx.grid(
            field("Provider / region", rx.select(AppState.provider_options, value=AppState.provider_label, on_change=AppState.set_provider, width="100%"), "Saved immediately as the next-run default."),
            endpoint_field,
            field("Quick model", rx.select(AppState.quick_model_options, value=AppState.quick_model_label, on_change=AppState.set_quick_model_choice, width="100%")),
            field("Deep model", rx.select(AppState.deep_model_options, value=AppState.deep_model_label, on_change=AppState.set_deep_model_choice, width="100%")),
            columns=rx.breakpoints(initial="1", md="2"), spacing="4", width="100%",
        ),
        rx.grid(
            rx.cond(AppState.quick_model_label == "Custom model ID", field("Custom quick model ID", rx.input(value=AppState.custom_quick_model, on_change=AppState.set_custom_quick_model, width="100%")), rx.box()),
            rx.cond(AppState.deep_model_label == "Custom model ID", field("Custom deep model ID", rx.input(value=AppState.custom_deep_model, on_change=AppState.set_custom_deep_model, width="100%")), rx.box()),
            columns=rx.breakpoints(initial="1", md="2"), spacing="4", width="100%",
        ),
        rx.cond(
            (AppState.llm_provider == "openai") | (AppState.llm_provider == "google") | (AppState.llm_provider == "anthropic"),
            field("Reasoning control", rx.segmented_control.root(
                rx.segmented_control.item("Low", value="low"), rx.segmented_control.item("Medium", value="medium"), rx.segmented_control.item("High", value="high"),
                value=AppState.reasoning_control, on_change=AppState.set_reasoning_control,
            )), rx.box(),
        ),
        spacing="4", align="start", width="100%",
    )
    reliability = rx.vstack(
        rx.hstack(
            rx.switch(checked=AppState.checkpoint_enabled, on_change=AppState.set_checkpoint_enabled, color_scheme="teal"),
            rx.vstack(rx.text("Checkpoint recovery", weight="bold", size="2"), rx.text("Crash recovery between graph nodes—not ordinary run history.", color=MUTED, size="1"), spacing="1", align="start"),
            align="center",
        ),
        rx.accordion.root(
            rx.accordion.item(
                header=rx.hstack(rx.icon("sliders-horizontal", size=16), rx.text("Advanced runtime controls")),
                content=rx.grid(
                    field("Debate rounds", rx.input(type="number", min=1, max=10, value=AppState.max_debate_rounds, on_change=AppState.set_max_debate_rounds, width="100%")),
                    field("Risk rounds", rx.input(type="number", min=1, max=10, value=AppState.max_risk_discuss_rounds, on_change=AppState.set_max_risk_discuss_rounds, width="100%")),
                    field("Temperature", rx.input(type="number", min=0, max=2, step="0.1", value=AppState.temperature, on_change=AppState.set_temperature, placeholder="Provider default", width="100%")),
                    field("LLM retry budget", rx.input(type="number", min=0, value=AppState.llm_max_retries, on_change=AppState.set_llm_max_retries, placeholder="SDK default", width="100%")),
                    field("Max output tokens", rx.input(type="number", min=1, value=AppState.max_tokens, on_change=AppState.set_max_tokens, placeholder="Provider default", width="100%")),
                    field("Benchmark ticker", rx.input(value=AppState.benchmark_ticker, on_change=AppState.set_benchmark_ticker, placeholder="Auto by market", width="100%")),
                    field("Core market vendor", rx.select(["yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"], value=AppState.core_vendor, on_change=AppState.set_core_vendor, width="100%")),
                    field("Technical vendor", rx.select(["yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"], value=AppState.technical_vendor, on_change=AppState.set_technical_vendor, width="100%")),
                    field("Fundamentals vendor", rx.select(["yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"], value=AppState.fundamental_vendor, on_change=AppState.set_fundamental_vendor, width="100%")),
                    field("News vendor", rx.select(["yfinance", "alpha_vantage", "yfinance,alpha_vantage", "alpha_vantage,yfinance", "default"], value=AppState.news_vendor, on_change=AppState.set_news_vendor, width="100%")),
                    columns=rx.breakpoints(initial="1", md="2"), spacing="4", width="100%",
                ), value="advanced",
            ), type="single", collapsible=True, width="100%", variant="ghost",
        ),
        spacing="4", align="start", width="100%",
    )
    review_panel = rx.card(
        rx.vstack(
            section_title("FINAL CHECK", "Configuration review", "Validation creates an immutable, secret-free snapshot."),
            rx.cond(
                AppState.review_ready,
                rx.vstack(
                    rx.hstack(signal_like_badge(AppState.review_config["asset_type"]), rx.text(AppState.review_config["ticker"], size="6", weight="bold", class_name="mono"), width="100%", align="center"),
                    summary_line("As-of", AppState.review_config["trade_date"]),
                    summary_line("Provider", AppState.review_config["llm_provider"]),
                    summary_line("Quick model", AppState.review_config["quick_think_llm"]),
                    summary_line("Deep model", AppState.review_config["deep_think_llm"]),
                    summary_line("Analysts", AppState.review_config["analysts"].to(list[str]).join(", ")),
                    summary_line("Rounds", AppState.review_config["max_debate_rounds"].to(int).to_string() + " research · " + AppState.review_config["max_risk_discuss_rounds"].to(int).to_string() + " risk"),
                    rx.cond(AppState.review_config["asset_type"] == "crypto", rx.callout("Fundamentals is excluded for crypto; the graph and visible team now match.", icon="info", color_scheme="blue", size="1"), rx.fragment()),
                    rx.cond(AppState.credential_hint != "", rx.callout(AppState.credential_hint, icon="key-round", color_scheme="amber", size="1"), rx.fragment()),
                    rx.button(rx.icon("list-plus", size=16), "Queue analysis", on_click=AppState.queue_analysis, color_scheme="teal", size="3", width="100%", disabled=AppState.credential_hint != ""),
                    spacing="3", align="start", width="100%",
                ),
                rx.center(rx.vstack(rx.icon("clipboard-check", size=27, color=MUTED), rx.text("Review the form to see the canonical instrument, asset type, and exact runtime settings.", color=MUTED, size="2", text_align="center"), spacing="3", align="center"), min_height="15rem"),
            ),
            rx.cond(AppState.form_error != "", rx.callout(AppState.form_error, icon="triangle-alert", color_scheme="red", size="1", width="100%"), rx.fragment()),
            spacing="4", align="start",
        ), class_name="panel review-panel",
    )
    form_content = rx.form(
        rx.vstack(
            form_section("01", "scan-search", "Instrument", "Identify the subject and point-in-time boundary.", instrument),
            form_section("02", "users", "Research team", "Choose the evidence pipeline and debate depth.", team),
            form_section("03", "cpu", "Models", "Select the provider, endpoint, and reasoning roles.", models),
            form_section("04", "shield-check", "Reliability", "Control recovery and advanced runtime bounds.", reliability),
            rx.button(rx.icon("clipboard-check", size=17), "Review configuration", type="button", on_click=AppState.review_configuration, variant="surface", color_scheme="teal", size="3", width="100%"),
            spacing="4", width="100%",
        ), width="100%",
    )
    content = rx.vstack(
        page_header("ANALYSIS / NEW", "Configure analysis", "Every run is durable, immutable, and independent of this browser tab."),
        rx.grid(form_content, review_panel, columns=rx.breakpoints(initial="1", xl="minmax(0, 1fr) 23rem"), spacing="5", width="100%", align_items="start"),
        class_name="content", align="start",
    )
    return app_shell(content, "new")


def runs_page() -> rx.Component:
    filters = rx.card(
        rx.vstack(
            rx.grid(
                field("Ticker", rx.input(value=AppState.filter_ticker, on_change=AppState.set_filter_ticker, placeholder="AAPL", width="100%")),
                field("Status", rx.select(["all", "queued", "running", "completed", "failed", "cancelled"], value=rx.cond(AppState.filter_status == "", "all", AppState.filter_status), on_change=AppState.set_status_filter, width="100%")),
                field("Rating", rx.select(["all", "Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"], value=rx.cond(AppState.filter_signal == "", "all", AppState.filter_signal), on_change=AppState.set_signal_filter, width="100%")),
                field("Provider", rx.input(value=AppState.filter_provider, on_change=AppState.set_filter_provider, placeholder="openai", width="100%")),
                field("As-of from", rx.input(type="date", value=AppState.filter_date_from, on_change=AppState.set_filter_date_from, width="100%")),
                field("As-of to", rx.input(type="date", value=AppState.filter_date_to, on_change=AppState.set_filter_date_to, width="100%")),
                field("Created from", rx.input(type="date", value=AppState.filter_created_from, on_change=AppState.set_filter_created_from, width="100%")),
                field("Created to", rx.input(type="date", value=AppState.filter_created_to, on_change=AppState.set_filter_created_to, width="100%")),
                columns=rx.breakpoints(initial="1", md="2", lg="4"), spacing="3", width="100%",
            ),
            rx.hstack(
                rx.button(rx.icon("search", size=15), "Apply filters", on_click=AppState.load_runs, color_scheme="teal", variant="soft"),
                rx.button("Clear", on_click=AppState.clear_run_filters, variant="ghost", color_scheme="gray"),
            ),
            spacing="4", align="start",
        ), class_name="panel", width="100%",
    )
    table = rx.card(
        rx.box(
            rx.table.root(
                rx.table.header(rx.table.row(*[rx.table.column_header_cell(label) for label in ["Instrument", "Status", "Rating", "Provider / models", "Team / depth", "Duration", "Created", ""]])),
                rx.table.body(rx.foreach(AppState.runs, run_table_row)),
                width="100%", variant="surface",
            ),
            overflow_x="auto", width="100%",
        ), class_name="panel table-panel", width="100%",
    )
    content = rx.vstack(
        page_header(
            "OPERATIONS / HISTORY", "Analysis runs", "Search durable run history without mutating or deleting prior decisions.",
            rx.link(rx.button(rx.icon("plus", size=16), "New analysis", color_scheme="teal"), href="/new-analysis"),
        ),
        filters,
        rx.cond(
            AppState.runs.length() > 0,
            table,
            empty_state("history", "No matching runs", "Adjust the filters or queue the first analysis.", rx.link(rx.button("New analysis", color_scheme="teal"), href="/new-analysis")),
        ),
        class_name="content", align="start",
    )
    return app_shell(content, "runs")


def run_table_row(run: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.vstack(rx.text(run["ticker"], weight="bold", class_name="mono"), rx.text(run["trade_date_label"], size="1", color=MUTED), spacing="1", align="start")),
        rx.table.cell(status_badge(run["status"])),
        rx.table.cell(signal_badge(run["signal_label"])),
        rx.table.cell(rx.vstack(rx.text(run["provider"], weight="medium", size="2"), rx.text(run["models"], size="1", color=MUTED), spacing="1", align="start")),
        rx.table.cell(rx.vstack(rx.text(run["analysts_label"], size="1"), rx.text(run["depth_label"], size="1", color=MUTED), spacing="1", align="start", max_width="18rem")),
        rx.table.cell(rx.text(run["duration"], class_name="mono", size="2")),
        rx.table.cell(rx.text(run["created_label"], class_name="mono", size="1", color=MUTED)),
        rx.table.cell(rx.link(rx.icon_button("arrow-up-right", variant="ghost", color_scheme="gray", aria_label="Open run"), href=run["href"])),
        _hover={"background": "rgba(93,217,193,.035)"},
    )


def run_detail_page() -> rx.Component:
    content = rx.cond(
        AppState.current_run,
        run_detail_content(),
        rx.vstack(
            page_header("ANALYSIS / RUN", "Run unavailable", "The requested durable run could not be loaded."),
            rx.callout(AppState.app_error, icon="triangle-alert", color_scheme="red"),
            class_name="content",
        ),
    )
    return app_shell(content, "runs", poll=True)


def run_detail_content() -> rx.Component:
    actions = rx.hstack(
        rx.cond(
            run_bool("is_active"),
            rx.button(rx.icon("square", size=15), "Cancel after current operation", on_click=AppState.cancel_run, color_scheme="amber", variant="soft"),
            rx.fragment(),
        ),
        rx.cond(
            run_bool("is_failed"),
            rx.fragment(
                rx.cond(AppState.can_resume, rx.button(rx.icon("play", size=15), "Resume from checkpoint", on_click=AppState.resume_run, color_scheme="teal"), rx.fragment()),
                rx.button(rx.icon("refresh-cw", size=15), "Retry as new run", on_click=AppState.retry_run, variant="soft", color_scheme="blue"),
                fresh_dialog(),
            ),
            rx.fragment(),
        ),
        rx.cond(
            run_bool("is_completed"),
            rx.button(rx.icon("rotate-ccw", size=15), "Run again", on_click=AppState.run_again, variant="soft", color_scheme="teal"),
            rx.fragment(),
        ),
        wrap="wrap",
    )
    header = rx.card(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.hstack(
                        signal_like_badge(run_str("asset_type")),
                        rx.text(run_str("ticker"), size="8", weight="bold", class_name="mono"),
                        status_badge(run_str("status")),
                        signal_badge(run_str("signal_label")),
                        wrap="wrap", align="center",
                    ),
                    rx.text(
                        run_str("trade_date_label") + " · " + run_str("provider") + " · " + run_str("models"),
                        size="2", color=MUTED,
                    ),
                    spacing="2", align="start",
                ),
                rx.spacer(), actions, width="100%", align="center", wrap="wrap",
            ),
            rx.cond(
                run_bool("resumed_from_checkpoint"),
                rx.callout("This attempt resumed a compatible checkpoint from its parent run.", icon="rotate-ccw", color_scheme="teal", size="1", width="100%"),
                rx.fragment(),
            ),
            rx.cond(
                run_str("signal_label") == "REVIEW",
                rx.callout("The graph completed, but no valid five-tier rating could be parsed. Human review is required; REVIEW is not Hold.", icon="triangle-alert", color_scheme="amber", width="100%"),
                rx.fragment(),
            ),
            stage_stepper(),
            rx.grid(
                detail_metric("Stage", run_str("stage"), "layers"),
                detail_metric("Active agent", run_str("active_label"), "bot"),
                detail_metric("Elapsed", run_str("duration"), "timer"),
                detail_metric("LLM / tools", run_int("llm_calls").to_string() + " / " + run_int("tool_calls").to_string(), "gauge"),
                detail_metric("Tokens in / out", run_int("tokens_in").to_string() + " / " + run_int("tokens_out").to_string(), "coins"),
                detail_metric("Checkpoint", run_str("resumed_label"), "save"),
                columns=rx.breakpoints(initial="2", lg="6"), spacing="3", width="100%",
            ),
            rx.hstack(
                rx.text("Created " + run_str("created_full"), size="1", color=MUTED, class_name="mono"),
                rx.text("Started " + run_str("started_full"), size="1", color=MUTED, class_name="mono"),
                rx.text("Finished " + run_str("finished_full"), size="1", color=MUTED, class_name="mono"),
                spacing="4", wrap="wrap", width="100%",
            ),
            spacing="5", align="start",
        ), class_name="panel run-hero", width="100%",
    )
    tabs = rx.tabs.root(
        rx.tabs.list(*[rx.tabs.trigger(label, value=value) for label, value in [("Overview", "overview"), ("Reports", "reports"), ("Debate", "debate"), ("Activity", "activity"), ("Configuration", "configuration"), ("Artifacts", "artifacts")]], class_name="run-tabs"),
        rx.tabs.content(overview_tab(), value="overview"),
        rx.tabs.content(reports_tab(), value="reports"),
        rx.tabs.content(debate_tab(), value="debate"),
        rx.tabs.content(activity_tab(), value="activity"),
        rx.tabs.content(configuration_tab(), value="configuration"),
        rx.tabs.content(artifacts_tab(), value="artifacts"),
        default_value="overview", width="100%",
    )
    return rx.vstack(
        rx.hstack(rx.link(rx.hstack(rx.icon("arrow-left", size=15), rx.text("Runs"), spacing="2"), href="/runs", color=MUTED, text_decoration="none"), width="100%"),
        header,
        rx.cond(run_str("error_message") != "", rx.callout(run_str("error_message"), icon="triangle-alert", color_scheme="red", width="100%"), rx.fragment()),
        tabs,
        class_name="content", align="start",
    )


def fresh_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(rx.button(rx.icon("eraser", size=15), "Start fresh", variant="ghost", color_scheme="red")),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Clear this compatible checkpoint?"),
            rx.alert_dialog.description("Only the checkpoint matching this run’s ticker, date, analysts, rounds, and asset type will be cleared. Run history remains immutable."),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("Keep checkpoint", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(rx.button("Clear and queue", color_scheme="red", on_click=AppState.start_fresh)),
                spacing="3", justify="end", margin_top="1.5rem",
            ),
        ),
    )


def stage_stepper() -> rx.Component:
    stages = [("Analysts", "scan-line"), ("Research", "messages-square"), ("Trader", "file-pen-line"), ("Risk", "shield-alert"), ("Portfolio", "briefcase-business")]
    return rx.hstack(
        *[
            rx.vstack(
                rx.center(
                    rx.icon(icon, size=16),
                    class_name=rx.cond(
                        run_bool("is_completed"),
                        "stage-node done",
                        rx.cond(
                            run_str("stage") == label,
                            "stage-node active",
                            rx.cond(run_int("stage_index") > index, "stage-node done", "stage-node"),
                        ),
                    ),
                ),
                rx.text(label, size="1", color="#d5dfeb"), spacing="2",
            )
            for index, (label, icon) in enumerate(stages)
        ],
        class_name="stage-track", justify="between", width="100%",
    )


def detail_metric(label: str, value, icon: str) -> rx.Component:
    return rx.vstack(
        rx.hstack(rx.icon(icon, size=14, color=ACCENT), rx.text(label, size="1", color=MUTED), spacing="2"),
        rx.text(value, size="2", weight="bold"),
        spacing="2", align="start", class_name="detail-metric",
    )


def overview_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            run_bool("is_completed"),
            rx.card(
                rx.vstack(
                    rx.text("FINAL RATING", class_name="eyebrow"), signal_badge(run_str("signal_label")),
                    spacing="3", align="start",
                ), class_name="panel decision-card",
            ), rx.fragment(),
        ),
        rx.cond(
            AppState.overview_reports.length() > 0,
            rx.vstack(rx.foreach(AppState.overview_reports, report_card), spacing="4", width="100%"),
            empty_state("file-clock", "Decision is still forming", "Manager, trader, and portfolio outputs appear here as the worker persists them."),
        ),
        evidence_card(), width="100%", spacing="4", padding_top="1rem", align="start",
    )


def evidence_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            section_title("EVIDENCE", "Agent completion"),
            rx.grid(rx.foreach(AppState.agent_statuses, agent_card), columns=rx.breakpoints(initial="1", sm="2", lg="4"), spacing="3", width="100%"),
            spacing="4", align="start",
        ), class_name="panel", width="100%",
    )


def agent_card(agent: rx.Var) -> rx.Component:
    icon = rx.match(
        agent["status"],
        ("completed", rx.icon("check", size=15)),
        ("running", rx.icon("loader-circle", size=15)),
        ("failed", rx.icon("x", size=15)),
        rx.icon("clock", size=15),
    )
    icon_class = rx.match(agent["status"], ("completed", "agent-icon complete"), ("running", "agent-icon running"), ("failed", "agent-icon failed"), "agent-icon")
    return rx.hstack(
        rx.center(icon, class_name=icon_class),
        rx.vstack(rx.text(agent["name"], size="2", weight="bold"), rx.text(agent["team"], size="1", color=MUTED), spacing="1", align="start"),
        rx.spacer(),
        rx.vstack(
            rx.text(agent["status"].to(str).upper(), size="1", color=MUTED, class_name="mono"),
            rx.cond(agent["duration"].to(str) != "", rx.text(agent["duration"], size="1", color=ACCENT, class_name="mono"), rx.fragment()),
            spacing="1", align="end",
        ),
        class_name="agent-card", align="center", width="100%",
    )


def report_card(report: rx.Var) -> rx.Component:
    return rx.accordion.root(
        rx.accordion.item(
            header=rx.hstack(
                rx.vstack(
                    rx.text(report["producer"], class_name="eyebrow"),
                    rx.heading(report["title"], size="5"),
                    spacing="1",
                    align="start",
                ),
                rx.spacer(),
                rx.badge("REV " + report["revision"].to(str), variant="surface", color_scheme="gray"),
                width="100%",
                align="center",
            ),
            content=rx.vstack(
                rx.separator(size="4"),
                rx.markdown(report["content"], use_raw=False, class_name="report-markdown"),
                spacing="4",
                align="start",
                width="100%",
            ),
            value=report["key"].to(str),
        ),
        type="single",
        collapsible=True,
        variant="ghost",
        class_name="panel report-card",
        width="100%",
    )


def reports_tab() -> rx.Component:
    return rx.cond(
        AppState.reports.length() > 0,
        rx.vstack(rx.foreach(AppState.reports, report_card), spacing="4", width="100%", padding_top="1rem"),
        empty_state("file-text", "Reports are pending", "Each report appears as soon as its producer completes."),
    )


def debate_tab() -> rx.Component:
    return rx.cond(
        AppState.debate_reports.length() > 0,
        rx.vstack(
            rx.callout("Research alternates Bull and Bear; risk discussion rotates Aggressive, Conservative, and Neutral before manager decisions.", icon="messages-square", color_scheme="blue", size="1", width="100%"),
            rx.foreach(AppState.debate_reports, report_card), spacing="4", width="100%", padding_top="1rem",
        ),
        empty_state("messages-square", "Debate has not started", "Durable debate histories appear here round by round."),
    )


def activity_tab() -> rx.Component:
    return rx.cond(
        AppState.activity.length() > 0,
        rx.vstack(rx.foreach(AppState.activity, activity_row), spacing="0", width="100%", padding_top="1rem", class_name="activity-feed"),
        empty_state("radio", "No activity yet", "Messages, safe tool summaries, status changes, and errors appear in sequence."),
    )


def activity_row(item: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text("#" + item["sequence"].to(int).to_string(), size="1", color=ACCENT, class_name="mono", width="3.5rem"),
        rx.text(item["time"], size="1", color=MUTED, class_name="mono", width="4.5rem"),
        rx.badge(item["type"], variant="surface", color_scheme="gray", min_width="6.5rem"),
        rx.vstack(rx.text(item["agent"], size="1", color=MUTED), rx.text(item["summary"], size="2"), spacing="1", align="start"),
        padding="0.9rem", border_bottom=f"1px solid {BORDER}", width="100%", align="start",
    )


def configuration_tab() -> rx.Component:
    return rx.card(
        rx.data_list.root(
            rx.foreach(AppState.config_rows, lambda item: rx.data_list.item(rx.data_list.label(item["label"]), rx.data_list.value(item["value"]))),
        ), class_name="panel config-panel", margin_top="1rem",
    )


def artifacts_tab() -> rx.Component:
    return rx.cond(
        AppState.artifacts.length() > 0,
        rx.grid(rx.foreach(AppState.artifacts, artifact_card), columns=rx.breakpoints(initial="1", md="2"), spacing="4", width="100%", padding_top="1rem"),
        empty_state("archive", "Artifacts are pending", "Completed runs provide Markdown, ZIP, JSON, and redacted activity downloads."),
    )


def artifact_card(item: rx.Var) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.center(rx.icon("file-down", size=20, color=ACCENT), class_name="empty-icon"),
            rx.vstack(rx.text(item["label"], weight="bold"), rx.text(item["format"], size="1", color=MUTED), spacing="1", align="start"),
            rx.spacer(),
            rx.icon_button("download", on_click=AppState.download_artifact(item["kind"]), color_scheme="teal", variant="soft", aria_label="Download artifact"),
            align="center",
        ), class_name="panel", width="100%",
    )


def memory_page() -> rx.Component:
    filters = rx.card(
        rx.grid(
            field("Ticker", rx.input(value=AppState.memory_ticker, on_change=AppState.set_memory_ticker, placeholder="Filter ticker", width="100%")),
            field("Outcome", rx.select(["all", "pending", "resolved"], value=rx.cond(AppState.memory_status == "", "all", AppState.memory_status), on_change=AppState.set_memory_status_filter, width="100%")),
            field("Rating", rx.select(["all", "Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"], value=rx.cond(AppState.memory_rating == "", "all", AppState.memory_rating), on_change=AppState.set_memory_rating_filter, width="100%")),
            field("Decision from", rx.input(type="date", value=AppState.memory_date_from, on_change=AppState.set_memory_date_from, width="100%")),
            field("Decision to", rx.input(type="date", value=AppState.memory_date_to, on_change=AppState.set_memory_date_to, width="100%")),
            rx.button(rx.icon("search", size=15), "Apply filters", on_click=AppState.load_memory, color_scheme="teal", variant="soft", align_self="end"),
            columns=rx.breakpoints(initial="1", md="3", xl="6"), spacing="3", width="100%", align_items="end",
        ), class_name="panel", width="100%",
    )
    content = rx.vstack(
        page_header("KNOWLEDGE / MEMORY", "Decision memory", "Read-only journal of prior decisions, five-day outcomes, benchmark alpha, and reflections."),
        rx.callout("Raw return is the instrument’s move across the stored holding window. Alpha is that return minus the configured benchmark over the same dates.", icon="info", color_scheme="blue", size="1", width="100%"),
        filters,
        rx.cond(
            AppState.memory_entries.length() > 0,
            rx.vstack(rx.foreach(AppState.memory_entries, memory_card), spacing="4", width="100%"),
            empty_state("brain", "No memory entries", "Entries are appended after completed portfolio decisions and resolve on a later same-ticker run."),
        ),
        class_name="content", align="start",
    )
    return app_shell(content, "memory")


def memory_card(item: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.hstack(rx.text(item["ticker"], size="5", weight="bold", class_name="mono"), signal_badge(item["rating"]), spacing="2"),
                    rx.text("Trade date " + item["date"].to(str) + " · Resolution " + item["resolved_label"].to(str), size="1", color=MUTED),
                    spacing="1", align="start",
                ),
                rx.spacer(),
                rx.cond(item["pending"], rx.badge("PENDING", color_scheme="amber", variant="soft"), rx.badge("RESOLVED", color_scheme="green", variant="soft")),
                width="100%", align="center",
            ),
            rx.grid(
                detail_metric("Raw return", item["raw_label"], "chart-no-axes-combined"),
                detail_metric("Alpha vs benchmark", item["alpha_label"], "scale"),
                detail_metric("Holding window", rx.cond(item["holding"], item["holding"], "—"), "calendar-days"),
                columns=rx.breakpoints(initial="1", sm="3"), spacing="3", width="100%",
            ),
            rx.accordion.root(
                rx.accordion.item(
                    header="Decision and reflection",
                    content=rx.vstack(
                        rx.markdown(item["decision"], use_raw=False, class_name="report-markdown"),
                        rx.cond(
                            item["reflection"] != "",
                            rx.vstack(rx.separator(size="4"), rx.text("REFLECTION", class_name="eyebrow"), rx.markdown(item["reflection"], use_raw=False, class_name="report-markdown"), spacing="3", align="start", width="100%"),
                            rx.text("The full five-trading-day outcome window has not resolved, or market data remains unavailable.", size="2", color=MUTED),
                        ),
                        spacing="3", align="start",
                    ), value="detail",
                ), type="single", collapsible=True, width="100%",
            ),
            spacing="4", align="start",
        ), class_name="panel", width="100%",
    )


def credential_row(item: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["provider"], weight="medium")),
        rx.table.cell(rx.text(item["env"], size="1", class_name="mono")),
        rx.table.cell(rx.match(
            item["status"],
            ("Configured", rx.badge("Configured", color_scheme="green", variant="soft")),
            ("Optional", rx.badge("Optional", color_scheme="gray", variant="surface")),
            rx.badge("Missing", color_scheme="amber", variant="soft"),
        )),
        rx.table.cell(rx.text(item["source"], size="1", color=MUTED)),
    )


def settings_page() -> rx.Component:
    overview = rx.vstack(
        rx.grid(
            metric_card("radio-tower", "Worker", AppState.health["worker_label"], AppState.health["worker_note"]),
            metric_card("database", "Database", rx.cond(AppState.health["database_ok"], "Ready", "Blocked"), AppState.health["database_path"], "#77a7ff"),
            metric_card("hard-drive", "Storage", rx.cond(AppState.health["storage_ok"], "Writable", "Blocked"), AppState.health["storage_free"], "#69df9d"),
            metric_card("list-ordered", "Queue", AppState.health["queue"], "Single durable worker", "#b8a5ff"),
            columns=rx.breakpoints(initial="1", sm="2", xl="4"), spacing="4", width="100%",
        ),
        rx.card(
            rx.hstack(
                rx.hstack(rx.icon("package-check", size=16, color=ACCENT), rx.text("App " + AppState.health["version"].to(str), size="2"), spacing="2"),
                rx.separator(orientation="vertical"),
                rx.hstack(rx.icon("git-commit-horizontal", size=16, color=ACCENT), rx.text(AppState.health["commit"], size="2", class_name="mono"), spacing="2"),
                rx.spacer(),
                rx.hstack(rx.icon("box", size=16, color=rx.cond(AppState.health["ollama_ok"].to(bool), ACCENT, MUTED)), rx.text("Ollama · " + AppState.health["ollama_label"].to(str), size="2", color=MUTED), spacing="2"),
                width="100%", align="center", wrap="wrap",
            ), class_name="panel system-strip", width="100%",
        ),
        rx.card(
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(rx.table.column_header_cell("Setting"), rx.table.column_header_cell("Effective value"), rx.table.column_header_cell("Source"))),
                    rx.table.body(rx.foreach(
                        AppState.settings_rows,
                        lambda item: rx.table.row(
                            rx.table.cell(item["label"]),
                            rx.table.cell(rx.text(item["value"], class_name="mono", size="1")),
                            rx.table.cell(rx.badge(item["source"], variant="surface", color_scheme="gray")),
                        ),
                    )), width="100%",
                ), overflow_x="auto",
            ), class_name="panel table-panel", width="100%",
        ),
        spacing="4", width="100%", padding_top="1rem",
    )
    credentials = rx.vstack(
        rx.callout("Secret values are write-only. The console stores only presence, source, and update state; secrets never enter a run record or download.", icon="shield-check", color_scheme="blue", width="100%"),
        rx.card(
            rx.vstack(
                section_title("TRUSTED ADMIN", "Add or rotate credential"),
                rx.grid(
                    field("Environment variable", rx.select(AppState.secret_names, value=AppState.secret_name, on_change=AppState.set_secret_name, width="100%")),
                    field("Secret value", rx.input(type="password", value=AppState.secret_value, on_change=AppState.set_secret_value, placeholder="Value is never echoed", width="100%")),
                    columns=rx.breakpoints(initial="1", md="2"), spacing="4", width="100%",
                ),
                rx.button(rx.icon("save", size=15), "Save credential", on_click=AppState.save_secret, color_scheme="teal"),
                rx.cond(AppState.toast_message != "", rx.callout(AppState.toast_message, icon="circle-check", color_scheme="green", size="1", width="100%"), rx.fragment()),
                spacing="4", align="start",
            ), class_name="panel", width="100%",
        ),
        rx.card(
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(rx.table.column_header_cell("Provider"), rx.table.column_header_cell("Credential"), rx.table.column_header_cell("Status"), rx.table.column_header_cell("Source"))),
                    rx.table.body(rx.foreach(AppState.credentials, credential_row)), width="100%",
                ), overflow_x="auto",
            ), class_name="panel table-panel", width="100%",
        ),
        spacing="4", width="100%", padding_top="1rem",
    )
    content = rx.vstack(
        page_header("SYSTEM / SETTINGS", "Settings & health", "Inspect effective defaults, credential presence, durable storage, and worker availability."),
        rx.cond(AppState.app_error != "", rx.callout(AppState.app_error, icon="triangle-alert", color_scheme="red"), rx.fragment()),
        rx.tabs.root(
            rx.tabs.list(rx.tabs.trigger("System & defaults", value="system"), rx.tabs.trigger("Credentials", value="credentials")),
            rx.tabs.content(overview, value="system"), rx.tabs.content(credentials, value="credentials"),
            default_value="system", width="100%",
        ),
        class_name="content", align="start",
    )
    return app_shell(content, "settings")
