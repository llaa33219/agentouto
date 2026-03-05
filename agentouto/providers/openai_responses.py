from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ToolCall
from agentouto.exceptions import ProviderError
from agentouto.model_metadata import resolve_max_output_tokens
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend
from agentouto.providers.openai import _parse_tool_arguments

logger = logging.getLogger("agentouto")


class OpenAIResponsesBackend(ProviderBackend):
    def __init__(self) -> None:
        self._clients: dict[str, tuple[str, AsyncOpenAI]] = {}

    def _get_client(self, provider: Provider, api_key: str) -> AsyncOpenAI:
        cached = self._clients.get(provider.name)
        if cached is not None and cached[0] == api_key:
            return cached[1]
        client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url)
        self._clients[provider.name] = (api_key, client)
        return client

    async def call(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> LLMResponse:
        api_key = await provider.resolve_api_key()
        client = self._get_client(provider, api_key)

        input_items = _build_input(context)
        response_tools = _build_tools(tools)

        params: dict[str, Any] = {
            "model": agent.model,
            "input": input_items,
            "instructions": context.system_prompt,
            **agent.extra,
        }
        max_tokens = resolve_max_output_tokens(agent.model, agent.max_output_tokens)
        if max_tokens is not None:
            params["max_output_tokens"] = max_tokens
        if response_tools:
            params["tools"] = response_tools
        if agent.reasoning:
            params["reasoning"] = {"effort": agent.reasoning_effort}
        else:
            params["temperature"] = agent.temperature

        try:
            response = await client.responses.create(**params)
        except Exception as exc:
            raise ProviderError(provider.name, str(exc)) from exc

        return _parse_response(response)

    async def stream(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> AsyncIterator[str | LLMResponse]:
        api_key = await provider.resolve_api_key()
        client = self._get_client(provider, api_key)

        input_items = _build_input(context)
        response_tools = _build_tools(tools)

        params: dict[str, Any] = {
            "model": agent.model,
            "input": input_items,
            "instructions": context.system_prompt,
            "stream": True,
            **agent.extra,
        }
        max_tokens = resolve_max_output_tokens(agent.model, agent.max_output_tokens)
        if max_tokens is not None:
            params["max_output_tokens"] = max_tokens
        if response_tools:
            params["tools"] = response_tools
        if agent.reasoning:
            params["reasoning"] = {"effort": agent.reasoning_effort}
        else:
            params["temperature"] = agent.temperature

        try:
            response_stream = await client.responses.create(**params)
        except Exception as exc:
            raise ProviderError(provider.name, str(exc)) from exc

        accumulated_text = ""
        tool_calls_buffer: dict[int, dict[str, str]] = {}

        async for event in response_stream:
            event_type = getattr(event, "type", "")

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    accumulated_text += delta
                    yield delta

            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", "") == "function_call":
                    idx = getattr(event, "output_index", len(tool_calls_buffer))
                    tool_calls_buffer[idx] = {
                        "call_id": getattr(item, "call_id", "") or "",
                        "name": getattr(item, "name", "") or "",
                        "arguments": "",
                    }

            elif event_type == "response.function_call_arguments.delta":
                delta = getattr(event, "delta", "")
                idx = getattr(event, "output_index", -1)
                if idx in tool_calls_buffer and delta:
                    tool_calls_buffer[idx]["arguments"] += delta

        parsed_calls: list[ToolCall] = []
        for idx in sorted(tool_calls_buffer):
            tc = tool_calls_buffer[idx]
            parsed_calls.append(
                ToolCall(
                    id=tc["call_id"],
                    name=tc["name"],
                    arguments=_parse_tool_arguments(tc["arguments"]),
                )
            )

        yield LLMResponse(
            content=accumulated_text or None, tool_calls=parsed_calls
        )


def _build_attachment_parts(attachments: list[Attachment]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for att in attachments:
        if att.mime_type.startswith("image/"):
            url = att.url or f"data:{att.mime_type};base64,{att.data}"
            parts.append({"type": "input_image", "image_url": url})
        elif att.mime_type.startswith("audio/"):
            fmt = att.mime_type.split("/")[-1]
            parts.append({"type": "input_audio", "data": att.data, "format": fmt})
    return parts


def _build_input(context: Context) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for msg in context.messages:
        if msg.role == "user":
            if msg.attachments:
                content_parts: list[dict[str, Any]] = [
                    {"type": "input_text", "text": msg.content or ""}
                ]
                content_parts.extend(_build_attachment_parts(msg.attachments))
                items.append({"role": "user", "content": content_parts})
            else:
                items.append({"role": "user", "content": msg.content or ""})
        elif msg.role == "assistant":
            if msg.content:
                items.append({"role": "assistant", "content": msg.content})
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    items.append({
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    })
        elif msg.role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": msg.tool_call_id,
                "output": msg.content or "",
            })

    return items


def _build_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [{"type": "function", **t} for t in tools]


def _parse_response(response: Any) -> LLMResponse:
    tool_calls: list[ToolCall] = []

    for item in response.output:
        if getattr(item, "type", "") == "function_call":
            tool_calls.append(
                ToolCall(
                    id=getattr(item, "call_id", "") or "",
                    name=getattr(item, "name", "") or "",
                    arguments=_parse_tool_arguments(
                        getattr(item, "arguments", None)
                    ),
                )
            )

    content = getattr(response, "output_text", None) or None

    return LLMResponse(content=content, tool_calls=tool_calls)
