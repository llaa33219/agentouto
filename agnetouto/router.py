from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agnetouto._constants import CALL_AGENT, FINISH
from agnetouto.agent import Agent
from agnetouto.context import Context
from agnetouto.exceptions import ProviderError, RoutingError, ToolError
from agnetouto.provider import Provider
from agnetouto.providers import LLMResponse, ProviderBackend, get_backend
from agnetouto.tool import Tool


class Router:
    def __init__(
        self,
        agents: list[Agent],
        tools: list[Tool],
        providers: list[Provider],
    ) -> None:
        self._agents: dict[str, Agent] = {a.name: a for a in agents}
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        self._providers: dict[str, Provider] = {p.name: p for p in providers}
        self._backends: dict[str, ProviderBackend] = {}

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_agent(self, name: str) -> Agent:
        if name not in self._agents:
            raise RoutingError(f"Unknown agent: {name}")
        return self._agents[name]

    def get_tool(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(name, "Tool not found")
        return self._tools[name]

    def build_tool_schemas(self, current_agent: str) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []

        for tool in self._tools.values():
            schemas.append(tool.to_schema())

        schemas.append(
            {
                "name": CALL_AGENT,
                "description": (
                    "Call another agent. The agent will process your message "
                    "and return a result when done."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Name of the agent to call",
                        },
                        "message": {
                            "type": "string",
                            "description": "Message to send to the agent",
                        },
                    },
                    "required": ["agent_name", "message"],
                },
            }
        )

        schemas.append(
            {
                "name": FINISH,
                "description": (
                    "Finish the current task and return a result to the caller. "
                    "The caller may be a user or another agent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Result message to return",
                        },
                    },
                    "required": ["message"],
                },
            }
        )

        return schemas

    def build_system_prompt(self, agent: Agent) -> str:
        other_agents = [
            a for a in self._agents.values() if a.name != agent.name
        ]

        lines = [f'You are "{agent.name}". {agent.instructions}']

        if other_agents:
            lines.append("")
            lines.append("Available agents:")
            for a in other_agents:
                lines.append(f"- {a.name}: {a.instructions}")

        lines.append("")
        lines.append("Use call_agent to delegate work to other agents.")
        lines.append("Use finish to complete your task and return the result.")

        return "\n".join(lines)

    def _get_backend(self, kind: str) -> ProviderBackend:
        if kind not in self._backends:
            self._backends[kind] = get_backend(kind)
        return self._backends[kind]

    async def call_llm(self, agent: Agent, context: Context, tool_schemas: list[dict[str, Any]]) -> LLMResponse:
        provider = self._providers.get(agent.provider)
        if provider is None:
            raise ProviderError(agent.provider, "Provider not found")
        backend = self._get_backend(provider.kind)
        return await backend.call(context, tool_schemas, agent, provider)

    async def stream_llm(
        self, agent: Agent, context: Context, tool_schemas: list[dict[str, Any]]
    ) -> AsyncIterator[str | LLMResponse]:
        provider = self._providers.get(agent.provider)
        if provider is None:
            raise ProviderError(agent.provider, "Provider not found")
        backend = self._get_backend(provider.kind)
        async for chunk in backend.stream(context, tool_schemas, agent, provider):
            yield chunk
