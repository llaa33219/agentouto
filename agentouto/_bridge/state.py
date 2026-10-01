from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentouto.agent import Agent
    from agentouto.context import Attachment
    from agentouto.loop_manager import RegisteredAgentLoop
    from agentouto.message import Message
    from agentouto.router import Router
    from agentouto.runtime import Runtime
    from agentouto.streaming import StreamEvent


@dataclass
class RunState:
    """Everything one agent loop iteration chain needs.

    coreouto's tool / hook / provider registries are process-global, so every
    dispatch entry point (tool handler, hook, provider shim) resolves the
    current run through the ``_RUN_STATE`` ContextVar instead of instance
    state. asyncio propagates the context into ``asyncio.gather`` children,
    into nested agent loops, and into ``asyncio.to_thread``.
    """

    runtime: Runtime
    agent: Agent | None = None
    forward_message: str = ""
    call_id: str = ""
    parent_call_id: str | None = None
    caller: str | None = None
    caller_name: str | None = None
    loop_id: str = ""
    system_prompt: str = ""
    attachments: list[Attachment] | None = None
    history: list[Message] | None = None
    caller_loop_id: str | None = None
    stream: bool = False
    event_queue: asyncio.Queue[StreamEvent] | None = None
    registered_loop: RegisteredAgentLoop | None = None
    user_out_queue: asyncio.Queue[str] | None = None
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Agent name used for event records ("" when unknown)."""
        if self.caller_name is not None:
            return self.caller_name
        return self.agent.name if self.agent is not None else ""

    @property
    def router(self) -> Router:
        return self.runtime._router


_RUN_STATE: ContextVar[RunState | None] = ContextVar(
    "agentouto_run_state", default=None
)


def get_run_state() -> RunState | None:
    return _RUN_STATE.get()


def require_run_state() -> RunState:
    state = _RUN_STATE.get()
    if state is None:
        raise RuntimeError(
            "agentouto bridge: no active RunState. Coreouto dispatch "
            "(tool/hook/provider) must run inside agentouto's agent loop."
        )
    return state


def bind_run_state(state: RunState) -> Token[RunState | None]:
    return _RUN_STATE.set(state)


def unbind_run_state(token: Token[RunState | None]) -> None:
    _RUN_STATE.reset(token)