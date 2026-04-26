from __future__ import annotations

import asyncio
import logging
import uuid
import warnings
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from agentouto._constants import CALL_AGENT, FINISH
from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ContextMessage, ToolCall
from agentouto.event_log import AgentEvent, EventLog
from agentouto.exceptions import RoutingError, ToolError
from agentouto.loop_manager import AgentLoopRegistry, BackgroundAgentLoop
from agentouto.message import Message
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, Usage
from agentouto.router import Router
from agentouto.summarizer import (
    SummarizeInfo,
    _SUMMARIZE_THRESHOLD,
    _estimate_message_tokens,
    build_self_summarize_context,
    estimate_context_tokens,
    find_summarization_boundary,
    needs_summarization,
    parse_summary_response,
)
from agentouto.tool import Tool, ToolResult
from agentouto.tracing import Trace
from agentouto.model_metadata import get_context_window

if TYPE_CHECKING:
    from agentouto.streaming import StreamEvent

logger = logging.getLogger("agentouto")

_FINISH_NUDGE = (
    "[SYSTEM] Your plain text response was NOT delivered to the caller. "
    "You MUST use the finish tool to return results. "
    'Call finish(message="your result") now. This is a SYSTEM message, not from a user.'
)


@dataclass
class RunResult:
    output: str
    messages: list[Message] = field(default_factory=list)
    trace: Trace | None = None
    event_log: EventLog | None = None
    token_usage: Usage = field(default_factory=Usage)

    def format_trace(self) -> str:
        if self.trace is None:
            return "(no trace — run with debug=True)"
        return self.trace.print_tree()


class Runtime:
    def __init__(
        self,
        router: Router,
        debug: bool = False,
        extra_instructions: str | None = None,
        extra_instructions_scope: Literal["entry", "all"] = "entry",
        on_message: Callable[[Message, Callable[[str], None]], None] | None = None,
        allow_background_agents: bool = False,
        on_summarize: Callable[[SummarizeInfo], str | None] | None = None,
    ) -> None:
        self._router = router
        self._debug = debug
        self._event_log: EventLog | None = EventLog() if debug else None
        self._messages: list[Message] = []
        self._extra_instructions = extra_instructions
        self._extra_instructions_scope = extra_instructions_scope
        self._on_message = on_message
        self._allow_background_agents = allow_background_agents
        self._on_summarize = on_summarize
        self._token_usage = Usage()
        self._last_input_tokens: int | None = None
        self._last_message_count: int = 0

    def _accumulate_usage(self, response: LLMResponse) -> None:
        if response.usage is not None:
            self._token_usage += response.usage
            self._last_input_tokens = response.usage.input_tokens

    async def execute(
        self,
        forward_message: str,
        *,
        attachments: list[Attachment] | None = None,
        history: list[Message] | None = None,
        starting_agents: list[Agent] | None = None,
    ) -> RunResult:
        if starting_agents is None or len(starting_agents) == 0:
            raise ValueError("starting_agents must be provided")

        if len(starting_agents) == 1:
            return await self._execute_single(
                starting_agents[0], forward_message, attachments, history
            )

        results: dict[str, str] = {}

        async def execute_and_collect(
            ag: Agent,
        ) -> None:
            result = await self._execute_single(
                ag, forward_message, attachments, history
            )
            results[ag.name] = result.output

        await asyncio.gather(
            *[execute_and_collect(sa) for sa in starting_agents],
        )
        trace = Trace(self._event_log) if self._event_log else None
        if self._debug and self._event_log is not None:
            logger.debug("Event log:\n%s", self._event_log.format())
            if trace:
                logger.debug("Trace:\n%s", trace.print_tree())
        output_parts = [
            f"[{name}]{content}[/{name}]" for name, content in results.items()
        ]
        return RunResult(
            output="\n\n".join(output_parts),
            messages=self._messages,
            trace=trace,
            event_log=self._event_log,
            token_usage=self._token_usage,
        )

    async def _execute_single(
        self,
        agent: Agent,
        forward_message: str,
        attachments: list[Attachment] | None,
        history: list[Message] | None,
    ) -> RunResult:
        from agentouto.loop_manager import RegisteredAgentLoop

        call_id = uuid.uuid4().hex

        user_loop_id: str | None = None
        user_out_queue: asyncio.Queue[str] | None = None
        if self._on_message is not None:
            user_loop_id = f"user_{call_id}"
            user_out_queue = asyncio.Queue()
            user_agent = Agent(name="user", instructions="", model="", provider="")

            on_message = self._on_message
            out_queue = user_out_queue

            def send(message: str) -> None:
                out_queue.put_nowait(message)

            def _wrapped_on_message(msg: Message) -> None:
                on_message(msg, send)

            user_loop = RegisteredAgentLoop(
                agent=user_agent,
                task_id=user_loop_id,
                on_message=_wrapped_on_message,
            )
            registry = AgentLoopRegistry.get_instance()
            registry.register(user_loop_id, user_loop)

        self._messages.append(
            Message(
                type="forward",
                sender="user",
                receiver=agent.name,
                content=forward_message,
                call_id=call_id,
                attachments=attachments,
            )
        )
        self._record(
            "agent_call",
            agent.name,
            call_id,
            None,
            {
                "message": _truncate(forward_message),
            },
        )

        try:
            output = await self._run_agent_loop(
                agent,
                forward_message,
                call_id,
                None,
                "user",
                attachments=attachments,
                history=history,
                extra_instructions=self._extra_instructions,
                caller_loop_id=user_loop_id,
                user_out_queue=user_out_queue,
            )
        finally:
            if user_loop_id is not None:
                AgentLoopRegistry.get_instance().unregister(user_loop_id)

        self._messages.append(
            Message(
                type="return",
                sender=agent.name,
                receiver="user",
                content=output,
                call_id=call_id,
            )
        )
        self._record(
            "agent_return",
            agent.name,
            call_id,
            None,
            {
                "result": _truncate(output),
            },
        )

        trace = Trace(self._event_log) if self._event_log else None
        if self._debug and self._event_log is not None:
            logger.debug("Event log:\n%s", self._event_log.format())
            if trace:
                logger.debug("Trace:\n%s", trace.print_tree())

        return RunResult(
            output=output,
            messages=self._messages,
            trace=trace,
            event_log=self._event_log,
            token_usage=self._token_usage,
        )

    async def _run_agent_loop(
        self,
        agent: Agent,
        forward_message: str,
        call_id: str,
        parent_call_id: str | None,
        caller: str | None = None,
        *,
        attachments: list[Attachment] | None = None,
        history: list[Message] | None = None,
        loop_id: str | None = None,
        extra_instructions: str | None = None,
        caller_loop_id: str | None = None,
        user_out_queue: asyncio.Queue[str] | None = None,
    ) -> str:
        from agentouto.loop_manager import RegisteredAgentLoop

        if loop_id is None:
            loop_id = call_id
        registry = AgentLoopRegistry.get_instance()
        registered_loop = RegisteredAgentLoop(
            agent=agent,
            task_id=loop_id,
            caller_loop_id=caller_loop_id,
        )
        registry.register(loop_id, registered_loop)

        system_prompt = self._router.build_system_prompt(
            agent,
            caller=caller,
            extra_instructions=extra_instructions,
            caller_loop_id=caller_loop_id,
        )
        context = Context(system_prompt)

        # Add history messages to context if provided
        if history:
            for msg in history:
                self._add_message_to_context(context, msg)

        context.add_user(forward_message, attachments=attachments)
        tool_schemas = self._router.build_tool_schemas(agent.name)

        try:
            while True:
                try:
                    injected_msg = registered_loop.message_queue._queue.get_nowait()
                    if injected_msg:
                        context.add_user(
                            injected_msg.content,
                            attachments=injected_msg.attachments,
                        )
                except asyncio.QueueEmpty:
                    pass

                if user_out_queue is not None:
                    try:
                        while True:
                            user_msg = user_out_queue.get_nowait()
                            context.add_user(user_msg)
                    except asyncio.QueueEmpty:
                        pass

                await self._maybe_summarize(context, agent)

                self._record(
                    "llm_call",
                    agent.name,
                    call_id,
                    parent_call_id,
                    {
                        "model": agent.model,
                    },
                )

                response = await self._router.call_llm(agent, context, tool_schemas)
                self._accumulate_usage(response)
                self._last_message_count = len(context.messages)

                self._record(
                    "llm_response",
                    agent.name,
                    call_id,
                    parent_call_id,
                    {
                        "has_tool_calls": bool(response.tool_calls),
                        "content_length": len(response.content)
                        if response.content
                        else 0,
                    },
                )

                if not response.tool_calls:
                    logger.warning(
                        "[%s] Agent responded with text instead of finish(), nudging",
                        agent.name,
                    )
                    context.add_assistant_text(response.content or "")
                    context.add_user(_FINISH_NUDGE)
                    continue

                finish_call = _find_finish(response.tool_calls)
                if finish_call is not None:
                    finish_override = self._router.get_builtin_override(FINISH)
                    if finish_override is not None:
                        try:
                            raw = await finish_override.execute(**finish_call.arguments)
                            result = (
                                raw.content if isinstance(raw, ToolResult) else str(raw)
                            )
                        except Exception as exc:
                            result = f"Error in finish override: {exc}"
                    else:
                        result = finish_call.arguments.get("message", "")
                    self._record(
                        "finish",
                        agent.name,
                        call_id,
                        parent_call_id,
                        {
                            "result": _truncate(result),
                        },
                    )
                    return result

                context.add_assistant_tool_calls(response.tool_calls, response.content)

                tasks = [
                    self._execute_tool_call(
                        tc, agent.name, call_id, current_loop_id=loop_id
                    )
                    for tc in response.tool_calls
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for tc, tool_result in zip(response.tool_calls, results):
                    if isinstance(tool_result, BaseException):
                        context.add_tool_result(tc.id, tc.name, f"Error: {tool_result}")
                    elif isinstance(tool_result, ToolResult):
                        context.add_tool_result(
                            tc.id,
                            tc.name,
                            tool_result.content,
                            attachments=tool_result.attachments,
                        )
                    else:
                        context.add_tool_result(tc.id, tc.name, str(tool_result))
        finally:
            registry.unregister(loop_id)

    def _resolve_agent_target(self, agent_name: str) -> Agent:
        if agent_name in self._router.tool_names:
            raise RoutingError(
                f"'{agent_name}' is a tool, not an agent. "
                f"Call it directly as {agent_name}(...) instead of using call_agent."
            )
        if agent_name not in self._router.agent_names:
            available = ", ".join(self._router.agent_names) or "(none)"
            raise RoutingError(
                f"Unknown agent: '{agent_name}'. Available agents: {available}"
            )
        return self._router.get_agent(agent_name)

    def _resolve_tool_target(self, tool_name: str) -> Tool:
        if tool_name in self._router.agent_names:
            raise ToolError(
                tool_name,
                f"'{tool_name}' is an agent, not a tool. "
                f'Use call_agent(agent_name="{tool_name}", message="...") to call it.',
            )
        if tool_name not in self._router.tool_names:
            available = ", ".join(self._router.tool_names) or "(none)"
            raise ToolError(
                tool_name, f"Unknown tool: '{tool_name}'. Available tools: {available}"
            )
        return self._router.get_tool(tool_name)

    async def _execute_tool_call(
        self,
        tc: ToolCall,
        caller_name: str,
        caller_call_id: str,
        *,
        current_loop_id: str | None = None,
    ) -> str | ToolResult:
        from agentouto._constants import BUILTIN_TOOL_NAMES

        override = self._router.get_builtin_override(tc.name)
        if override is not None:
            self._record(
                "tool_exec",
                caller_name,
                caller_call_id,
                None,
                {"tool_name": tc.name, "arguments": tc.arguments, "override": True},
            )
            try:
                return await override.execute(**tc.arguments)
            except Exception as exc:
                raise ToolError(tc.name, str(exc)) from exc

        if tc.name in self._router.disabled_tools and tc.name in BUILTIN_TOOL_NAMES:
            return f"Error: Tool '{tc.name}' is disabled in this run."

        if tc.name == CALL_AGENT:
            agent_name = tc.arguments.get("agent_name", "")
            message = tc.arguments.get("message", "")
            history_arg = tc.arguments.get("history")
            background = tc.arguments.get("background", False)

            history: list[Message] | None = None

            if history_arg and isinstance(history_arg, list):
                history = []
                for h in history_arg:
                    if isinstance(h, dict):
                        history.append(
                            Message(
                                type=h.get("type", "forward"),
                                sender=h.get("sender", ""),
                                receiver=h.get("receiver", ""),
                                content=h.get("content", ""),
                                call_id=uuid.uuid4().hex,
                            )
                        )

            target = self._resolve_agent_target(agent_name)

            sub_call_id = uuid.uuid4().hex
            self._messages.append(
                Message(
                    type="forward",
                    sender=caller_name,
                    receiver=agent_name,
                    content=message,
                    call_id=sub_call_id,
                )
            )
            self._record(
                "agent_call",
                agent_name,
                sub_call_id,
                caller_call_id,
                {
                    "from": caller_name,
                    "message": _truncate(message),
                    "background": background,
                },
            )

            if background:
                if not self._allow_background_agents:
                    return "Error: Background agent spawning is disabled. Use allow_background_agents=True to enable it."
                task_id = await self._spawn_background_agent(
                    message,
                    [target],
                    sub_call_id,
                    caller_call_id,
                    caller_name,
                    history=history,
                    extra_instructions=self._extra_instructions
                    if self._extra_instructions_scope == "all"
                    else None,
                )
                return f"Background agent started. Task ID: {task_id}"

            result = await self._run_agent_loop(
                target,
                message,
                sub_call_id,
                caller_call_id,
                caller_name,
                history=history,
                extra_instructions=self._extra_instructions
                if self._extra_instructions_scope == "all"
                else None,
                caller_loop_id=current_loop_id,
            )

            self._messages.append(
                Message(
                    type="return",
                    sender=agent_name,
                    receiver=caller_name,
                    content=result,
                    call_id=sub_call_id,
                )
            )
            self._record(
                "agent_return",
                agent_name,
                sub_call_id,
                caller_call_id,
                {
                    "result": _truncate(result),
                },
            )
            return f"[{agent_name}]{result}[/{agent_name}]"

        if tc.name == "spawn_background_agent":
            if not self._allow_background_agents:
                return "Error: Background agent spawning is disabled. Use allow_background_agents=True to enable it."

            agent_name = tc.arguments.get("agent_name", "")
            message = tc.arguments.get("message", "")
            history_arg = tc.arguments.get("history")

            history = None
            if history_arg and isinstance(history_arg, list):
                history = []
                for h in history_arg:
                    if isinstance(h, dict):
                        history.append(
                            Message(
                                type=h.get("type", "forward"),
                                sender=h.get("sender", ""),
                                receiver=h.get("receiver", ""),
                                content=h.get("content", ""),
                                call_id=uuid.uuid4().hex,
                            )
                        )

            target = self._resolve_agent_target(agent_name)
            task_id = await self._spawn_background_agent(
                message,
                [target],
                uuid.uuid4().hex,
                caller_call_id,
                caller_name,
                history=history,
                extra_instructions=self._extra_instructions
                if self._extra_instructions_scope == "all"
                else None,
            )
            return f"Background agent started. Task ID: {task_id}"

        if tc.name == "send_message":
            task_id = tc.arguments.get("task_id", "")
            message = tc.arguments.get("message", "")

            registry = AgentLoopRegistry.get_instance()
            bg_loop = registry.get_loop(task_id)

            if bg_loop is None:
                return f"Error: No background agent found with task_id: {task_id}"

            msg = Message(
                type="forward",
                sender=caller_name,
                receiver=bg_loop.agent.name,
                content=message,
                call_id=uuid.uuid4().hex,
            )

            self._messages.append(msg)
            await bg_loop.inject_message(msg)
            return f"Message sent to {bg_loop.agent.name} (task_id: {task_id})"

        if tc.name == "get_messages":
            task_id = tc.arguments.get("task_id", "")
            clear = tc.arguments.get("clear", False)

            registry = AgentLoopRegistry.get_instance()
            bg_loop = registry.get_loop(task_id)

            if bg_loop is None:
                return f"Error: No background agent found with task_id: {task_id}"

            status = bg_loop.get_status()
            messages = bg_loop.get_messages(clear=clear)

            result_parts = [
                f"Task ID: {task_id}",
                f"Agent: {bg_loop.agent.name}",
                f"Status: {status}",
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

        self._record(
            "tool_exec",
            caller_name,
            caller_call_id,
            None,
            {
                "tool_name": tc.name,
                "arguments": tc.arguments,
            },
        )
        tool = self._resolve_tool_target(tc.name)
        try:
            return await tool.execute(**tc.arguments)
        except Exception as exc:
            raise ToolError(tc.name, str(exc)) from exc

    async def _maybe_summarize(self, context: Context, agent: Agent) -> None:
        context_window = agent.context_window
        if context_window is None:
            try:
                context_window = await get_context_window(agent.model)
            except Exception:
                return

        current_tokens = self._estimate_current_tokens(context)
        if current_tokens <= int(context_window * _SUMMARIZE_THRESHOLD):
            return

        tokens_before = current_tokens
        messages = context.messages
        split = find_summarization_boundary(messages, context_window)
        if split is None:
            return

        messages_to_summarize = messages[:split]
        summarize_context = build_self_summarize_context(
            messages_to_summarize, context.system_prompt
        )

        try:
            response = await self._router.call_llm(agent, summarize_context, [])
            self._accumulate_usage(response)
            if response.content:
                parsed = parse_summary_response(response.content)
                summary = parsed.summary
                next_steps = parsed.next_steps

                if self._on_summarize is not None:
                    try:
                        from agentouto.summarizer import SummarizeInfo

                        tokens_after_llm = self._estimate_current_tokens(context)
                        info = SummarizeInfo(
                            agent_name=agent.name,
                            messages_to_summarize=list(messages_to_summarize),
                            summary=summary,
                            next_steps=next_steps,
                            tokens_before=tokens_before,
                            tokens_after=tokens_after_llm,
                        )
                        overridden = self._on_summarize(info)
                        if overridden is not None:
                            summary = overridden
                    except Exception as exc:
                        logger.warning(
                            "[%s] on_summarize callback raised an error: %s",
                            agent.name,
                            exc,
                        )

                context.replace_with_summary(summary, keep_from=split)
                self._last_message_count = len(context.messages)
                if next_steps:
                    context.add_user(
                        f"[SYSTEM] Summary complete. Based on the summary, the following next steps have been identified:\n{next_steps}\n\nProceed with these next steps when you continue."
                    )
                tokens_after = self._estimate_current_tokens(context)
                logger.info(
                    "[%s] Self-summarized %d messages (%d → %d tokens)",
                    agent.name,
                    split,
                    tokens_before,
                    tokens_after,
                )
        except Exception as exc:
            logger.warning("[%s] Self-summarization failed: %s", agent.name, exc)

    def _estimate_current_tokens(self, context: Context) -> int:
        if self._last_input_tokens is not None:
            current_count = len(context.messages)
            new_messages = current_count - self._last_message_count
            if new_messages > 0:
                new_msg_tokens = sum(
                    _estimate_message_tokens(msg)
                    for msg in context.messages[self._last_message_count:]
                )
                return self._last_input_tokens + new_msg_tokens
            return self._last_input_tokens
        return estimate_context_tokens(context)

    async def _spawn_background_agent(
        self,
        forward_message: str,
        starting_agents: list[Agent],
        call_id: str,
        parent_call_id: str | None,
        caller: str | None = None,
        history: list[Message] | None = None,
        extra_instructions: str | None = None,
    ) -> str:
        task_id = f"bg_{uuid.uuid4().hex[:12]}"

        async def executor(
            agnt: Agent, msg: str, hist: list[Message] | None, cid: str
        ) -> str:
            return await self._run_agent_loop(
                agnt,
                msg,
                cid,
                parent_call_id,
                caller,
                history=hist,
                loop_id=cid,
                extra_instructions=extra_instructions,
            )

        for i, agnt in enumerate(starting_agents):
            tid = f"{task_id}_{i}" if i > 0 else task_id
            bg_loop = BackgroundAgentLoop(
                agent=agnt,
                initial_message=forward_message,
                history=history,
                executor=lambda a=agnt, m=forward_message, h=history, c=tid: executor(  # type: ignore[misc]
                    a, m, h, c
                ),
                task_id=tid,
            )
            registry = AgentLoopRegistry.get_instance()
            registry.register(tid, bg_loop)
            bg_loop.start()

        return task_id

    # --- Streaming ---

    async def execute_stream(
        self,
        agent: Agent,
        forward_message: str,
        *,
        attachments: list[Attachment] | None = None,
        history: list[Message] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        from agentouto.loop_manager import RegisteredAgentLoop
        from agentouto.streaming import StreamEvent

        call_id = uuid.uuid4().hex

        user_loop_id: str | None = None
        user_loop: RegisteredAgentLoop | None = None
        user_out_queue: asyncio.Queue[str] | None = None
        if self._on_message is not None:
            user_loop_id = f"user_{call_id}"
            user_out_queue = asyncio.Queue()
            user_agent = Agent(name="user", instructions="", model="", provider="")

            on_message = self._on_message
            out_queue = user_out_queue

            def send(message: str) -> None:
                out_queue.put_nowait(message)

            def _wrapped_on_message(msg: Message) -> None:
                on_message(msg, send)

            user_loop = RegisteredAgentLoop(
                agent=user_agent,
                task_id=user_loop_id,
                on_message=_wrapped_on_message,
            )
            registry = AgentLoopRegistry.get_instance()
            registry.register(user_loop_id, user_loop)

        self._messages.append(
            Message(
                type="forward",
                sender="user",
                receiver=agent.name,
                content=forward_message,
                call_id=call_id,
                attachments=attachments,
            )
        )

        output = ""
        try:
            async for event in self._stream_agent_loop(
                agent,
                forward_message,
                call_id,
                None,
                "user",
                attachments=attachments,
                history=history,
                extra_instructions=self._extra_instructions,
                caller_loop_id=user_loop_id,
                user_out_queue=user_out_queue,
            ):
                if event.type == "finish":
                    output = event.data.get("output", "")
                yield event

                if user_loop is not None:
                    while True:
                        try:
                            msg = user_loop.message_queue._queue.get_nowait()
                            yield StreamEvent(
                                type="user_message",
                                agent_name=msg.sender,
                                call_id=msg.call_id,
                                parent_call_id=call_id,
                                data={"message": msg.content, "sender": msg.sender},
                            )
                        except asyncio.QueueEmpty:
                            break
        finally:
            if user_loop_id is not None:
                AgentLoopRegistry.get_instance().unregister(user_loop_id)

        self._messages.append(
            Message(
                type="return",
                sender=agent.name,
                receiver="user",
                content=output,
                call_id=call_id,
            )
        )

    async def _stream_agent_loop(
        self,
        agent: Agent,
        forward_message: str,
        call_id: str,
        parent_call_id: str | None,
        caller: str | None = None,
        *,
        attachments: list[Attachment] | None = None,
        history: list[Message] | None = None,
        extra_instructions: str | None = None,
        caller_loop_id: str | None = None,
        user_out_queue: asyncio.Queue[str] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        from agentouto.streaming import StreamEvent

        system_prompt = self._router.build_system_prompt(
            agent,
            caller=caller,
            extra_instructions=extra_instructions,
            caller_loop_id=caller_loop_id,
        )
        context = Context(system_prompt)

        if history:
            for msg in history:
                self._add_message_to_context(context, msg)

        context.add_user(forward_message, attachments=attachments)
        tool_schemas = self._router.build_tool_schemas(agent.name)

        while True:
            if user_out_queue is not None:
                try:
                    while True:
                        user_msg = user_out_queue.get_nowait()
                        context.add_user(user_msg)
                except asyncio.QueueEmpty:
                    pass

            await self._maybe_summarize(context, agent)

            response = None
            async for chunk in self._router.stream_llm(agent, context, tool_schemas):
                if isinstance(chunk, str):
                    yield StreamEvent(
                        type="token",
                        agent_name=agent.name,
                        call_id=call_id,
                        parent_call_id=parent_call_id,
                        data={"text": chunk},
                    )
                else:
                    response = chunk

            if response is None:
                yield StreamEvent(
                    type="error",
                    agent_name=agent.name,
                    call_id=call_id,
                    parent_call_id=parent_call_id,
                    data={"error": "No response from LLM"},
                )
                return

            self._accumulate_usage(response)
            self._last_message_count = len(context.messages)

            if not response.tool_calls:
                logger.warning(
                    "[%s] Agent responded with text instead of finish(), nudging",
                    agent.name,
                )
                context.add_assistant_text(response.content or "")
                context.add_user(_FINISH_NUDGE)
                continue

            finish_call = _find_finish(response.tool_calls)
            if finish_call is not None:
                finish_override = self._router.get_builtin_override(FINISH)
                if finish_override is not None:
                    try:
                        raw = await finish_override.execute(**finish_call.arguments)
                        output = (
                            raw.content if isinstance(raw, ToolResult) else str(raw)
                        )
                    except Exception as exc:
                        output = f"Error in finish override: {exc}"
                else:
                    output = finish_call.arguments.get("message", "")
                yield StreamEvent(
                    type="finish",
                    agent_name=agent.name,
                    call_id=call_id,
                    parent_call_id=parent_call_id,
                    data={"output": output},
                )
                return

            context.add_assistant_tool_calls(response.tool_calls, response.content)

            # Process tool calls in parallel using asyncio.gather
            tool_call_tasks = [
                self._execute_streaming_tool_call(
                    tc, agent.name, call_id, parent_call_id, context
                )
                for tc in response.tool_calls
            ]
            all_events = await asyncio.gather(*tool_call_tasks, return_exceptions=True)
            for item in all_events:
                if isinstance(item, Exception):
                    yield StreamEvent(
                        type="error",
                        agent_name=agent.name,
                        call_id=call_id,
                        parent_call_id=parent_call_id,
                        data={"error": f"Unexpected error: {item}"},
                    )
                else:
                    for event in item:  # type: ignore[union-attr]
                        yield event

    # --- Helpers ---

    def _add_message_to_context(self, context: Context, message: Message) -> None:
        if message.type == "forward":
            if message.sender == "user":
                context.add_user(message.content, attachments=message.attachments)
            else:
                context.add_user(
                    f"[Forwarded from {message.sender}]: {message.content}",
                    attachments=message.attachments,
                )
        elif message.type == "return":
            context.add_assistant_text(
                f"[Return from {message.sender}]: {message.content}"
            )

    async def _execute_streaming_tool_call(
        self,
        tc: ToolCall,
        caller_name: str,
        caller_call_id: str,
        parent_call_id: str | None,
        context: Context,
    ) -> list[StreamEvent]:
        from agentouto._constants import BUILTIN_TOOL_NAMES
        from agentouto.streaming import StreamEvent

        events: list[StreamEvent] = []

        override = self._router.get_builtin_override(tc.name)
        if override is not None:
            try:
                result = await override.execute(**tc.arguments)
                result_str = (
                    result.content if isinstance(result, ToolResult) else str(result)
                )
            except Exception as exc:
                result_str = f"Error: {exc}"
            context.add_tool_result(tc.id, tc.name, result_str)
            events.append(
                StreamEvent(
                    type="tool_result",
                    agent_name=caller_name,
                    call_id=caller_call_id,
                    parent_call_id=parent_call_id,
                    data={"tool_name": tc.name, "result": result_str},
                )
            )
            return events

        if tc.name in self._router.disabled_tools and tc.name in BUILTIN_TOOL_NAMES:
            err = f"Error: Tool '{tc.name}' is disabled in this run."
            context.add_tool_result(tc.id, tc.name, err)
            events.append(
                StreamEvent(
                    type="tool_result",
                    agent_name=caller_name,
                    call_id=caller_call_id,
                    parent_call_id=parent_call_id,
                    data={"tool_name": tc.name, "result": err},
                )
            )
            return events

        if tc.name == CALL_AGENT:
            target_name = tc.arguments.get("agent_name", "")
            msg = tc.arguments.get("message", "")
            try:
                target = self._resolve_agent_target(target_name)
            except Exception as exc:
                context.add_tool_result(tc.id, tc.name, f"Error: {exc}")
                events.append(
                    StreamEvent(
                        type="error",
                        agent_name=caller_name,
                        call_id=caller_call_id,
                        parent_call_id=parent_call_id,
                        data={"error": str(exc)},
                    )
                )
                return events

            try:
                sub_call_id = uuid.uuid4().hex
                self._messages.append(
                    Message(
                        type="forward",
                        sender=caller_name,
                        receiver=target_name,
                        content=msg,
                        call_id=sub_call_id,
                    )
                )
                events.append(
                    StreamEvent(
                        type="agent_call",
                        agent_name=target_name,
                        call_id=sub_call_id,
                        parent_call_id=caller_call_id,
                        data={"from": caller_name, "message": _truncate(msg)},
                    )
                )

                sub_result = ""
                sub_extra = (
                    self._extra_instructions
                    if self._extra_instructions_scope == "all"
                    else None
                )
                async for sub_event in self._stream_agent_loop(
                    target,
                    msg,
                    sub_call_id,
                    caller_call_id,
                    caller_name,
                    extra_instructions=sub_extra,
                ):
                    events.append(sub_event)
                    if sub_event.type == "finish":
                        sub_result = sub_event.data.get("output", "")

                self._messages.append(
                    Message(
                        type="return",
                        sender=target_name,
                        receiver=caller_name,
                        content=sub_result,
                        call_id=sub_call_id,
                    )
                )
                events.append(
                    StreamEvent(
                        type="agent_return",
                        agent_name=target_name,
                        call_id=sub_call_id,
                        parent_call_id=caller_call_id,
                        data={"result": _truncate(sub_result)},
                    )
                )
                context.add_tool_result(
                    tc.id, tc.name, f"[{target_name}]{sub_result}[/{target_name}]"
                )
            except Exception as exc:
                context.add_tool_result(tc.id, tc.name, f"Error: {exc}")
                events.append(
                    StreamEvent(
                        type="error",
                        agent_name=caller_name,
                        call_id=sub_call_id,
                        parent_call_id=caller_call_id,
                        data={"error": str(exc)},
                    )
                )
        else:
            try:
                tool = self._resolve_tool_target(tc.name)
            except Exception as exc:
                context.add_tool_result(tc.id, tc.name, f"Error: {exc}")
                events.append(
                    StreamEvent(
                        type="error",
                        agent_name=caller_name,
                        call_id=caller_call_id,
                        parent_call_id=parent_call_id,
                        data={"error": str(exc)},
                    )
                )
                return events

            events.append(
                StreamEvent(
                    type="tool_call",
                    agent_name=caller_name,
                    call_id=caller_call_id,
                    parent_call_id=parent_call_id,
                    data={"tool_name": tc.name, "arguments": tc.arguments},
                )
            )
            try:
                result = await tool.execute(**tc.arguments)
            except Exception as exc:
                result = f"Error: {exc}"
            if isinstance(result, ToolResult):
                context.add_tool_result(
                    tc.id,
                    tc.name,
                    result.content,
                    attachments=result.attachments,
                )
                attachments_data = None
                if result.attachments:
                    attachments_data = [
                        {
                            "mime_type": att.mime_type,
                            "data": att.data,
                            "url": att.url,
                            "name": att.name,
                        }
                        for att in result.attachments
                    ]
                events.append(
                    StreamEvent(
                        type="tool_result",
                        agent_name=caller_name,
                        call_id=caller_call_id,
                        parent_call_id=parent_call_id,
                        data={
                            "tool_name": tc.name,
                            "result": result.content,
                            "attachments": attachments_data,
                        },
                    )
                )
            else:
                context.add_tool_result(tc.id, tc.name, result)
                events.append(
                    StreamEvent(
                        type="tool_result",
                        agent_name=caller_name,
                        call_id=caller_call_id,
                        parent_call_id=parent_call_id,
                        data={"tool_name": tc.name, "result": str(result)},
                    )
                )

        return events

    def _record(
        self,
        event_type: str,
        agent_name: str,
        call_id: str,
        parent_call_id: str | None,
        details: dict,
    ) -> None:
        if self._event_log is None:
            return
        event = AgentEvent(
            event_type=event_type,  # type: ignore[arg-type]
            agent_name=agent_name,
            call_id=call_id,
            parent_call_id=parent_call_id,
            details=details,
        )
        self._event_log.record(event)
        logger.debug("[%s] %s cid=%s %s", agent_name, event_type, call_id[:8], details)


def _find_finish(tool_calls: list[ToolCall]) -> ToolCall | None:
    for tc in tool_calls:
        if tc.name == FINISH:
            return tc
    return None


def _truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


async def async_run(
    message: str,
    starting_agents: list[Agent] | None = None,
    tools: list[Tool] | None = None,
    providers: list[Provider] | None = None,
    *,
    attachments: list[Attachment] | None = None,
    history: list[Message] | None = None,
    debug: bool = False,
    extra_instructions: str | None = None,
    extra_instructions_scope: Literal["entry", "all"] = "entry",
    run_agents: list[Agent] | None = None,
    disabled_tools: set[str] | None = None,
    on_message: Callable[[Message, Callable[[str], None]], None] | None = None,
    allow_background_agents: bool = False,
    on_summarize: Callable[[SummarizeInfo], str | None] | None = None,
) -> RunResult:
    if starting_agents is None or len(starting_agents) == 0:
        raise ValueError(
            "starting_agents must be provided (list of agents to start in parallel)"
        )

    run_agents_list = run_agents if run_agents is not None else starting_agents

    # Warning: agents in starting_agents but not in run_agents cannot participate
    if run_agents is not None:
        starting_names = {a.name for a in starting_agents}
        run_names = {a.name for a in run_agents}
        missing = starting_names - run_names
        if missing:
            warnings.warn(
                f"Agents in starting_agents but not in run_agents: {missing}. "
                f"These agents will execute but cannot call or perceive other agents. "
                f"Consider adding them to run_agents or removing from starting_agents.",
                UserWarning,
                stacklevel=2,
            )

    router = Router(
        run_agents_list,
        tools or [],
        providers or [],
        run_agents=run_agents_list,
        disabled_tools=disabled_tools,
        allow_background_agents=allow_background_agents,
    )
    runtime = Runtime(
        router,
        debug=debug,
        extra_instructions=extra_instructions,
        extra_instructions_scope=extra_instructions_scope,
        on_message=on_message,
        allow_background_agents=allow_background_agents,
        on_summarize=on_summarize,
    )
    return await runtime.execute(
        message,
        starting_agents=starting_agents,
        attachments=attachments,
        history=history,
    )


def run(
    message: str,
    starting_agents: list[Agent],
    tools: list[Tool] | None = None,
    providers: list[Provider] | None = None,
    *,
    attachments: list[Attachment] | None = None,
    history: list[Message] | None = None,
    debug: bool = False,
    extra_instructions: str | None = None,
    extra_instructions_scope: Literal["entry", "all"] = "entry",
    run_agents: list[Agent] | None = None,
    disabled_tools: set[str] | None = None,
    on_message: Callable[[Message, Callable[[str], None]], None] | None = None,
    allow_background_agents: bool = False,
    on_summarize: Callable[[SummarizeInfo], str | None] | None = None,
) -> RunResult:
    return asyncio.run(
        async_run(
            message,
            starting_agents,
            tools,
            providers,
            attachments=attachments,
            history=history,
            debug=debug,
            extra_instructions=extra_instructions,
            extra_instructions_scope=extra_instructions_scope,
            run_agents=run_agents,
            disabled_tools=disabled_tools,
            on_message=on_message,
            allow_background_agents=allow_background_agents,
            on_summarize=on_summarize,
        )
    )


def send_message_to_background_agent(task_id: str, message: str) -> str:
    """Send a message to a background agent.

    This is a user-facing function to communicate with agents running in
    isolated background loops. The agent will receive the message as a
    new user input in its running loop.

    Args:
        task_id: The task ID returned when spawning a background agent
                 (e.g., "bg_abc123" from call_agent with background=True)
        message: The message content to send to the agent

    Returns:
        A confirmation string with the agent name and task_id

    Raises:
        AgentError: If no background agent with the given task_id exists

    Example:
        # Agent A spawns B in background
        # call_agent(agent_name="B", message="Work", background=True)
        # Returns: "Background agent started. Task ID: bg_abc123"
        #
        # User sends message to B:
        send_message_to_background_agent("bg_abc123", "Add more details")
    """
    from agentouto.loop_manager import AgentLoopRegistry

    registry = AgentLoopRegistry.get_instance()
    bg_loop = registry.get_loop(task_id)

    if bg_loop is None:
        from agentouto.exceptions import AgentError

        raise AgentError(
            "unknown", f"No background agent found with task_id: {task_id}"
        )

    msg = Message(
        type="forward",
        sender="user",
        receiver=bg_loop.agent.name,
        content=message,
        call_id=uuid.uuid4().hex,
    )

    # Need to run the async inject_message
    asyncio.run(bg_loop.inject_message(msg))

    return f"Message sent to {bg_loop.agent.name} (task_id: {task_id})"


def get_background_agent_status(task_id: str) -> str:
    """Get status and messages from a background agent.

    Args:
        task_id: The task ID of the background agent

    Returns:
        A formatted string with task_id, agent name, status, result (if any),
        error (if any), and all messages collected so far

    Raises:
        AgentError: If no background agent with the given task_id exists

    Example:
        status = get_background_agent_status("bg_abc123")
        print(status)
        # Task ID: bg_abc123
        # Agent: writer
        # Status: running
        # Messages (3):
        #   [forward] user -> writer: Work on report...
    """
    from agentouto.loop_manager import AgentLoopRegistry

    registry = AgentLoopRegistry.get_instance()
    bg_loop = registry.get_loop(task_id)

    if bg_loop is None:
        from agentouto.exceptions import AgentError

        raise AgentError(
            "unknown", f"No background agent found with task_id: {task_id}"
        )

    status = bg_loop.get_status()
    messages = bg_loop.get_messages(clear=False)

    result_parts = [
        f"Task ID: {task_id}",
        f"Agent: {bg_loop.agent.name}",
        f"Status: {status}",
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


async def run_background(
    message: str,
    starting_agents: list[Agent] | None = None,
    tools: list[Tool] | None = None,
    providers: list[Provider] | None = None,
    *,
    attachments: list[Attachment] | None = None,
    history: list[Message] | None = None,
    extra_instructions: str | None = None,
    extra_instructions_scope: Literal["entry", "all"] = "entry",
    run_agents: list[Agent] | None = None,
    disabled_tools: set[str] | None = None,
    allow_background_agents: bool = False,
    on_summarize: Callable[[SummarizeInfo], str | None] | None = None,
) -> str:
    if starting_agents is None or len(starting_agents) == 0:
        raise ValueError(
            "starting_agents must be provided (list of agents to start in parallel)"
        )

    run_agents_list = run_agents if run_agents is not None else starting_agents

    if run_agents is not None:
        starting_names = {a.name for a in starting_agents}
        run_names = {a.name for a in run_agents}
        missing = starting_names - run_names
        if missing:
            warnings.warn(
                f"Agents in starting_agents but not in run_agents: {missing}. "
                f"These agents will not be able to participate in this run.",
                UserWarning,
                stacklevel=2,
            )

    router = Router(
        run_agents_list,
        tools or [],
        providers or [],
        run_agents=run_agents_list,
        disabled_tools=disabled_tools,
        allow_background_agents=allow_background_agents,
    )
    runtime = Runtime(
        router,
        extra_instructions=extra_instructions,
        extra_instructions_scope=extra_instructions_scope,
        allow_background_agents=allow_background_agents,
        on_summarize=on_summarize,
    )
    return await runtime._spawn_background_agent(
        message,
        starting_agents,
        uuid.uuid4().hex,
        None,
        "user",
        history=history,
        extra_instructions=extra_instructions,
    )


def run_background_sync(
    message: str,
    starting_agents: list[Agent] | None = None,
    tools: list[Tool] | None = None,
    providers: list[Provider] | None = None,
    *,
    attachments: list[Attachment] | None = None,
    history: list[Message] | None = None,
    extra_instructions: str | None = None,
    extra_instructions_scope: Literal["entry", "all"] = "entry",
    run_agents: list[Agent] | None = None,
    disabled_tools: set[str] | None = None,
    allow_background_agents: bool = False,
    on_summarize: Callable[[SummarizeInfo], str | None] | None = None,
) -> str:
    return asyncio.run(
        run_background(
            message,
            starting_agents,
            tools,
            providers,
            attachments=attachments,
            history=history,
            extra_instructions=extra_instructions,
            extra_instructions_scope=extra_instructions_scope,
            run_agents=run_agents,
            disabled_tools=disabled_tools,
            allow_background_agents=allow_background_agents,
            on_summarize=on_summarize,
        )
    )


async def get_stream_events(task_id: str):
    from agentouto.loop_manager import AgentLoopRegistry

    registry = AgentLoopRegistry.get_instance()
    bg_loop = registry.get_loop(task_id)

    if bg_loop is None:
        from agentouto.exceptions import AgentError

        raise AgentError("unknown", f"No agent found with task_id: {task_id}")

    event_queue: asyncio.Queue[dict] = asyncio.Queue()
    bg_loop.set_event_queue(event_queue)

    while True:
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=30.0)
            yield event
            if event.get("type") == "finish":
                break
        except TimeoutError:
            if bg_loop.get_status() in {"completed", "failed"}:
                break


send_message = send_message_to_background_agent
get_agent_status = get_background_agent_status
