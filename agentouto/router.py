from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agentouto._constants import BUILTIN_TOOL_NAMES, CALL_AGENT, FINISH
from agentouto.agent import Agent
from agentouto.context import Context
from agentouto.exceptions import ProviderError, RoutingError, ToolError
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend, get_backend
from agentouto.tool import Tool


class Router:
    def __init__(
        self,
        agents: list[Agent],
        tools: list[Tool],
        providers: list[Provider],
        *,
        run_agents: list[Agent] | None = None,
        disabled_tools: set[str] | None = None,
    ) -> None:
        _disabled = frozenset(disabled_tools) if disabled_tools else frozenset()
        if FINISH in _disabled:
            raise ValueError(
                "Cannot disable 'finish' tool — agents need it to return results. "
                "Use a finish override instead if you want custom finish behavior."
            )

        self._agents: dict[str, Agent] = {a.name: a for a in agents}
        self._providers: dict[str, Provider] = {p.name: p for p in providers}
        self._backends: dict[str, ProviderBackend] = {}
        self._run_agents: dict[str, Agent] | None = (
            {a.name: a for a in run_agents} if run_agents is not None else None
        )
        self._disabled_tools: frozenset[str] = _disabled

        self._tools: dict[str, Tool] = {}
        self._builtin_overrides: dict[str, Tool] = {}
        for t in tools:
            if t.name in BUILTIN_TOOL_NAMES:
                self._builtin_overrides[t.name] = t
            else:
                self._tools[t.name] = t

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    @property
    def disabled_tools(self) -> frozenset[str]:
        return self._disabled_tools

    def get_builtin_override(self, name: str) -> Tool | None:
        return self._builtin_overrides.get(name)

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

        for name, schema in self._builtin_tool_schemas().items():
            if name in self._disabled_tools and name not in self._builtin_overrides:
                continue
            if name in self._builtin_overrides:
                schemas.append(self._builtin_overrides[name].to_schema())
            else:
                schemas.append(schema)

        return schemas

    def _builtin_tool_schemas(self) -> dict[str, dict[str, Any]]:
        return {
            CALL_AGENT: {
                "name": CALL_AGENT,
                "description": (
                    "Call another agent. The agent will process your message "
                    "and return a result when done. Use background=True to run "
                    "the agent in background and get a task_id immediately."
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
                        "history": {
                            "type": "array",
                            "description": "Optional conversation history to attach (from previous RunResult.messages)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["forward", "return"],
                                    },
                                    "sender": {"type": "string"},
                                    "receiver": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["type", "sender", "receiver", "content"],
                            },
                        },
                        "background": {
                            "type": "boolean",
                            "description": "If true, spawn the agent in background and return task_id immediately. The agent will run independently.",
                            "default": False,
                        },
                    },
                    "required": ["agent_name", "message"],
                },
            },
            "spawn_background_agent": {
                "name": "spawn_background_agent",
                "description": (
                    "Spawn an agent to run in the background. Returns a task_id "
                    "that can be used to send messages or retrieve results later."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Name of the agent to spawn",
                        },
                        "message": {
                            "type": "string",
                            "description": "Initial message to send to the agent",
                        },
                        "history": {
                            "type": "array",
                            "description": "Optional conversation history to attach",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["forward", "return"],
                                    },
                                    "sender": {"type": "string"},
                                    "receiver": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["type", "sender", "receiver", "content"],
                            },
                        },
                    },
                    "required": ["agent_name", "message"],
                },
            },
            "send_message": {
                "name": "send_message",
                "description": (
                    "Send a message to a running agent (background agent or your caller). "
                    "The agent will receive it as a new user input in its running loop."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Task ID of the target agent",
                        },
                        "message": {
                            "type": "string",
                            "description": "Message content to send",
                        },
                    },
                    "required": ["task_id", "message"],
                },
            },
            "get_messages": {
                "name": "get_messages",
                "description": (
                    "Retrieve messages from a background agent. Returns status, "
                    "result (if completed), and all messages collected so far."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Task ID of the background agent",
                        },
                        "clear": {
                            "type": "boolean",
                            "description": "If true, clear messages after retrieving",
                            "default": False,
                        },
                    },
                    "required": ["task_id"],
                },
            },
            FINISH: {
                "name": FINISH,
                "description": (
                    "Return your final result to the caller. "
                    "This is the ONLY way to deliver your response — "
                    "plain text is not delivered. "
                    "Always use this tool when you are done."
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
            },
        }

    def build_system_prompt(
        self,
        agent: Agent,
        caller: str | None = None,
        extra_instructions: str | None = None,
        caller_loop_id: str | None = None,
    ) -> str:
        visible_agents = (
            self._run_agents if self._run_agents is not None else self._agents
        )
        other_agents = [a for a in visible_agents.values() if a.name != agent.name]

        agent_description = agent.role if agent.role is not None else agent.instructions
        lines = [f'You are "{agent.name}". {agent_description}']

        if agent.role is not None:
            lines.append("")
            lines.append("INSTRUCTIONS:")
            lines.append(agent.instructions)

        if extra_instructions:
            lines.append("")
            lines.append("ADDITIONAL INSTRUCTIONS:")
            lines.append(extra_instructions)

        if caller:
            lines.append("")
            lines.append(f"INVOKED BY: You have been called by '{caller}'.")
            lines.append(
                "Consider their request carefully and fulfill it to the best of your ability."
            )
            if caller_loop_id:
                lines.append(
                    f"Your caller's task_id is '{caller_loop_id}'. "
                    f'Send progress updates: send_message(task_id="{caller_loop_id}", message="your update")'
                )

        if other_agents:
            lines.append("")
            lines.append("Available agents:")
            for a in other_agents:
                agent_role = a.role if a.role is not None else a.instructions
                lines.append(f"- {a.name}: {agent_role}")

        lines.append("")
        lines.append("PARALLEL EXECUTION:")
        lines.append(
            "- You can call MULTIPLE agents AT ONCE by including multiple call_agent tool calls in your single response."
        )
        lines.append(
            "- When you call multiple agents simultaneously, they execute in PARALLEL — this is MUCH FASTER than sequential calls."
        )
        lines.append(
            "- Use parallel execution when: tasks are independent, you need diverse perspectives, or gathering information from multiple sources."
        )
        lines.append(
            "- Example: One response with 3 call_agent calls = 3 agents working simultaneously."
        )

        lines.append("")
        lines.append("COLLABORATION GUIDELINES:")
        lines.append(
            "- Be enthusiastic about collaborating with other agents — teamwork makes the work better."
        )
        lines.append(
            "- Follow your role precisely — stay true to your defined purpose and expertise."
        )
        lines.append(
            "- When asked to collaborate, engage actively and contribute your best work."
        )
        lines.append("- Delegate tasks to other agents when it improves the result.")
        lines.append(
            "- Provide constructive feedback to help other agents improve their work."
        )

        lines.append("")
        lines.append("BACKGROUND EXECUTION:")
        lines.append(
            "- Use call_agent(agent_name, message, background=True) to spawn an agent that runs independently."
        )
        lines.append(
            "- When background=True, the agent runs in a SEPARATE loop and returns a task_id immediately."
        )
        lines.append(
            "- Use send_message(task_id, message) to send messages to a running background agent."
        )
        lines.append(
            "- Use get_messages(task_id) to check status and retrieve messages from a background agent."
        )
        lines.append(
            "- Background agents are ideal for: long-running tasks, concurrent work, agents that need to receive messages mid-execution."
        )
        lines.append(
            "- Unlike parallel call_agent (same loop), background agents have their own isolated loop and context."
        )

        lines.append("")
        lines.append(
            "IMPORTANT: You MUST call the finish tool to return your final result. "
            "Plain text responses are NOT delivered to the caller — "
            'only finish(message="...") will be received. '
            "Never respond with plain text when you are done."
        )
        lines.append("Use call_agent to delegate work to other agents.")

        return "\n".join(lines)

    def _get_backend(self, kind: str) -> ProviderBackend:
        if kind not in self._backends:
            self._backends[kind] = get_backend(kind)
        return self._backends[kind]

    async def call_llm(
        self, agent: Agent, context: Context, tool_schemas: list[dict[str, Any]]
    ) -> LLMResponse:
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
