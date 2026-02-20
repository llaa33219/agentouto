from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from agnetouto.agent import Agent
from agnetouto.provider import Provider
from agnetouto.tool import Tool


@dataclass
class StreamEvent:
    type: Literal["token", "tool_call", "agent_call", "agent_return", "finish", "error"]
    agent_name: str
    data: dict[str, Any] = field(default_factory=dict)


async def async_run_stream(
    entry: Agent,
    message: str,
    agents: list[Agent],
    tools: list[Tool],
    providers: list[Provider],
) -> AsyncIterator[StreamEvent]:
    from agnetouto.router import Router
    from agnetouto.runtime import Runtime

    router = Router(agents, tools, providers)
    runtime = Runtime(router)
    async for event in runtime.execute_stream(entry, message):
        yield event
