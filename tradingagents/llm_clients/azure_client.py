import os
from typing import Any
from urllib.parse import urlparse

from langchain_openai import AzureChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .capabilities import get_capabilities
from .openai_client import DeepSeekChatOpenAI, NormalizedChatOpenAI

_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "api_key", "reasoning_effort", "temperature",
    "max_tokens", "callbacks", "http_client", "http_async_client",
)


class NormalizedAzureChatOpenAI(AzureChatOpenAI):
    """AzureChatOpenAI with normalized content output."""

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


class AzureOpenAIClient(BaseLLMClient):
    """Client for Azure OpenAI and Microsoft Foundry deployments.

    Legacy Azure OpenAI deployment routing uses ``AzureChatOpenAI`` and needs:
        AZURE_OPENAI_API_KEY: API key
        AZURE_OPENAI_ENDPOINT: Endpoint URL (e.g. https://<resource>.openai.azure.com/)
        AZURE_OPENAI_DEPLOYMENT_NAME: Optional shared deployment name
        OPENAI_API_VERSION: API version (e.g. 2025-03-01-preview)

    Microsoft Foundry's current OpenAI-compatible route ends in ``/openai/v1``.
    It accepts the deployment name in the ``model`` field, so it uses
    ``ChatOpenAI`` instead of the deployment-style Azure client. This supports
    Foundry Models such as DeepSeek-V4-Flash and DeepSeek-V4-Pro.
    """

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def _resolved_endpoint(self) -> str | None:
        """Prefer the persisted run endpoint, then preserve Azure's env default."""
        return self.base_url or os.environ.get("AZURE_OPENAI_ENDPOINT")

    def _uses_foundry_v1_route(self) -> bool:
        """Whether this is the OpenAI-compatible Foundry endpoint shape."""
        endpoint = self._resolved_endpoint()
        if not endpoint:
            return False
        return urlparse(endpoint).path.rstrip("/").lower().endswith("/openai/v1")

    def _foundry_v1_llm(self) -> Any:
        """Build a standard OpenAI-compatible client for Foundry v1 routes."""
        api_key = self.kwargs.get("api_key") or os.environ.get("AZURE_OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "AZURE_OPENAI_API_KEY is required for the Azure AI Foundry endpoint."
            )
        llm_kwargs = {
            "model": self.model,
            "base_url": self._resolved_endpoint(),
            "api_key": api_key,
        }
        for key in _PASSTHROUGH_KWARGS:
            if key != "api_key" and key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        chat_class = (
            DeepSeekChatOpenAI
            if get_capabilities(self.model).requires_reasoning_content_roundtrip
            else NormalizedChatOpenAI
        )
        return chat_class(**llm_kwargs)

    def get_llm(self) -> Any:
        """Return a client matched to Azure's selected endpoint route."""
        self.warn_if_unknown_model()
        if self._uses_foundry_v1_route():
            return self._foundry_v1_llm()

        llm_kwargs = {
            "model": self.model,
            "azure_deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", self.model),
        }
        endpoint = self._resolved_endpoint()
        if endpoint:
            llm_kwargs["azure_endpoint"] = endpoint

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return NormalizedAzureChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """Azure accepts any deployed model name."""
        return True
