import os

import reflex as rx


config = rx.Config(
    app_name="tradingagents_web",
    app_module_import="tradingagents.web.app",
    frontend_port=8501,
    backend_port=8000,
    backend_host="0.0.0.0",
    api_url=os.getenv("REFLEX_API_URL", "http://localhost:8501"),
    deploy_url=os.getenv("REFLEX_DEPLOY_URL", "http://localhost:8501"),
    telemetry_enabled=False,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                appearance="dark",
                accent_color="teal",
                gray_color="slate",
                radius="large",
                panel_background="translucent",
            )
        )
    ],
)
