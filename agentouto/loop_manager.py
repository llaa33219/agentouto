from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from agentouto import Agent, Message
from agentouto.exceptions import AgentError

LoopStatus = Literal["pending", "running", "completed", "failed"]
LoopExecutor = Callable[[Agent, str, list[Message] | None], Awaitable[str]]


class AgentLoopRegistry:
    _instance: AgentLoopRegistry | None = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._loops: dict[str, BackgroundAgentLoop] = {}
        self._lock: threading.RLock = threading.RLock()

    @classmethod
    def get_instance(cls) -> AgentLoopRegistry:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, loop_id: str, bg_loop: BackgroundAgentLoop) -> None:
        with self._lock:
            self._loops[loop_id] = bg_loop

    def unregister(self, loop_id: str) -> None:
        with self._lock:
            _ = self._loops.pop(loop_id, None)

    def get_loop(self, loop_id: str) -> BackgroundAgentLoop | None:
        with self._lock:
            return self._loops.get(loop_id)

    def get_all_loops(self) -> dict[str, BackgroundAgentLoop]:
        with self._lock:
            return dict(self._loops)

    def get_task_ids(self) -> list[str]:
        with self._lock:
            return list(self._loops.keys())


class MessageQueue:
    def __init__(self, max_size: int = 100) -> None:
        self._queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=max_size)
        self._lock: asyncio.Lock = asyncio.Lock()

    async def enqueue(self, message: Message) -> None:
        async with self._lock:
            if self._queue.full():
                try:
                    _ = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await self._queue.put(message)

    async def dequeue(self, timeout: float | None = None) -> Message | None:
        if timeout is None:
            return await self._queue.get()
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def peek(self) -> list[Message]:
        async with self._lock:
            items: list[Message] = []
            buffered: list[Message] = []
            while not self._queue.empty():
                message = self._queue.get_nowait()
                items.append(message)
                buffered.append(message)
            for message in buffered:
                self._queue.put_nowait(message)
            return items

    async def clear(self) -> None:
        async with self._lock:
            while not self._queue.empty():
                try:
                    _ = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break


@dataclass
class BackgroundResult:
    task_id: str
    status: LoopStatus
    result: str | None = None
    error: str | None = None
    messages: list[Message] = field(default_factory=list)


@dataclass
class BackgroundAgentLoop:
    agent: Agent
    initial_message: str
    history: list[Message] | None = None
    executor: LoopExecutor | None = None
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: LoopStatus = "pending"
    result: str | None = None
    error: str | None = None
    messages: list[Message] = field(default_factory=list)
    message_queue: MessageQueue = field(default_factory=MessageQueue)
    _runner_task: asyncio.Task[None] | None = field(
        default=None, init=False, repr=False
    )
    _done_event: asyncio.Event = field(
        default_factory=asyncio.Event, init=False, repr=False
    )

    def start(self) -> None:
        if self._runner_task is not None and not self._runner_task.done():
            raise AgentError(self.agent.name, "Background loop is already running.")
        if self.status not in {"pending", "failed"}:
            raise AgentError(
                self.agent.name,
                f"Cannot start background loop from status '{self.status}'.",
            )

        self._done_event.clear()
        self._runner_task = asyncio.create_task(self._run())

    async def inject_message(self, message: Message) -> None:
        if self.status not in {"pending", "running"}:
            raise AgentError(
                self.agent.name,
                f"Cannot inject message when status is '{self.status}'.",
            )
        self.messages.append(message)
        await self.message_queue.enqueue(message)

    def get_status(self) -> LoopStatus:
        return self.status

    async def get_result(self) -> str:
        _ = await self._done_event.wait()
        if self.status == "failed":
            raise AgentError(self.agent.name, self.error or "Background loop failed.")
        return self.result or ""

    def get_messages(self, clear: bool = False) -> list[Message]:
        collected = list(self.messages)
        if clear:
            self.messages.clear()
        return collected

    async def _run(self) -> None:
        self.status = "running"
        self.result = None
        self.error = None

        try:
            self.messages.append(
                Message(
                    type="forward",
                    sender="user",
                    receiver=self.agent.name,
                    content=self.initial_message,
                    call_id=self.task_id,
                )
            )

            if self.executor is None:
                raise AgentError(
                    self.agent.name,
                    "No background executor configured for this loop.",
                )

            self.result = await self.executor(
                self.agent,
                self.initial_message,
                self.history,
            )

            self.messages.append(
                Message(
                    type="return",
                    sender=self.agent.name,
                    receiver="user",
                    content=self.result,
                    call_id=self.task_id,
                )
            )
            self.status = "completed"
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
        finally:
            self._done_event.set()


__all__ = [
    "AgentLoopRegistry",
    "BackgroundAgentLoop",
    "BackgroundResult",
    "MessageQueue",
]
