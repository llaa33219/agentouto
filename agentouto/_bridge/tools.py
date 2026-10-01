from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from coreouto import Tool as CoreTool
from coreouto import tools as _core_tools

from agentouto._bridge.convert import tool_result_to_core
from agentouto._bridge.state import RunState, require_run_state
from agentouto._constants import BUILTIN_TOOL_NAMES, CALL_AGENT
from agentouto.agent import Agent
from agentouto.exceptions import RoutingError, ToolError
from agentouto.message import Message
from agentouto.tool import Tool, ToolResult

if TYPE_CHECKING:
    from agentouto.router import Router
    from agentouto.runtime import Runtime

logger = logging.getLogger("agentouto")

# coreouto exposes no "register a pre-built Tool" API (only the decorator
# form, which derives a JSON schema from the handler signature and rejects
# `Any`-typed parameters). agentouto's dispatch handlers take arbitrary tool
# arguments and never use ``Tool.parameters`` — the backend schema list comes
# from ``Router.build_tool_schemas`` — so the pinned 0.11.x registry dict is
# written directly.
_TOOL_REGISTRY: dict[str, CoreTool] = _core_tools._TOOL_REGISTRY  # type: ignore[attr-defined]


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# --- Target resolution ---


def resolve_agent_target(router: Router, agent_name: str) -> Agent:
    if agent_name in router.tool_names:
        raise RoutingError(
            f"'{agent_name}' is a tool, not an agent. "
            f"Call it directly as {agent_name}(...) instead of using call_agent."
        )
    if agent_name not in router.agent_names:
        available = ", ".join(router.agent_names) or "(none)"
        raise RoutingError(
            f"Unknown agent: '{agent_name}'. Available agents: {available}"
        )
    return router.get_agent(agent_name)


def resolve_tool_target(router: Router, tool_name: str) -> Tool:
    if tool_name in router.agent_names:
        raise ToolError(
            tool_name,
            f"'{tool_name}' is an agent, not a tool. "
            f'Use call_agent(agent_name="{tool_name}", message="...") to call it.',
        )
    if tool_name not in router.tool_names:
        available = ", ".join(router.tool_names) or "(none)"
        raise ToolError(
            tool_name, f"Unknown tool: '{tool_name}'. Available tools: {available}"
        )
    return router.get_tool(tool_name)


def unknown_tool_error(router: Router, tool_name: str) -> str:
    available = ", ".join(router.tool_names) or "(none)"
    return f"Error: Unknown tool: '{tool_name}'. Available tools: {available}"


# --- Background helpers ---


def history_from_argument(history_arg: Any) -> list[Message] | None:
    """Rebuild ``Message`` history from a raw tool argument (regenerated ids)."""
    if not (isinstance(history_arg, list) and history_arg):
        return None
    history: list[Message] = []
    for item in history_arg:
        if isinstance(item, dict):
            history.append(
                Message(
                    type=item.get("type", "forward"),
                    sender=item.get("sender", ""),
                    receiver=item.get("receiver", ""),
                    content=item.get("content", ""),
                    call_id=uuid.uuid4().hex,
                )
            )
    return history


def background_report(bg_loop: Any, task_id: str, messages: list[Message]) -> str:
    """The ``get_messages`` / ``get_agent_status`` report layout."""
    result_parts = [
        f"Task ID: {task_id}",
        f"Agent: {bg_loop.agent.name}",
        f"Status: {bg_loop.get_status()}",
    ]
    if bg_loop.result is not None:
        result_parts.append(f"Result: {bg_loop.result}")
    if bg_loop.error is not None:
        result_parts.append(f"Error: {bg_loop.error}")
    if messages:
        result_parts.append(f"Messages ({len(messages)}):")
        for msg in messages:
            result_parts.append(
                f"  [{msg.type}] {msg.sender} -> {msg.receiver}: {msg.content[:100]}"
            )
    return "\n".join(result_parts)


def _sub_instructions(runtime: Runtime) -> str | None:
    if runtime._extra_instructions_scope == "all":
        return runtime._extra_instructions
    return None


def _lookup_loop(task_id: str) -> Any:
    from agentouto.loop_manager import AgentLoopRegistry

    return AgentLoopRegistry.get_instance().get_loop(task_id)


# --- Builtin behaviors ---


def _emit_sub_event(
    state: RunState, event_type: str, data: dict[str, Any], call_id: str
) -> None:
    if state.event_queue is None:
        return
    from agentouto.streaming import StreamEvent

    state.event_queue.put_nowait(
        StreamEvent(
            type=event_type,  # type: ignore[arg-type]
            agent_name=state.agent.name if state.agent is not None else "",
            call_id=call_id,
            parent_call_id=state.call_id,
            data=data,
        )
    )


async def _call_agent(state: RunState, arguments: dict[str, Any]) -> str:
    runtime = state.runtime
    agent_name = arguments.get("agent_name", "")
    message = arguments.get("message", "")
    background = arguments.get("background", False)
    history = history_from_argument(arguments.get("history"))

    target = resolve_agent_target(state.router, agent_name)

    sub_call_id = uuid.uuid4().hex
    runtime._messages.append(
        Message(
            type="forward",
            sender=state.name,
            receiver=agent_name,
            content=message,
            call_id=sub_call_id,
        )
    )
    runtime._record(
        "agent_call",
        agent_name,
        sub_call_id,
        state.call_id,
        {
            "from": state.name,
            "message": truncate(message),
            "background": background,
        },
    )
    _emit_sub_event(
        state,
        "agent_call",
        {"from": state.name, "message": truncate(message)},
        sub_call_id,
    )

    if background:
        if not runtime._allow_background_agents:
            return (
                "Error: Background agent spawning is disabled. "
                "Use allow_background_agents=True to enable it."
            )
        task_id = await runtime._spawn_background_agent(
            message,
            [target],
            sub_call_id,
            state.call_id,
            state.name,
            history=history,
            extra_instructions=_sub_instructions(runtime),
        )
        return f"Background agent started. Task ID: {task_id}"

    result = await runtime._run_agent_loop(
        target,
        message,
        sub_call_id,
        state.call_id,
        state.name,
        history=history,
        extra_instructions=_sub_instructions(runtime),
        caller_loop_id=state.loop_id,
    )

    runtime._messages.append(
        Message(
            type="return",
            sender=agent_name,
            receiver=state.name,
            content=result,
            call_id=sub_call_id,
        )
    )
    runtime._record(
        "agent_return",
        agent_name,
        sub_call_id,
        state.call_id,
        {"result": truncate(result)},
    )
    _emit_sub_event(
        state, "agent_return", {"result": truncate(result)}, sub_call_id
    )
    return f"[{agent_name}]{result}[/{agent_name}]"


async def _spawn_background_agent(state: RunState, arguments: dict[str, Any]) -> str:
    runtime = state.runtime
    if not runtime._allow_background_agents:
        return (
            "Error: Background agent spawning is disabled. "
            "Use allow_background_agents=True to enable it."
        )
    agent_name = arguments.get("agent_name", "")
    message = arguments.get("message", "")
    history = history_from_argument(arguments.get("history"))
    target = resolve_agent_target(state.router, agent_name)
    task_id = await runtime._spawn_background_agent(
        message,
        [target],
        uuid.uuid4().hex,
        state.call_id,
        state.name,
        history=history,
        extra_instructions=_sub_instructions(runtime),
    )
    return f"Background agent started. Task ID: {task_id}"


async def _send_message(state: RunState, arguments: dict[str, Any]) -> str:
    task_id = arguments.get("task_id", "")
    message = arguments.get("message", "")

    bg_loop = _lookup_loop(task_id)
    if bg_loop is None:
        return f"Error: No background agent found with task_id: {task_id}"

    msg = Message(
        type="forward",
        sender=state.name,
        receiver=bg_loop.agent.name,
        content=message,
        call_id=uuid.uuid4().hex,
    )
    state.runtime._messages.append(msg)
    await bg_loop.inject_message(msg)
    return f"Message sent to {bg_loop.agent.name} (task_id: {task_id})"


async def _get_messages(state: RunState, arguments: dict[str, Any]) -> str:
    task_id = arguments.get("task_id", "")
    bg_loop = _lookup_loop(task_id)
    if bg_loop is None:
        return f"Error: No background agent found with task_id: {task_id}"
    return background_report(
        bg_loop, task_id, bg_loop.get_messages(clear=arguments.get("clear", False))
    )


# --- Dispatch ---


async def execute_tool_logic(
    state: RunState, name: str, arguments: dict[str, Any]
) -> str | ToolResult:
    """Resolve and execute one tool call for the current run.

    Raises ``ToolError`` / ``RoutingError`` on resolution failures and tool
    exceptions; the caller decides how to surface them.
    """
    router = state.router
    runtime = state.runtime

    override = router.get_builtin_override(name)
    if override is not None:
        runtime._record(
            "tool_exec",
            state.name,
            state.call_id,
            None,
            {"tool_name": name, "arguments": arguments, "override": True},
        )
        try:
            return await override.execute(**arguments)
        except Exception as exc:
            raise ToolError(name, str(exc)) from exc

    if name in router.disabled_tools and name in BUILTIN_TOOL_NAMES:
        return f"Error: Tool '{name}' is disabled in this run."

    if name == CALL_AGENT:
        return await _call_agent(state, arguments)
    if name == "spawn_background_agent":
        return await _spawn_background_agent(state, arguments)
    if name == "send_message":
        return await _send_message(state, arguments)
    if name == "get_messages":
        return await _get_messages(state, arguments)

    runtime._record(
        "tool_exec",
        state.name,
        state.call_id,
        None,
        {"tool_name": name, "arguments": arguments},
    )
    tool = resolve_tool_target(router, name)
    try:
        return await tool.execute(**arguments)
    except Exception as exc:
        raise ToolError(name, str(exc)) from exc


async def execute_dispatch(name: str, arguments: dict[str, Any]) -> Any:
    """coreouto tool-handler entry point: never raises, always yields text.

    Returning the error string keeps coreouto's ``"{type}: {exc}"`` swallowing
    out of the picture, so agentouto's exact error strings reach the model.
    """
    state = require_run_state()
    try:
        raw = await execute_tool_logic(state, name, arguments)
    except Exception as exc:
        logger.debug("[%s] tool %s failed: %s", state.name, name, exc)
        return tool_result_to_core("", f"Error: {exc}", None)
    if isinstance(raw, ToolResult):
        return tool_result_to_core("", raw.content, raw.attachments)
    return tool_result_to_core("", str(raw), None)


_DESCRIPTIONS: dict[str, str] = {
    CALL_AGENT: "Dispatch shim — the real schema comes from Router.build_tool_schemas.",
    "spawn_background_agent": "Dispatch shim — the real schema comes from Router.",
    "send_message": "Dispatch shim — the real schema comes from Router.",
    "get_messages": "Dispatch shim — the real schema comes from Router.",
    "finish": "Dispatch shim — finish is intercepted before tool execution.",
}


def _make_handler(name: str) -> Any:
    if name == "finish":

        async def finish_handler(**arguments: Any) -> Any:
            raise RuntimeError(
                "finish intercepted by the agentouto provider shim; it must "
                "never execute as a coreouto tool"
            )

        handler: Any = finish_handler
    else:

        async def dispatch_handler(**arguments: Any) -> Any:
            return await execute_dispatch(name, arguments)

        handler = dispatch_handler

    handler.__name__ = name
    handler.__doc__ = _DESCRIPTIONS.get(name, "Dispatch shim.")
    return handler


_builtins_registered = False


def register_builtin_dispatch_tools() -> None:
    """Register one coreouto ``Tool`` per agentouto builtin, once per process."""
    global _builtins_registered
    if _builtins_registered:
        return
    for name in BUILTIN_TOOL_NAMES:
        _TOOL_REGISTRY[name] = CoreTool(
            name=name,
            description=_DESCRIPTIONS[name],
            parameters={},
            handler=_make_handler(name),
            parallelizable=True,
        )
    _builtins_registered = True


def register_run_tools(schemas: list[dict[str, Any]], router: Router) -> None:
    """Register a dispatch ``Tool`` for every name the current run may resolve.

    coreouto resolves ``AgentConfig.tools`` through the global registry, so
    every declared name must exist before ``Agent.call``. Agent names are
    registered too: calling an agent as a tool is a routable mistake that must
    produce agentouto's own message rather than coreouto's not-found string.

    The schema stored here is never used — the backend schema list comes from
    the run — but the name lookup is load-bearing.
    """
    names = [str(schema["name"]) for schema in schemas] + list(router.agent_names)
    for name in names:
        if name in _TOOL_REGISTRY:
            continue
        _TOOL_REGISTRY[name] = CoreTool(
            name=name,
            description=_DESCRIPTIONS.get(name, "Dispatch shim."),
            parameters={},
            handler=_make_handler(name),
            parallelizable=True,
        )


def run_tool_names(router: Router) -> frozenset[str]:
    """Every tool name the current run's registry may legitimately resolve."""
    return (
        frozenset(BUILTIN_TOOL_NAMES)
        | frozenset(router.tool_names)
        | frozenset(router.agent_names)
    )