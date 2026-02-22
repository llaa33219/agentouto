from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentouto._constants import CALL_AGENT, FINISH
from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ToolCall
from agentouto.event_log import AgentEvent, EventLog
from agentouto.exceptions import ToolError
from agentouto.message import Message
from agentouto.provider import Provider
from agentouto.router import Router
from agentouto.tool import Tool, ToolResult
from agentouto.tracing import Trace

if TYPE_CHECKING:
    from agentouto.streaming import StreamEvent

logger = logging.getLogger("agentouto")


@dataclass
class RunResult:
    output: str
    messages: list[Message] = field(default_factory=list)
    trace: Trace | None = None
    event_log: EventLog | None = None

    def format_trace(self) -> str:
        if self.trace is None:
            return "(no trace — run with debug=True)"
        return self.trace.print_tree()


class Runtime:
    def __init__(self, router: Router, debug: bool = False) -> None:
        self._router = router
        self._debug = debug
        self._event_log: EventLog | None = EventLog() if debug else None
        self._messages: list[Message] = []

    async def execute(
        self,
        agent: Agent,
        forward_message: str,
        *,
        attachments: list[Attachment] | None = None,
    ) -> RunResult:
        call_id = uuid.uuid4().hex

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
        self._record("agent_call", agent.name, call_id, None, {
            "message": _truncate(forward_message),
        })

        output = await self._run_agent_loop(
            agent, forward_message, call_id, None, attachments=attachments
        )

        self._messages.append(
            Message(
                type="return",
                sender=agent.name,
                receiver="user",
                content=output,
                call_id=call_id,
            )
        )
        self._record("agent_return", agent.name, call_id, None, {
            "result": _truncate(output),
        })

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
        )

    async def _run_agent_loop(
        self,
        agent: Agent,
        forward_message: str,
        call_id: str,
        parent_call_id: str | None,
        *,
        attachments: list[Attachment] | None = None,
    ) -> str:
        system_prompt = self._router.build_system_prompt(agent)
        context = Context(system_prompt)
        context.add_user(forward_message, attachments=attachments)
        tool_schemas = self._router.build_tool_schemas(agent.name)

        while True:
            self._record("llm_call", agent.name, call_id, parent_call_id, {
                "model": agent.model,
            })

            response = await self._router.call_llm(agent, context, tool_schemas)

            self._record("llm_response", agent.name, call_id, parent_call_id, {
                "has_tool_calls": bool(response.tool_calls),
                "content_length": len(response.content) if response.content else 0,
            })

            if not response.tool_calls:
                return response.content or ""

            finish_call = _find_finish(response.tool_calls)
            if finish_call is not None:
                result = finish_call.arguments.get("message", "")
                self._record("finish", agent.name, call_id, parent_call_id, {
                    "result": _truncate(result),
                })
                return result

            context.add_assistant_tool_calls(response.tool_calls, response.content)

            tasks = [
                self._execute_tool_call(tc, agent.name, call_id)
                for tc in response.tool_calls
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for tc, result in zip(response.tool_calls, results):
                if isinstance(result, BaseException):
                    context.add_tool_result(tc.id, tc.name, f"Error: {result}")
                elif isinstance(result, ToolResult):
                    context.add_tool_result(
                        tc.id, tc.name, result.content,
                        attachments=result.attachments,
                    )
                else:
                    context.add_tool_result(tc.id, tc.name, result)

    async def _execute_tool_call(
        self, tc: ToolCall, caller_name: str, caller_call_id: str
    ) -> str | ToolResult:
        if tc.name == CALL_AGENT:
            agent_name = tc.arguments.get("agent_name", "")
            message = tc.arguments.get("message", "")
            target = self._router.get_agent(agent_name)

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
            self._record("agent_call", agent_name, sub_call_id, caller_call_id, {
                "from": caller_name,
                "message": _truncate(message),
            })

            result = await self._run_agent_loop(
                target, message, sub_call_id, caller_call_id
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
            self._record("agent_return", agent_name, sub_call_id, caller_call_id, {
                "result": _truncate(result),
            })
            return result

        self._record("tool_exec", caller_name, caller_call_id, None, {
            "tool_name": tc.name,
            "arguments": tc.arguments,
        })
        tool = self._router.get_tool(tc.name)
        try:
            return await tool.execute(**tc.arguments)
        except Exception as exc:
            raise ToolError(tc.name, str(exc)) from exc

    # --- Streaming ---

    async def execute_stream(
        self,
        agent: Agent,
        forward_message: str,
        *,
        attachments: list[Attachment] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        from agentouto.streaming import StreamEvent

        call_id = uuid.uuid4().hex
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
        async for event in self._stream_agent_loop(
            agent, forward_message, call_id, None, attachments=attachments
        ):
            if event.type == "finish":
                output = event.data.get("output", "")
            yield event

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
        *,
        attachments: list[Attachment] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        from agentouto.streaming import StreamEvent

        system_prompt = self._router.build_system_prompt(agent)
        context = Context(system_prompt)
        context.add_user(forward_message, attachments=attachments)
        tool_schemas = self._router.build_tool_schemas(agent.name)

        while True:
            response = None
            async for chunk in self._router.stream_llm(
                agent, context, tool_schemas
            ):
                if isinstance(chunk, str):
                    yield StreamEvent(
                        type="token",
                        agent_name=agent.name,
                        data={"text": chunk},
                    )
                else:
                    response = chunk

            if response is None:
                yield StreamEvent(
                    type="error",
                    agent_name=agent.name,
                    data={"error": "No response from LLM"},
                )
                return

            if not response.tool_calls:
                yield StreamEvent(
                    type="finish",
                    agent_name=agent.name,
                    data={"output": response.content or ""},
                )
                return

            finish_call = _find_finish(response.tool_calls)
            if finish_call is not None:
                yield StreamEvent(
                    type="finish",
                    agent_name=agent.name,
                    data={"output": finish_call.arguments.get("message", "")},
                )
                return

            context.add_assistant_tool_calls(response.tool_calls, response.content)

            for tc in response.tool_calls:
                if tc.name == CALL_AGENT:
                    target_name = tc.arguments.get("agent_name", "")
                    msg = tc.arguments.get("message", "")
                    target = self._router.get_agent(target_name)

                    sub_call_id = uuid.uuid4().hex
                    self._messages.append(
                        Message(
                            type="forward",
                            sender=agent.name,
                            receiver=target_name,
                            content=msg,
                            call_id=sub_call_id,
                        )
                    )
                    yield StreamEvent(
                        type="agent_call",
                        agent_name=target_name,
                        data={"from": agent.name, "message": _truncate(msg)},
                    )

                    sub_result = ""
                    async for sub_event in self._stream_agent_loop(
                        target, msg, sub_call_id, call_id
                    ):
                        yield sub_event
                        if sub_event.type == "finish":
                            sub_result = sub_event.data.get("output", "")

                    self._messages.append(
                        Message(
                            type="return",
                            sender=target_name,
                            receiver=agent.name,
                            content=sub_result,
                            call_id=sub_call_id,
                        )
                    )
                    yield StreamEvent(
                        type="agent_return",
                        agent_name=target_name,
                        data={"result": _truncate(sub_result)},
                    )
                    context.add_tool_result(tc.id, tc.name, sub_result)
                else:
                    tool = self._router.get_tool(tc.name)
                    yield StreamEvent(
                        type="tool_call",
                        agent_name=agent.name,
                        data={"tool_name": tc.name, "arguments": tc.arguments},
                    )
                    try:
                        result = await tool.execute(**tc.arguments)
                    except Exception as exc:
                        result = f"Error: {exc}"
                    if isinstance(result, ToolResult):
                        context.add_tool_result(
                            tc.id, tc.name, result.content,
                            attachments=result.attachments,
                        )
                    else:
                        context.add_tool_result(tc.id, tc.name, result)

    # --- Helpers ---

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
        logger.debug(
            "[%s] %s cid=%s %s", agent_name, event_type, call_id[:8], details
        )


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
    entry: Agent,
    message: str,
    agents: list[Agent],
    tools: list[Tool],
    providers: list[Provider],
    *,
    attachments: list[Attachment] | None = None,
    debug: bool = False,
) -> RunResult:
    router = Router(agents, tools, providers)
    runtime = Runtime(router, debug=debug)
    return await runtime.execute(entry, message, attachments=attachments)


def run(
    entry: Agent,
    message: str,
    agents: list[Agent],
    tools: list[Tool],
    providers: list[Provider],
    *,
    attachments: list[Attachment] | None = None,
    debug: bool = False,
) -> RunResult:
    return asyncio.run(
        async_run(
            entry, message, agents, tools, providers,
            attachments=attachments, debug=debug,
        )
    )
