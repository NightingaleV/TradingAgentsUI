"""Public provider metadata shared by CLI-independent application surfaces."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.model_catalog import get_model_options


@dataclass(frozen=True)
class ProviderMetadata:
    key: str
    label: str
    backend_url: str | None
    credential_env: str | None
    credential_required: bool
    region: str | None = None
    custom_models_only: bool = False


_PROVIDERS: tuple[ProviderMetadata, ...] = (
    ProviderMetadata("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY", True),
    ProviderMetadata("google", "Google Gemini", None, "GOOGLE_API_KEY", True),
    ProviderMetadata("anthropic", "Anthropic", "https://api.anthropic.com/", "ANTHROPIC_API_KEY", True),
    ProviderMetadata("xai", "xAI", "https://api.x.ai/v1", "XAI_API_KEY", True),
    ProviderMetadata("deepseek", "DeepSeek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", True),
    ProviderMetadata("qwen", "Qwen · International", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY", True, "International"),
    ProviderMetadata("qwen-cn", "Qwen · China", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_CN_API_KEY", True, "China"),
    ProviderMetadata("glm", "GLM · International", "https://api.z.ai/api/paas/v4/", "ZHIPU_API_KEY", True, "International"),
    ProviderMetadata("glm-cn", "GLM · China", "https://open.bigmodel.cn/api/paas/v4/", "ZHIPU_CN_API_KEY", True, "China"),
    ProviderMetadata("minimax", "MiniMax · Global", "https://api.minimax.io/v1", "MINIMAX_API_KEY", True, "Global"),
    ProviderMetadata("minimax-cn", "MiniMax · China", "https://api.minimaxi.com/v1", "MINIMAX_CN_API_KEY", True, "China"),
    ProviderMetadata("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", True, custom_models_only=True),
    ProviderMetadata("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", True, custom_models_only=True),
    ProviderMetadata("kimi", "Kimi · Moonshot", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY", True, custom_models_only=True),
    ProviderMetadata("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", True, custom_models_only=True),
    ProviderMetadata("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", True, custom_models_only=True),
    ProviderMetadata("azure", "Azure OpenAI", None, "AZURE_OPENAI_API_KEY", True, custom_models_only=True),
    ProviderMetadata("bedrock", "Amazon Bedrock", None, None, False, custom_models_only=True),
    ProviderMetadata("ollama", "Ollama", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"), None, False),
    ProviderMetadata("openai_compatible", "OpenAI-compatible endpoint", None, "OPENAI_COMPATIBLE_API_KEY", False, custom_models_only=True),
)

PROVIDER_CATALOG: dict[str, ProviderMetadata] = {provider.key: provider for provider in _PROVIDERS}


def list_providers() -> list[dict]:
    """Return serializable provider metadata in stable display order."""
    return [asdict(provider) for provider in _PROVIDERS]


def provider_metadata(provider: str) -> ProviderMetadata:
    try:
        return PROVIDER_CATALOG[provider.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported LLM provider: {provider}") from exc


def provider_models(provider: str, mode: str) -> list[tuple[str, str]]:
    """Return curated models, falling back to a custom-ID choice."""
    try:
        options = list(get_model_options(provider, mode))
    except KeyError:
        return [("Custom model ID", "custom")]
    if not any(value == "custom" for _, value in options):
        options.append(("Custom model ID", "custom"))
    return options


def credential_status(provider: str, extra_env: dict[str, str] | None = None) -> dict:
    """Return presence-only credential status; secret bytes never leave this module."""
    metadata = provider_metadata(provider)
    env_name = get_api_key_env(provider)
    if not env_name:
        return {
            "provider": provider,
            "env": None,
            "configured": True,
            "required": metadata.credential_required,
            "source": "credential chain" if provider == "bedrock" else "not required",
        }
    value = (extra_env or {}).get(env_name) or os.environ.get(env_name)
    return {
        "provider": provider,
        "env": env_name,
        "configured": bool(value),
        "required": metadata.credential_required,
        "source": "web secret" if (extra_env or {}).get(env_name) else ("environment" if value else "missing"),
    }


def provider_is_key_optional(provider: str) -> bool:
    return provider.lower() in {"ollama", "openai_compatible"}
