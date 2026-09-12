"""Write-only local secret store used by the trusted-admin settings page."""

from __future__ import annotations

import os
import re
from pathlib import Path

from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV

from .database import webui_root


SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,80}$")
KNOWN_SECRET_NAMES = {name for name in PROVIDER_API_KEY_ENV.values() if name}
KNOWN_SECRET_NAMES.update({
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "ALPHA_VANTAGE_API_KEY",
    "FRED_API_KEY",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
})


def secret_path() -> Path:
    return Path(os.getenv("TRADINGAGENTS_WEB_SECRETS", webui_root() / "secrets.env")).expanduser()


def load_secrets() -> dict[str, str]:
    path = secret_path()
    if not path.exists():
        return {}
    secrets: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if SECRET_NAME_RE.fullmatch(name):
            secrets[name] = value.strip()
    return secrets


def store_secret(name: str, value: str) -> None:
    name = name.strip().upper()
    if name not in KNOWN_SECRET_NAMES:
        raise ValueError("That credential name is not on the web-console allowlist.")
    if not value or "\n" in value or "\r" in value:
        raise ValueError("Credential value must be a non-empty single line.")
    path = secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets()
    secrets[name] = value.strip()
    body = "# TradingAgents web secrets — values are write-only in the UI.\n"
    body += "\n".join(f"{key}={secrets[key]}" for key in sorted(secrets)) + "\n"
    temp = path.with_suffix(".tmp")
    temp.write_text(body, encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def export_secrets_to_environment() -> None:
    for key, value in load_secrets().items():
        os.environ[key] = value


def secret_status(name: str) -> dict:
    web_value = load_secrets().get(name)
    env_value = os.environ.get(name)
    return {
        "name": name,
        "configured": bool(web_value or env_value),
        "source": "web secret" if web_value else ("environment" if env_value else "missing"),
        "updated_at": (
            secret_path().stat().st_mtime if web_value and secret_path().exists() else None
        ),
    }
