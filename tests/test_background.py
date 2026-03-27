from __future__ import annotations

import asyncio
import importlib
from typing import Any
from unittest.mock import patch

import pytest

from agentouto.agent import Agent
from agentouto.context import Context, ToolCall
from agentouto.message import Message
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend
from agentouto.router import Router
from agentouto.runtime import Runtime

loop_manager = importlib.import_module("agentouto.loop_manager")
AgentLoopRegistry = loop_manager.AgentLoopRegistry
BackgroundAgentLoop = loop_manager.BackgroundAgentLoop
MessageQueue = loop_manager.MessageQueue


class MockBackend(ProviderBackend):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def call(
        self,
        context: Context,
        tools: list[dict[str, Any]],
        agent: Agent,
        provider: Provider,
    ) -> LLMResponse:
        assert self._call_count < len(self._responses), (
            f"MockBackend exhausted: {self._call_count} calls made, "
            f"only {len(self._responses)} responses configured"
        )
        response = self._responses[self._call_count]
        self._call_count += 1
        return response


def _finish(message: str) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCall(id="fin_1", name="finish", arguments={"message": message})
        ],
    )


def _mk_agent(name: str) -> Agent:
    return Agent(
        name=name, instructions=f"{name} agent", model="gpt-4o", provider="openai"
    )


def _mk_runtime(*agents: Agent) -> Runtime:
    provider = Provider(name="openai", kind="openai", api_key="sk-test")
    router = Router(list(agents), [], [provider])
    return Runtime(router)


def _clear_registry() -> None:
    registry = AgentLoopRegistry.get_instance()
    for task_id in registry.get_task_ids():
        registry.unregister(task_id)


@pytest.fixture(autouse=True)
def clean_registry() -> Any:
    _clear_registry()
    yield
    _clear_registry()


class TestAgentLoopRegistry:
    def test_singleton(self) -> None:
        r1 = AgentLoopRegistry.get_instance()
        r2 = AgentLoopRegistry.get_instance()
        assert r1 is r2

    def test_register_unregister_get_loop_and_task_ids(self) -> None:
        registry = AgentLoopRegistry.get_instance()
        loop_a = BackgroundAgentLoop(agent=_mk_agent("a"), initial_message="hi")
        loop_b = BackgroundAgentLoop(agent=_mk_agent("b"), initial_message="yo")

        registry.register("task_a", loop_a)
        registry.register("task_b", loop_b)

        assert registry.get_loop("task_a") is loop_a
        assert registry.get_loop("task_b") is loop_b
        assert registry.get_loop("missing") is None
        assert set(registry.get_task_ids()) == {"task_a", "task_b"}

        registry.unregister("task_a")
        assert registry.get_loop("task_a") is None
        assert registry.get_task_ids() == ["task_b"]


class TestMessageQueue:
    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self) -> None:
        queue = MessageQueue()
        msg = Message(type="forward", sender="user", receiver="agent", content="hello")

        await queue.enqueue(msg)
        result = await queue.dequeue(timeout=0.1)

        assert result is msg

    @pytest.mark.asyncio
    async def test_peek_does_not_consume(self) -> None:
        queue = MessageQueue()
        m1 = Message(type="forward", sender="u", receiver="a", content="one")
        m2 = Message(type="forward", sender="u", receiver="a", content="two")
        await queue.enqueue(m1)
        await queue.enqueue(m2)

        peeked = await queue.peek()
        assert [m.content for m in peeked] == ["one", "two"]

        d1 = await queue.dequeue(timeout=0.1)
        d2 = await queue.dequeue(timeout=0.1)
        assert d1 is m1
        assert d2 is m2

    @pytest.mark.asyncio
    async def test_clear_empties_queue(self) -> None:
        queue = MessageQueue()
        await queue.enqueue(
            Message(type="forward", sender="u", receiver="a", content="one")
        )
        await queue.enqueue(
            Message(type="forward", sender="u", receiver="a", content="two")
        )

        await queue.clear()

        assert await queue.peek() == []
        assert await queue.dequeue(timeout=0.01) is None

    @pytest.mark.asyncio
    async def test_max_size_drops_oldest(self) -> None:
        queue = MessageQueue(max_size=2)
        m1 = Message(type="forward", sender="u", receiver="a", content="oldest")
        m2 = Message(type="forward", sender="u", receiver="a", content="middle")
        m3 = Message(type="forward", sender="u", receiver="a", content="newest")

        await queue.enqueue(m1)
        await queue.enqueue(m2)
        await queue.enqueue(m3)

        d1 = await queue.dequeue(timeout=0.1)
        d2 = await queue.dequeue(timeout=0.1)
        assert d1 is m2
        assert d2 is m3


class TestBackgroundAgentLoop:
    @pytest.mark.asyncio
    async def test_status_transitions_pending_running_completed(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def executor(
            agent: Agent, message: str, history: list[Message] | None
        ) -> str:
            started.set()
            await release.wait()
            return f"done: {message}"

        bg_loop = BackgroundAgentLoop(
            agent=_mk_agent("worker"),
            initial_message="process this",
            executor=executor,
        )

        assert bg_loop.get_status() == "pending"
        bg_loop.start()
        await asyncio.wait_for(started.wait(), timeout=1)
        assert bg_loop.get_status() == "running"

        release.set()
        result = await bg_loop.get_result()
        assert result == "done: process this"
        assert bg_loop.get_status() == "completed"

    @pytest.mark.asyncio
    async def test_start_creates_task(self) -> None:
        release = asyncio.Event()

        async def executor(
            agent: Agent, message: str, history: list[Message] | None
        ) -> str:
            await release.wait()
            return "ok"

        bg_loop = BackgroundAgentLoop(
            agent=_mk_agent("worker"),
            initial_message="hello",
            executor=executor,
        )

        bg_loop.start()
        assert bg_loop._runner_task is not None
        assert not bg_loop._runner_task.done()

        release.set()
        assert await bg_loop.get_result() == "ok"

    @pytest.mark.asyncio
    async def test_inject_message_and_get_messages(self) -> None:
        bg_loop = BackgroundAgentLoop(
            agent=_mk_agent("worker"), initial_message="hello"
        )
        injected = Message(
            type="forward", sender="tester", receiver="worker", content="ping"
        )

        await bg_loop.inject_message(injected)

        messages = bg_loop.get_messages()
        assert injected in messages
        queued = await bg_loop.message_queue.dequeue(timeout=0.1)
        assert queued is injected

    @pytest.mark.asyncio
    async def test_get_messages_clear(self) -> None:
        bg_loop = BackgroundAgentLoop(
            agent=_mk_agent("worker"), initial_message="hello"
        )
        msg = Message(
            type="forward", sender="tester", receiver="worker", content="to-clear"
        )
        await bg_loop.inject_message(msg)

        assert len(bg_loop.get_messages(clear=False)) == 1
        assert len(bg_loop.get_messages(clear=True)) == 1
        assert bg_loop.get_messages(clear=False) == []

    @pytest.mark.asyncio
    async def test_get_result_blocks_until_complete(self) -> None:
        finished = asyncio.Event()

        async def executor(
            agent: Agent, message: str, history: list[Message] | None
        ) -> str:
            await asyncio.sleep(0.05)
            finished.set()
            return "finished"

        bg_loop = BackgroundAgentLoop(
            agent=_mk_agent("worker"),
            initial_message="wait",
            executor=executor,
        )
        bg_loop.start()

        result = await bg_loop.get_result()
        assert result == "finished"
        assert finished.is_set()


class TestBackgroundExecutionIntegration:
    @pytest.mark.asyncio
    async def test_call_agent_background_returns_task_id_and_runs(self) -> None:
        caller = _mk_agent("caller")
        worker = _mk_agent("worker")
        runtime = _mk_runtime(caller, worker)

        mock = MockBackend([_finish("background done")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await runtime._execute_tool_call(
                ToolCall(
                    id="tc1",
                    name="call_agent",
                    arguments={
                        "agent_name": "worker",
                        "message": "run in background",
                        "background": True,
                    },
                ),
                caller_name="caller",
                caller_call_id="cid_parent",
            )

            assert isinstance(result, str)
            assert result.startswith("Background agent started. Task ID: bg_")
            task_id = result.split("Task ID: ")[1]

            registry = AgentLoopRegistry.get_instance()
            bg_loop = registry.get_loop(task_id)
            assert bg_loop is not None

            final = await bg_loop.get_result()
            assert final == "background done"
            assert bg_loop.get_status() == "completed"

    @pytest.mark.asyncio
    async def test_send_message_injects_and_get_messages_reports_status(self) -> None:
        caller = _mk_agent("caller")
        worker = _mk_agent("worker")
        runtime = _mk_runtime(caller, worker)

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_executor(
            agent: Agent, message: str, history: list[Message] | None
        ) -> str:
            started.set()
            await release.wait()
            return "done"

        bg_loop = BackgroundAgentLoop(
            agent=worker,
            initial_message="initial",
            executor=slow_executor,
            task_id="bg_manual",
        )
        AgentLoopRegistry.get_instance().register("bg_manual", bg_loop)
        bg_loop.start()
        await asyncio.wait_for(started.wait(), timeout=1)

        send_result = await runtime._execute_tool_call(
            ToolCall(
                id="tc_send",
                name="send_message",
                arguments={"task_id": "bg_manual", "message": "extra input"},
            ),
            caller_name="caller",
            caller_call_id="cid_parent",
        )
        assert send_result == "Message sent to worker (task_id: bg_manual)"

        get_result = await runtime._execute_tool_call(
            ToolCall(
                id="tc_get",
                name="get_messages",
                arguments={"task_id": "bg_manual"},
            ),
            caller_name="caller",
            caller_call_id="cid_parent",
        )
        assert isinstance(get_result, str)
        assert "Task ID: bg_manual" in get_result
        assert "Agent: worker" in get_result
        assert "Status: running" in get_result
        assert "extra input" in get_result

        release.set()
        assert await bg_loop.get_result() == "done"
