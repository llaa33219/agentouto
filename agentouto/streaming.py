from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from agentouto.agent import Agent
from agentouto.context import Attachment
from agentouto.provider import Provider
from agentouto.tool import Tool


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
    *,
    attachments: list[Attachment] | None = None,
) -> AsyncIterator[StreamEvent]:
    from agentouto.router import Router
    from agentouto.runtime import Runtime

    router = Router(agents, tools, providers)
    runtime = Runtime(router)
    async for event in runtime.execute_stream(entry, message, attachments=attachments):
        yield event
