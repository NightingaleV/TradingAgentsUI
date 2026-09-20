"""Reusable presentation components for the Reflex console."""

from __future__ import annotations

from typing import Any

import reflex as rx

from .state import AppState

ACCENT = "#5dd9c1"
PANEL = "#111923"
BORDER = "#263242"
MUTED = "#8fa0b5"
TEXT = "#eef5fb"


def brand() -> rx.Component:
    return rx.hstack(
        rx.center(
            rx.icon("chart-candlestick", size=22, color="#07110f"),
            width="2.5rem", height="2.5rem", border_radius="0.8rem", background=ACCENT,
        ),
        rx.vstack(
            rx.text("TRADINGAGENTS", class_name="brand-title"),
            rx.text("RESEARCH CONSOLE", class_name="eyebrow"),
            spacing="0", align="start",
        ),
        spacing="3", align="center",
    )


def nav_item(icon: str, label: str, href: str, active: bool = False) -> rx.Component:
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=18), rx.text(label, size="2", weight="medium"),
            width="100%", padding="0.7rem 0.8rem", border_radius="0.65rem", align="center",
            color=TEXT if active else MUTED,
            background="#192634" if active else "transparent",
            border=f"1px solid {BORDER}" if active else "1px solid transparent",
            _hover={"background": "#151f2a", "color": TEXT},
        ),
        href=href, width="100%", text_decoration="none",
    )


def sidebar(active: str) -> rx.Component:
    items = [
        ("layout-dashboard", "Overview", "/", "dashboard"),
        ("plus", "New analysis", "/new-analysis", "new"),
        ("briefcase-business", "Portfolio", "/portfolio", "portfolio"),
        ("history", "Runs", "/runs", "runs"),
        ("brain", "Memory", "/memory", "memory"),
        ("settings", "Settings & health", "/settings", "settings"),
    ]
    return rx.vstack(
        brand(),
        rx.vstack(*[nav_item(icon, label, href, active == key) for icon, label, href, key in items], spacing="1", width="100%"),
        rx.spacer(),
        rx.vstack(
            rx.hstack(
                rx.box(class_name=rx.cond(AppState.health["worker_online"], "status-dot online", "status-dot offline")),
                rx.text(rx.cond(AppState.health["worker_online"], "Worker online", "Worker unavailable"), size="2", color="#c9d5e3"),
                align="center",
            ),
            rx.text("Persistent local workspace", size="1", color=MUTED),
            spacing="2", width="100%", padding="0.85rem", border=f"1px solid {BORDER}", border_radius="0.75rem",
        ),
        class_name="sidebar", align="start",
    )


def mobile_bar(active: str) -> rx.Component:
    return rx.hstack(
        brand(), rx.spacer(),
        rx.dropdown_menu.root(
            rx.dropdown_menu.trigger(rx.button(rx.icon("menu", size=18), variant="soft", color_scheme="gray")),
            rx.dropdown_menu.content(
                rx.dropdown_menu.item("Overview", on_click=rx.redirect("/")),
                rx.dropdown_menu.item("New analysis", on_click=rx.redirect("/new-analysis")),
                rx.dropdown_menu.item("Portfolio", on_click=rx.redirect("/portfolio")),
                rx.dropdown_menu.item("Runs", on_click=rx.redirect("/runs")),
                rx.dropdown_menu.item("Memory", on_click=rx.redirect("/memory")),
                rx.dropdown_menu.separator(),
                rx.dropdown_menu.item("Settings & health", on_click=rx.redirect("/settings")),
            ),
        ),
        class_name="mobile-bar", align="center", width="100%",
    )


def app_shell(content: rx.Component, active: str, *, poll: bool = False) -> rx.Component:
    return rx.box(
        sidebar(active), mobile_bar(active), content,
        rx.cond(poll, rx.moment(interval=1000, on_change=AppState.poll, class_name="poll-clock"), rx.fragment()),
        class_name="app-shell",
    )


def page_header(kicker: str, title: str | rx.Var, description: str | rx.Var, *actions: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(kicker, class_name="eyebrow"), rx.heading(title, size="8", letter_spacing="-0.04em"),
            rx.text(description, size="3", color=MUTED, max_width="48rem"), spacing="2", align="start",
        ),
        rx.spacer(), *actions, align="center", width="100%", wrap="wrap",
    )


def metric_card(icon: str, label: str, value: Any, note: Any, tone: str = ACCENT) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(rx.center(rx.icon(icon, size=17, color=tone), class_name="metric-icon"), rx.text(label, size="2", color=MUTED), justify="between", width="100%"),
            rx.text(value, size="7", weight="bold", letter_spacing="-0.04em"), rx.text(note, size="1", color=MUTED),
            spacing="3", align="start",
        ),
        class_name="panel metric-card",
    )


def status_badge(status: rx.Var | str) -> rx.Component:
    return rx.match(
        status,
        ("completed", rx.badge("COMPLETED", color_scheme="green", variant="soft", radius="full")),
        ("running", rx.badge("RUNNING", color_scheme="blue", variant="soft", radius="full")),
        ("queued", rx.badge("QUEUED", color_scheme="gray", variant="surface", radius="full")),
        ("cancel_requested", rx.badge("CANCELLING", color_scheme="amber", variant="soft", radius="full")),
        ("cancelled", rx.badge("CANCELLED", color_scheme="amber", variant="soft", radius="full")),
        ("failed", rx.badge("FAILED", color_scheme="red", variant="soft", radius="full")),
        rx.badge(status, color_scheme="gray", variant="surface", radius="full"),
    )


def signal_badge(signal: rx.Var | str) -> rx.Component:
    return rx.match(
        signal,
        ("Buy", rx.badge(rx.icon("trending-up", size=13), "BUY", color_scheme="green", size="2", variant="solid")),
        ("Overweight", rx.badge(rx.icon("arrow-up-right", size=13), "OVERWEIGHT", color_scheme="teal", size="2", variant="solid")),
        ("Hold", rx.badge(rx.icon("minus", size=13), "HOLD", color_scheme="gray", size="2", variant="surface")),
        ("Underweight", rx.badge(rx.icon("arrow-down-right", size=13), "UNDERWEIGHT", color_scheme="amber", size="2", variant="soft")),
        ("Sell", rx.badge(rx.icon("trending-down", size=13), "SELL", color_scheme="red", size="2", variant="solid")),
        ("REVIEW", rx.badge(rx.icon("triangle-alert", size=13), "REVIEW", color_scheme="amber", size="2", variant="solid")),
        rx.badge(signal, color_scheme="gray", size="2", variant="surface"),
    )


def empty_state(icon: str, title: str, description: str, action: rx.Component | None = None) -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.center(rx.icon(icon, size=24, color=ACCENT), class_name="empty-icon"), rx.heading(title, size="4"),
            rx.text(description, size="2", color=MUTED, text_align="center", max_width="30rem"), action or rx.fragment(),
            spacing="3", align="center",
        ),
        min_height="14rem", width="100%", class_name="panel empty-state",
    )


def section_title(kicker: str, title: str, description: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(kicker, class_name="eyebrow"), rx.heading(title, size="5"),
        rx.cond(description != "", rx.text(description, size="2", color=MUTED), rx.fragment()),
        spacing="1", align="start",
    )


def field(label: str, control: rx.Component, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium", color="#dbe6f2"), control,
        rx.cond(hint != "", rx.text(hint, size="1", color=MUTED), rx.fragment()),
        spacing="2", align="start", width="100%",
    )


def run_compact_row(run: rx.Var) -> rx.Component:
    return rx.link(
        rx.hstack(
            rx.vstack(rx.hstack(rx.text(run["ticker"], weight="bold", size="3"), status_badge(run["status"]), spacing="2"), rx.text(run["trade_date_label"], size="1", color=MUTED), spacing="1", align="start"),
            rx.spacer(),
            rx.vstack(rx.text(run["active_label"], size="2", color="#cbd8e5"), rx.text(run["duration"], size="1", color=MUTED, class_name="mono"), spacing="1", align="end"),
            rx.icon("chevron-right", size=16, color=MUTED),
            width="100%", align="center", padding="0.9rem 0", border_bottom=f"1px solid {BORDER}",
        ),
        href=run["href"], width="100%", text_decoration="none",
    )
