from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from agnetouto.agent import Agent
from agnetouto.context import Context, ToolCall
from agnetouto.exceptions import ProviderError
from agnetouto.provider import Provider
from agnetouto.providers import LLMResponse, ProviderBackend


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
            "max_completion_tokens": agent.max_output_tokens,
            **agent.extra,
        }
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
                try:
                    arguments = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {"raw": tc.function.arguments}
                parsed_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=arguments,
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
            "max_completion_tokens": agent.max_output_tokens,
            "stream": True,
            **agent.extra,
        }
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
            try:
                arguments = json.loads(tc["arguments"])
            except (json.JSONDecodeError, TypeError):
                arguments = {"raw": tc["arguments"]}
            parsed_calls.append(
                ToolCall(id=tc["id"], name=tc["name"], arguments=arguments)
            )

        yield LLMResponse(
            content=accumulated_content or None, tool_calls=parsed_calls
        )


def _build_messages(context: Context) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": context.system_prompt}
    ]

    for msg in context.messages:
        if msg.role == "user":
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
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content or "",
                }
            )

    return messages


def _build_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [{"type": "function", "function": t} for t in tools]
