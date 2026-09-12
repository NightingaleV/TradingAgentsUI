"""Reusable LangChain callback metrics for CLI and durable workers."""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult


class StatsCallbackHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        with self._lock:
            self.llm_calls += 1

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], **kwargs: Any) -> None:
        with self._lock:
            self.llm_calls += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            message = response.generations[0][0].message
            usage = message.usage_metadata if isinstance(message, AIMessage) else None
        except (AttributeError, IndexError, TypeError):
            return
        if usage:
            with self._lock:
                self.tokens_in += usage.get("input_tokens", 0)
                self.tokens_out += usage.get("output_tokens", 0)

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        with self._lock:
            self.tool_calls += 1

    def get_stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
            }
