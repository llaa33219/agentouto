from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentouto.agent import Agent
    from agentouto.context import Context, ToolCall
    from agentouto.provider import Provider
    from agentouto.tool import Tool

_REASONING_TAG_RE = re.compile(
    r"<(think|thinking|reason|reasoning)>.*?(?:</\1>|$)",
    re.DOTALL,
)


def _normalize_stop_reason(value: object) -> str | None:
    """Normalize a vendor terminal status to a lowercase string.

    Returns ``None`` when the vendor exposes no status.  Vendor enums carry
    their symbolic name in ``.name`` (Google's ``FinishReason.STOP`` stringifies
    to ``"1"``), so ``.name`` is preferred over ``str(value)``.
    """
    if value is None:
        return None
    raw = getattr(value, "name", None) or value
    if not isinstance(raw, str):
        return None
    return raw.strip().lower() or None


def _content_outside_reasoning(content: str) -> str:
    """Return *content* with all reasoning-tag blocks removed.

    Use this **before** parsing text for tool-call patterns so that anything
    inside ``<think>``, ``<thinking>``, ``<reason>``, or ``<reasoning>``
    blocks is excluded from detection.  The original content stored in the
    context is never modified.
    """
    return _REASONING_TAG_RE.sub("", content).strip()


@dataclass
class Usage:
    """Token usage from an LLM API call."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def __iadd__(self, other: Usage) -> Usage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        return self


class LLMResponse:
    __slots__ = ("content", "stop_reason", "tool_calls", "usage")

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        usage: Usage | None = None,
        stop_reason: str | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage
        self.stop_reason = stop_reason

    @property
    def content_without_reasoning(self) -> str | None:
        """Content with reasoning tag blocks stripped. ``None`` when empty."""
        if self.content is None:
            return None
        result = _content_outside_reasoning(self.content)
        return result or None


class ProviderBackend(ABC):
    @abstractmethod
    async def call(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> LLMResponse: ...

    async def stream(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> AsyncIterator[str | LLMResponse]:
        """Stream LLM response. Yields str for text chunks, then a final LLMResponse."""
        response = await self.call(context, tools, agent, provider)
        if response.content:
            yield response.content
        yield response


def get_backend(kind: str) -> ProviderBackend:
    if kind == "openai":
        from agentouto.providers.openai import OpenAIBackend
        return OpenAIBackend()
    elif kind == "openai_responses":
        from agentouto.providers.openai_responses import OpenAIResponsesBackend
        return OpenAIResponsesBackend()
    elif kind == "anthropic":
        from agentouto.providers.anthropic import AnthropicBackend
        return AnthropicBackend()
    elif kind == "google":
        from agentouto.providers.google import GoogleBackend
        return GoogleBackend()
    else:
        raise ValueError(f"Unknown provider kind: {kind}")
