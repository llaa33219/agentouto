from __future__ import annotations

import asyncio
import logging
import uuid
import warnings
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from agentouto._bridge import run_agent_loop
from agentouto._bridge.state import RunState, bind_run_state, get_run_state
from agentouto._bridge.state import unbind_run_state as _unbind_run_state
from agentouto._bridge.tools import background_report, execute_tool_logic, truncate
from agentouto.agent import Agent
from agentouto.context import Attachment, ToolCall
from agentouto.event_log import AgentEvent, EventLog
from agentouto.loop_manager import AgentLoopRegistry, BackgroundAgentLoop
from agentouto.message import Message
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, Usage
from agentouto.router import Router
from agentouto.summarizer import SummarizeInfo
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
                "message": truncate(forward_message),
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
                "result": truncate(output),
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
        stream: bool | None = None,
        event_queue: asyncio.Queue[StreamEvent] | None = None,
    ) -> str:
        """Thin orchestration: the turn loop itself is ``coreouto.Agent.call()``."""
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

        ambient = get_run_state()
        if stream is None:
            stream = ambient.stream if ambient is not None else False
        if event_queue is None:
            event_queue = ambient.event_queue if ambient is not None else None

        state = RunState(
            runtime=self,
            agent=agent,
            forward_message=forward_message,
            call_id=call_id,
            parent_call_id=parent_call_id,
            caller=caller,
            loop_id=loop_id,
            system_prompt=self._router.build_system_prompt(
                agent,
                caller=caller,
                extra_instructions=extra_instructions,
                caller_loop_id=caller_loop_id,
            ),
            attachments=attachments,
            history=history,
            caller_loop_id=caller_loop_id,
            stream=stream,
            event_queue=event_queue,
            registered_loop=registered_loop,
            user_out_queue=user_out_queue,
        )

        try:
            return await run_agent_loop(state)
        finally:
            registry.unregister(loop_id)

    async def _execute_tool_call(
        self,
        tc: ToolCall,
        caller_name: str,
        caller_call_id: str,
        *,
        current_loop_id: str | None = None,
    ) -> str | ToolResult:
        state = RunState(
            runtime=self,
            agent=None,
            call_id=caller_call_id,
            caller_name=caller_name,
            loop_id=current_loop_id or caller_call_id,
            stream=False,
        )
        token = bind_run_state(state)
        try:
            return await execute_tool_logic(state, tc.name, tc.arguments)
        finally:
            _unbind_run_state(token)

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
                stream=False,
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
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        loop_task = asyncio.create_task(
            self._run_agent_loop(
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
                stream=True,
                event_queue=queue,
            )
        )
        try:
            while True:
                getter = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    {getter, loop_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if getter not in done:
                    # The loop ended without emitting a finish event.
                    getter.cancel()
                    break
                event = getter.result()
                if event.type == "finish":
                    output = event.data.get("output", "")
                yield event
                if event.type == "finish":
                    break
                if user_loop is not None:
                    while True:
                        try:
                            msg = user_loop.message_queue._queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        yield StreamEvent(
                            type="user_message",
                            agent_name=msg.sender,
                            call_id=msg.call_id,
                            parent_call_id=call_id,
                            data={"message": msg.content, "sender": msg.sender},
                        )
            await loop_task
        finally:
            if user_loop_id is not None:
                AgentLoopRegistry.get_instance().unregister(user_loop_id)
            if not loop_task.done():
                loop_task.cancel()
                await asyncio.gather(loop_task, return_exceptions=True)

        self._messages.append(
            Message(
                type="return",
                sender=agent.name,
                receiver="user",
                content=output,
                call_id=call_id,
            )
        )

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

    return background_report(bg_loop, task_id, bg_loop.get_messages(clear=False))


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