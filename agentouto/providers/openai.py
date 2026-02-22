from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ToolCall
from agentouto.exceptions import ProviderError
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend

logger = logging.getLogger("agentouto")


class OpenAIBackend(ProviderBackend):
    def __init__(self) -> None:
        self._clients: dict[str, AsyncOpenAI] = {}

    def _get_client(self, provider: Provider) -> AsyncOpenAI:
        if provider.name not in self._clients:
            self._clients[provider.name] = AsyncOpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
            )
        return self._clients[provider.name]

    async def call(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> LLMResponse:
        client = self._get_client(provider)

        messages = _build_messages(context)
        openai_tools = _build_tools(tools)

        params: dict[str, Any] = {
            "model": agent.model,
            "messages": messages,
            **agent.extra,
        }
        if agent.max_output_tokens is not None:
            params["max_completion_tokens"] = agent.max_output_tokens
        if openai_tools:
            params["tools"] = openai_tools
        if agent.reasoning:
            params["reasoning_effort"] = agent.reasoning_effort
        else:
            params["temperature"] = agent.temperature

        try:
            response = await client.chat.completions.create(**params)
        except Exception as exc:
            raise ProviderError(provider.name, str(exc)) from exc

        if not response.choices:
            raise ProviderError(provider.name, "Empty response: no choices returned")

        msg = response.choices[0].message

        parsed_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                parsed_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=_parse_tool_arguments(tc.function.arguments),
                    )
                )

        return LLMResponse(content=msg.content, tool_calls=parsed_calls)

    async def stream(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> AsyncIterator[str | LLMResponse]:
        client = self._get_client(provider)

        messages = _build_messages(context)
        openai_tools = _build_tools(tools)

        params: dict[str, Any] = {
            "model": agent.model,
            "messages": messages,
            "stream": True,
            **agent.extra,
        }
        if agent.max_output_tokens is not None:
            params["max_completion_tokens"] = agent.max_output_tokens
        if openai_tools:
            params["tools"] = openai_tools
        if agent.reasoning:
            params["reasoning_effort"] = agent.reasoning_effort
        else:
            params["temperature"] = agent.temperature

        try:
            response_stream = await client.chat.completions.create(**params)
        except Exception as exc:
            raise ProviderError(provider.name, str(exc)) from exc

        accumulated_content = ""
        accumulated_tool_calls: dict[int, dict[str, str]] = {}

        async for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                accumulated_content += delta.content
                yield delta.content

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        accumulated_tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            accumulated_tool_calls[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            accumulated_tool_calls[idx]["arguments"] += (
                                tc_delta.function.arguments
                            )

        parsed_calls: list[ToolCall] = []
        for idx in sorted(accumulated_tool_calls):
            tc = accumulated_tool_calls[idx]
            parsed_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=_parse_tool_arguments(tc["arguments"]),
                )
            )

        yield LLMResponse(
            content=accumulated_content or None, tool_calls=parsed_calls
        )


def _build_attachment_parts(attachments: list[Attachment]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for att in attachments:
        if att.mime_type.startswith("image/"):
            url = att.url or f"data:{att.mime_type};base64,{att.data}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
        elif att.mime_type.startswith("audio/"):
            fmt = att.mime_type.split("/")[-1]
            parts.append({"type": "input_audio", "input_audio": {"data": att.data, "format": fmt}})
    return parts


def _build_messages(context: Context) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": context.system_prompt}
    ]

    for msg in context.messages:
        if msg.role == "user":
            if msg.attachments:
                content_parts: list[dict[str, Any]] = [
                    {"type": "text", "text": msg.content or ""}
                ]
                content_parts.extend(_build_attachment_parts(msg.attachments))
                messages.append({"role": "user", "content": content_parts})
            else:
                messages.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(entry)
        elif msg.role == "tool":
            if msg.attachments:
                content_parts = [
                    {"type": "text", "text": msg.content or ""}
                ]
                content_parts.extend(_build_attachment_parts(msg.attachments))
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": content_parts,
                })
            else:
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content or "",
                })

    return messages


def _build_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [{"type": "function", "function": t} for t in tools]


def _parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    """Parse JSON tool-call arguments, repairing common LLM formatting issues.

    Always returns a ``dict``.  When the raw string is malformed or not a JSON
    object, an empty dict is returned so that the tool fails with a clear error
    about missing arguments rather than propagating an opaque ``{"raw": ...}``
    wrapper that poisons the conversation history.
    """
    if not raw or not raw.strip():
        return {}

    text = raw.strip()

    # Strip markdown code fences:  ```json\n...\n```  or  ```\n...\n```
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if not text:
            return {}

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        repaired = _repair_incomplete_json(text)
        if repaired is not None:
            try:
                parsed = json.loads(repaired)
            except (json.JSONDecodeError, TypeError, ValueError):
                parsed = None
        else:
            parsed = None
        if not isinstance(parsed, dict):
            logger.warning("Malformed tool arguments: %.200s", raw)
            return {}
        return parsed

    if isinstance(parsed, dict):
        return parsed

    logger.warning(
        "Tool arguments parsed to %s instead of dict: %.200s",
        type(parsed).__name__,
        raw,
    )
    return {}


def _repair_incomplete_json(text: str) -> str | None:
    """Try to repair truncated JSON by appending missing closing brackets."""
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    if open_braces <= 0 and open_brackets <= 0:
        return None
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        text += '"'
    return text + "]" * open_brackets + "}" * open_braces
