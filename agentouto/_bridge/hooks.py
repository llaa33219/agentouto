from __future__ import annotations

import asyncio
import logging
from typing import Any

from coreouto import (
    AFTER_LLM_CALL,
    AFTER_TOOL_CALL,
    BEFORE_LLM_CALL,
    BEFORE_TOOL_CALL,
    ON_FINISH,
    ON_STREAM_TEXT,
    ON_STREAM_THINKING,
    Message as CoreMessage,
    ToolResult as CoreToolResult,
    register_hook,
)

from agentouto._bridge.convert import (
    blocks_to_attachments,
    build_context,
    context_message_to_core_message,
    core_message_to_context_message,
)
from agentouto._bridge.state import RunState, get_run_state
from agentouto._bridge.tools import run_tool_names, truncate, unknown_tool_error
from agentouto.context import Context
from agentouto.summarizer import (
    SummarizeInfo,
    _SUMMARIZE_THRESHOLD,
    _estimate_message_tokens,
    build_self_summarize_context,
    estimate_context_tokens,
    find_summarization_boundary,
    parse_summary_response,
)

logger = logging.getLogger("agentouto")

_NEXT_STEPS_TEMPLATE = (
    "[SYSTEM] Summary complete. Based on the summary, the following next "
    "steps have been identified:\n{next_steps}\n\nProceed with these next "
    "steps when you continue."
)


def _emit(state: RunState, event: Any) -> None:
    if state.event_queue is not None:
        state.event_queue.put_nowait(event)


def _stream_event(state: RunState, event_type: str, data: dict[str, Any]) -> None:
    from agentouto.streaming import StreamEvent

    _emit(
        state,
        StreamEvent(
            type=event_type,  # type: ignore[arg-type]
            agent_name=state.name,
            call_id=state.call_id,
            parent_call_id=state.parent_call_id,
            data=data,
        ),
    )


# --- Summarization ---


def _estimate_current_tokens(runtime: Any, context: Context) -> int:
    if runtime._last_input_tokens is not None:
        current_count = len(context.messages)
        new_messages = current_count - runtime._last_message_count
        if new_messages > 0:
            new_msg_tokens = sum(
                _estimate_message_tokens(msg)
                for msg in context.messages[runtime._last_message_count:]
            )
            return runtime._last_input_tokens + new_msg_tokens
        return runtime._last_input_tokens
    return estimate_context_tokens(context)


async def maybe_summarize(state: RunState, messages: list[CoreMessage]) -> None:
    """Self-summarize coreouto's message list in place when the window fills.

    Runs as a ``BEFORE_LLM_CALL`` hook. All failures are logged and swallowed
    (matching the previous runtime behavior).
    """
    from agentouto.model_metadata import get_context_window

    agent = state.agent
    runtime = state.runtime
    if agent is None or len(messages) == 0:
        return

    context_window = agent.context_window
    if context_window is None:
        try:
            context_window = await get_context_window(agent.model)
        except Exception:
            return

    view = [core_message_to_context_message(m) for m in messages[1:]]
    context = build_context(messages[0].content if isinstance(messages[0].content, str) else "", view)

    current_tokens = _estimate_current_tokens(runtime, context)
    if current_tokens <= int(context_window * _SUMMARIZE_THRESHOLD):
        return

    tokens_before = current_tokens
    split = find_summarization_boundary(view, context_window)
    if split is None:
        return

    messages_to_summarize = view[:split]
    summarize_context = build_self_summarize_context(
        messages_to_summarize, context.system_prompt
    )

    try:
        response = await state.router.call_llm(agent, summarize_context, [])
        runtime._accumulate_usage(response)
        if not response.content:
            return
        parsed = parse_summary_response(response.content)
        summary = parsed.summary
        next_steps = parsed.next_steps

        if runtime._on_summarize is not None:
            try:
                tokens_after_llm = _estimate_current_tokens(runtime, context)
                info = SummarizeInfo(
                    agent_name=agent.name,
                    messages_to_summarize=list(messages_to_summarize),
                    summary=summary,
                    next_steps=next_steps,
                    tokens_before=tokens_before,
                    tokens_after=tokens_after_llm,
                )
                overridden = runtime._on_summarize(info)
                if overridden is not None:
                    summary = overridden
            except Exception as exc:
                logger.warning(
                    "[%s] on_summarize callback raised an error: %s",
                    agent.name,
                    exc,
                )

        context.replace_with_summary(summary, keep_from=split)
        runtime._last_message_count = len(context.messages)
        if next_steps:
            context.add_user(_NEXT_STEPS_TEMPLATE.format(next_steps=next_steps))
        messages[:] = [messages[0]] + [
            context_message_to_core_message(m) for m in context.messages
        ]
        tokens_after = _estimate_current_tokens(runtime, context)
        logger.info(
            "[%s] Self-summarized %d messages (%d → %d tokens)",
            agent.name,
            split,
            tokens_before,
            tokens_after,
        )
    except Exception as exc:
        logger.warning("[%s] Self-summarization failed: %s", agent.name, exc)


# --- Message injection ---


def _drain_injected_messages(state: RunState, messages: list[CoreMessage]) -> None:
    from agentouto._bridge.convert import user_core_message

    registered_loop = state.registered_loop
    if registered_loop is not None:
        try:
            injected = registered_loop.message_queue._queue.get_nowait()
        except asyncio.QueueEmpty:
            injected = None
        if injected is not None:
            messages.append(
                user_core_message(injected.content, injected.attachments)
            )

    user_out_queue = state.user_out_queue
    if user_out_queue is None:
        return
    while True:
        try:
            messages.append(user_core_message(user_out_queue.get_nowait()))
        except asyncio.QueueEmpty:
            return


# --- Hooks ---


async def _on_before_llm_call(
    messages: list[CoreMessage], model: str, tools: list[Any], **kwargs: Any
) -> None:
    state = get_run_state()
    if state is None:
        return
    _drain_injected_messages(state, messages)
    await maybe_summarize(state, messages)
    state.runtime._record(
        "llm_call",
        state.name,
        state.call_id,
        state.parent_call_id,
        {"model": model},
    )


async def _on_after_llm_call(
    response: Any, messages: list[CoreMessage], **kwargs: Any
) -> None:
    state = get_run_state()
    if state is None:
        return
    content = response.content or ""
    state.runtime._record(
        "llm_response",
        state.name,
        state.call_id,
        state.parent_call_id,
        {
            "has_tool_calls": bool(response.tool_calls),
            "content_length": len(content),
        },
    )
    if response.usage is not None:
        runtime = state.runtime
        runtime._token_usage += _core_usage_to_usage(response.usage)
        runtime._last_input_tokens = response.usage.prompt_tokens
    # ``messages`` includes the system prompt, which is not part of Context.
    state.runtime._last_message_count = len(messages) - 1


def _core_usage_to_usage(usage: Any) -> Any:
    from agentouto.providers import Usage

    return Usage(input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens)


async def _on_before_tool_call(name: str, arguments: dict[str, Any], **kwargs: Any) -> None:
    state = get_run_state()
    if state is None or state.event_queue is None:
        return
    _stream_event(state, "tool_call", {"tool_name": name, "arguments": arguments})


async def _on_after_tool_call(name: str, result: CoreToolResult, **kwargs: Any) -> None:
    state = get_run_state()
    if state is None:
        return

    content = result.content
    attachments = None
    if content is None and result.blocks is not None:
        content, attachments = blocks_to_attachments(result.blocks)
    text = content or ""

    if name not in run_tool_names(state.router):
        # coreouto reports "tool not found: X" for names outside the registry;
        # rewrite it into agentouto's exact phrasing.
        text = unknown_tool_error(state.router, name)
        result.content = text
        result.blocks = None

    if state.event_queue is None:
        return
    data: dict[str, Any] = {"tool_name": name, "result": text}
    if attachments:
        data["attachments"] = [
            {
                "mime_type": att.mime_type,
                "data": att.data,
                "url": att.url,
                "name": att.name,
            }
            for att in attachments
        ]
    _stream_event(state, "tool_result", data)


async def _on_finish(
    content: str, messages: list[CoreMessage], iterations: int, **kwargs: Any
) -> None:
    state = get_run_state()
    if state is None:
        return
    _stream_event(state, "finish", {"output": content})
    state.runtime._record(
        "finish",
        state.name,
        state.call_id,
        state.parent_call_id,
        {"result": truncate(content)},
    )


async def _on_stream_text(text: str, **kwargs: Any) -> None:
    state = get_run_state()
    if state is None:
        return
    _stream_event(state, "token", {"text": text})


async def _on_stream_thinking(text: str, **kwargs: Any) -> None:
    # agentouto exposes no thinking StreamEvent — discard.
    return


_hooks_registered = False


def register_bridge_hooks() -> None:
    """Register every coreouto hook once per process.

    coreouto's hook registry is global; per-run register/clear would leak
    across concurrent runs. Each hook dispatches through the ``RunState``
    ContextVar and no-ops when agentouto is not the caller.
    """
    global _hooks_registered
    if _hooks_registered:
        return
    register_hook(BEFORE_LLM_CALL, _on_before_llm_call)
    register_hook(AFTER_LLM_CALL, _on_after_llm_call)
    register_hook(BEFORE_TOOL_CALL, _on_before_tool_call)
    register_hook(AFTER_TOOL_CALL, _on_after_tool_call)
    register_hook(ON_FINISH, _on_finish)
    register_hook(ON_STREAM_TEXT, _on_stream_text)
    register_hook(ON_STREAM_THINKING, _on_stream_thinking)
    _hooks_registered = True