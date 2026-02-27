from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ToolCall
from agentouto.exceptions import ProviderError
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend

logger = logging.getLogger("agentouto")

_max_tokens_cache: dict[str, int] = {}
_PROBE_MAX_TOKENS = 999_999_999
_DEFAULT_MAX_TOKENS = 8192
_MAX_TOKENS_RE = re.compile(r"> (\d+),")
_MAX_TOKENS_FALLBACK_RE = re.compile(r"\bis\s+(\d+)")


class AnthropicBackend(ProviderBackend):
    def __init__(self) -> None:
        self._clients: dict[str, tuple[str, AsyncAnthropic]] = {}

    def _get_client(self, provider: Provider, api_key: str) -> AsyncAnthropic:
        cached = self._clients.get(provider.name)
        if cached is not None and cached[0] == api_key:
            return cached[1]
        client = AsyncAnthropic(api_key=api_key, base_url=provider.base_url)
        self._clients[provider.name] = (api_key, client)
        return client

    async def call(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> LLMResponse:
        response: LLMResponse | None = None
        async for chunk in self._stream_response(context, tools, agent, provider):
            if isinstance(chunk, LLMResponse):
                response = chunk
        if response is None:
            raise ProviderError(provider.name, "Empty response: no content from stream")
        return response

    async def stream(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> AsyncIterator[str | LLMResponse]:
        async for chunk in self._stream_response(context, tools, agent, provider):
            yield chunk

    async def _stream_response(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> AsyncIterator[str | LLMResponse]:
        api_key = await provider.resolve_api_key()
        client = self._get_client(provider, api_key)

        messages = _build_messages(context)
        anthropic_tools = _build_tools(tools)

        max_tokens = agent.max_output_tokens
        if max_tokens is None:
            max_tokens = _max_tokens_cache.get(agent.model, _PROBE_MAX_TOKENS)

        params: dict[str, Any] = {
            "model": agent.model,
            "system": context.system_prompt,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
            **agent.extra,
        }
        if anthropic_tools:
            params["tools"] = anthropic_tools
        if agent.reasoning:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": agent.reasoning_budget or 4096,
            }
            params["temperature"] = 1
        else:
            params["temperature"] = agent.temperature

        try:
            response_stream = await client.messages.create(**params)
        except Exception as exc:
            if agent.max_output_tokens is not None or agent.model in _max_tokens_cache:
                raise ProviderError(provider.name, str(exc)) from exc
            error_str = str(exc)
            resolved = _parse_max_tokens_from_error(error_str)
            if resolved is None:
                if "max_tokens" not in error_str.lower():
                    raise ProviderError(provider.name, error_str) from exc
                resolved = _DEFAULT_MAX_TOKENS
                logger.warning(
                    "Could not discover max_tokens for %s, using %d",
                    agent.model, resolved,
                )
            else:
                logger.info(
                    "Discovered max_tokens=%d for %s", resolved, agent.model,
                )
                _max_tokens_cache[agent.model] = resolved
            params["max_tokens"] = resolved
            try:
                response_stream = await client.messages.create(**params)
            except Exception as retry_exc:
                raise ProviderError(provider.name, str(retry_exc)) from retry_exc

        accumulated_content = ""
        tool_blocks: dict[int, dict[str, Any]] = {}

        async for event in response_stream:
            if event.type == "content_block_start":
                if event.content_block.type == "tool_use":
                    tool_blocks[event.index] = {
                        "id": event.content_block.id,
                        "name": event.content_block.name,
                        "input_json": "",
                    }
            elif event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    accumulated_content += event.delta.text
                    yield event.delta.text
                elif event.delta.type == "input_json_delta":
                    if event.index in tool_blocks:
                        tool_blocks[event.index]["input_json"] += event.delta.partial_json

        if max_tokens == _PROBE_MAX_TOKENS and agent.model not in _max_tokens_cache:
            _max_tokens_cache[agent.model] = _PROBE_MAX_TOKENS

        if not accumulated_content and not tool_blocks:
            raise ProviderError(provider.name, "Empty response: no content blocks returned")

        parsed_calls: list[ToolCall] = []
        for idx in sorted(tool_blocks):
            tb = tool_blocks[idx]
            try:
                arguments = json.loads(tb["input_json"]) if tb["input_json"] else {}
            except (json.JSONDecodeError, TypeError):
                logger.warning("Malformed tool input JSON: %.200s", tb["input_json"])
                arguments = {}
            parsed_calls.append(
                ToolCall(id=tb["id"], name=tb["name"], arguments=arguments)
            )

        yield LLMResponse(
            content=accumulated_content or None, tool_calls=parsed_calls,
        )


def _parse_max_tokens_from_error(error_msg: str) -> int | None:
    """Extract the maximum allowed output tokens from an Anthropic API error.

    Anthropic returns errors like:
        ``max_tokens: 999999 > 64000, which is the maximum allowed ...``
    """
    match = _MAX_TOKENS_RE.search(error_msg)
    if match:
        return int(match.group(1))
    match = _MAX_TOKENS_FALLBACK_RE.search(error_msg)
    if match:
        return int(match.group(1))
    return None


def _build_attachment_blocks(attachments: list[Attachment]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for att in attachments:
        if att.mime_type.startswith("image/"):
            source: dict[str, Any]
            if att.data:
                source = {"type": "base64", "media_type": att.mime_type, "data": att.data}
            elif att.url:
                source = {"type": "url", "url": att.url}
            else:
                continue
            blocks.append({"type": "image", "source": source})
        elif att.mime_type == "application/pdf":
            if att.data:
                source = {"type": "base64", "media_type": att.mime_type, "data": att.data}
            elif att.url:
                source = {"type": "url", "url": att.url}
            else:
                continue
            blocks.append({"type": "document", "source": source})
    return blocks


def _build_messages(context: Context) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    ctx_messages = context.messages
    i = 0

    while i < len(ctx_messages):
        msg = ctx_messages[i]

        if msg.role == "user":
            if msg.attachments:
                content_blocks: list[dict[str, Any]] = [
                    {"type": "text", "text": msg.content or ""}
                ]
                content_blocks.extend(_build_attachment_blocks(msg.attachments))
                messages.append({"role": "user", "content": content_blocks})
            else:
                messages.append({"role": "user", "content": msg.content or ""})
            i += 1

        elif msg.role == "assistant":
            content_blocks = []
            if msg.content:
                content_blocks.append({"type": "text", "text": msg.content})
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
            messages.append({"role": "assistant", "content": content_blocks})
            i += 1

        elif msg.role == "tool":
            tool_results: list[dict[str, Any]] = []
            while i < len(ctx_messages) and ctx_messages[i].role == "tool":
                tmsg = ctx_messages[i]
                if tmsg.attachments:
                    result_content: list[dict[str, Any]] = []
                    if tmsg.content:
                        result_content.append({"type": "text", "text": tmsg.content})
                    result_content.extend(_build_attachment_blocks(tmsg.attachments))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tmsg.tool_call_id,
                        "content": result_content,
                    })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tmsg.tool_call_id,
                        "content": tmsg.content or "",
                    })
                i += 1
            messages.append({"role": "user", "content": tool_results})

        else:
            i += 1

    return messages


def _build_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in tools
    ]
