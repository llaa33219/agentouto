from __future__ import annotations

from coreouto import Agent as CoreAgent
from coreouto import AgentConfig as CoreAgentConfig
from coreouto import Message as CoreMessage

from agentouto._bridge.convert import history_entry_to_core_message, user_core_message
from agentouto._bridge.hooks import register_bridge_hooks
from agentouto._bridge.provider import NoLLMResponseError, core_provider_name
from agentouto._bridge.state import (
    RunState,
    bind_run_state,
    get_run_state,
    unbind_run_state,
)
from agentouto._bridge.tools import (
    background_report,
    execute_dispatch,
    execute_tool_logic,
    register_builtin_dispatch_tools,
    register_run_tools,
)

__all__ = [
    "NoLLMResponseError",
    "RunState",
    "background_report",
    "bind_run_state",
    "execute_dispatch",
    "execute_tool_logic",
    "get_run_state",
    "register_bridge_hooks",
    "register_builtin_dispatch_tools",
    "register_run_tools",
    "run_agent_loop",
    "unbind_run_state",
]

register_builtin_dispatch_tools()
register_bridge_hooks()


def _core_history(state: RunState) -> list[CoreMessage]:
    history = [history_entry_to_core_message(m) for m in state.history or []]
    history.append(user_core_message(state.forward_message, state.attachments))
    return history


async def run_agent_loop(state: RunState) -> str:
    """Run one agent turn-loop on ``coreouto.Agent.call()``.

    The returned string is the agent's final answer: plain assistant text
    with no tool calls, an unrecoverable provider stop, or a normalized
    ``finish(message=X)`` response.
    """
    agent = state.agent
    assert agent is not None

    state.tool_schemas = state.router.build_tool_schemas(agent.name)
    register_run_tools(state.tool_schemas, state.router)

    config = CoreAgentConfig(
        name=agent.name,
        model=agent.model,
        provider=core_provider_name(state.router, agent),
        system_prompt=state.system_prompt,
        tools=[str(schema["name"]) for schema in state.tool_schemas],
        # agentouto has no iteration cap.
        max_iterations=None,
        parallel_tool_calls=True,
    )

    token = bind_run_state(state)
    try:
        response = await CoreAgent(config).call(history=_core_history(state))
        return response.content
    except NoLLMResponseError:
        _emit_no_response(state)
        return ""
    finally:
        unbind_run_state(token)


def _emit_no_response(state: RunState) -> None:
    if state.event_queue is None:
        return
    from agentouto.streaming import StreamEvent

    state.event_queue.put_nowait(
        StreamEvent(
            type="error",
            agent_name=state.name,
            call_id=state.call_id,
            parent_call_id=state.parent_call_id,
            data={"error": "No response from LLM"},
        )
    )