from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ToolCall
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend
from agentouto.runtime import RunResult, async_run
from agentouto.tool import Tool, ToolResult


class MockBackend(ProviderBackend):
    """Returns pre-configured LLMResponse objects in order."""

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
        tool_calls=[ToolCall(id="fin_1", name="finish", arguments={"message": message})],
    )


def _text(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[])


def _tool_call(tool_name: str, tool_id: str, **kwargs: str) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=dict(kwargs))],
    )


def _call_agent(agent_name: str, message: str) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCall(
                id="ca_1",
                name="call_agent",
                arguments={"agent_name": agent_name, "message": message},
            )
        ],
    )


def _multi_tool_calls(*calls: tuple[str, str, dict[str, str]]) -> LLMResponse:
    tool_calls = [
        ToolCall(id=tc_id, name=name, arguments=args)
        for name, tc_id, args in calls
    ]
    return LLMResponse(content=None, tool_calls=tool_calls)


# --- Fixtures ---


@pytest.fixture
def provider() -> Provider:
    return Provider(name="openai", kind="openai", api_key="sk-test")


@pytest.fixture
def agent_a() -> Agent:
    return Agent(name="agent_a", instructions="Agent A.", model="gpt-4o", provider="openai")


@pytest.fixture
def agent_b() -> Agent:
    return Agent(name="agent_b", instructions="Agent B.", model="gpt-4o", provider="openai")


@pytest.fixture
def search_tool() -> Tool:
    @Tool
    def search(query: str) -> str:
        """Search the web."""
        return f"Results for: {query}"
    return search


@pytest.fixture
def upper_tool() -> Tool:
    @Tool
    def uppercase(text: str) -> str:
        """Convert to uppercase."""
        return text.upper()
    return uppercase


# --- Tests ---


class TestSingleAgentTextResponse:
    @pytest.mark.asyncio
    async def test_text_response_triggers_nudge_then_finish(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        """Text-only response nudges the LLM; finish on retry is accepted."""
        mock = MockBackend([
            _text("Hello from LLM"),
            _finish("Hello from LLM"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Say hello",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "Hello from LLM"
        assert mock._call_count == 2


class TestSingleAgentFinish:
    @pytest.mark.asyncio
    async def test_llm_calls_finish(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("Final answer")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Give me the answer",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "Final answer"


class TestSingleAgentToolCall:
    @pytest.mark.asyncio
    async def test_tool_call_then_finish(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([
            _tool_call("search", "tc1", query="AI trends"),
            _finish("Based on search: AI is trending"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Search for AI trends",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "Based on search: AI is trending"
        assert mock._call_count == 2


class TestMultiAgent:
    @pytest.mark.asyncio
    async def test_agent_calls_agent(
        self,
        agent_a: Agent,
        agent_b: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([
            _call_agent("agent_b", "Please help me"),
            _finish("I helped you"),
            _finish("Done with help from B"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Do something complex",
                agents=[agent_a, agent_b],
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "Done with help from B"
        assert mock._call_count == 3


class TestDebugMode:
    @pytest.mark.asyncio
    async def test_debug_populates_messages(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("debug result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Test debug",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
                debug=True,
            )
        assert result.output == "debug result"
        assert len(result.messages) >= 2
        forward_msgs = [m for m in result.messages if m.type == "forward"]
        return_msgs = [m for m in result.messages if m.type == "return"]
        assert len(forward_msgs) >= 1
        assert len(return_msgs) >= 1
        assert forward_msgs[0].sender == "user"
        assert forward_msgs[0].receiver == "agent_a"
        assert return_msgs[-1].sender == "agent_a"
        assert return_msgs[-1].receiver == "user"

    @pytest.mark.asyncio
    async def test_debug_populates_event_log(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Test",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
                debug=True,
            )
        assert result.event_log is not None
        assert len(result.event_log) > 0
        event_types = [e.event_type for e in result.event_log]
        assert "agent_call" in event_types
        assert "llm_call" in event_types

    @pytest.mark.asyncio
    async def test_debug_populates_trace(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("traced")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Trace me",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
                debug=True,
            )
        assert result.trace is not None
        assert result.trace.root is not None
        assert result.trace.root.agent_name == "agent_a"

    @pytest.mark.asyncio
    async def test_format_trace(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("traced")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Trace me",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
                debug=True,
            )
        tree = result.format_trace()
        assert "agent_a" in tree

    @pytest.mark.asyncio
    async def test_format_trace_without_debug(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("no debug")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="No debug",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert "no trace" in result.format_trace()


class TestDebugMultiAgent:
    @pytest.mark.asyncio
    async def test_multi_agent_messages(
        self,
        agent_a: Agent,
        agent_b: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([
            _call_agent("agent_b", "Help"),
            _finish("Helped"),
            _finish("All done"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Start",
                agents=[agent_a, agent_b],
                tools=[search_tool],
                providers=[provider],
                debug=True,
            )
        assert result.output == "All done"
        assert result.event_log is not None
        agent_calls = result.event_log.filter(event_type="agent_call")
        assert len(agent_calls) >= 2
        assert result.trace is not None
        assert len(result.trace.root.children) >= 1


class TestParallelToolCalls:
    @pytest.mark.asyncio
    async def test_multiple_tools_in_one_response(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
        upper_tool: Tool,
    ) -> None:
        mock = MockBackend([
            _multi_tool_calls(
                ("search", "tc1", {"query": "hello"}),
                ("uppercase", "tc2", {"text": "world"}),
            ),
            _finish("Got both results"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Do two things",
                agents=[agent_a],
                tools=[search_tool, upper_tool],
                providers=[provider],
            )
        assert result.output == "Got both results"
        assert mock._call_count == 2


class TestAttachmentsPassthrough:
    @pytest.mark.asyncio
    async def test_attachments_passed_to_context(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("analyzed")])
        att = Attachment(mime_type="image/png", data="base64data")
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Analyze this image",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
                attachments=[att],
            )
        assert result.output == "analyzed"
        forward_msgs = [m for m in result.messages if m.type == "forward"]
        assert len(forward_msgs) == 1
        assert forward_msgs[0].attachments is not None
        assert len(forward_msgs[0].attachments) == 1
        assert forward_msgs[0].attachments[0].mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_tool_result_with_attachments(
        self, agent_a: Agent, provider: Provider,
    ) -> None:
        @Tool
        def fetch_image(url: str) -> ToolResult:
            """Fetch an image."""
            return ToolResult(
                content="fetched",
                attachments=[Attachment(mime_type="image/png", data="imgdata")],
            )

        mock = MockBackend([
            _tool_call("fetch_image", "tc1", url="https://example.com/img.png"),
            _finish("Image shows a cat"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Fetch and analyze the image",
                agents=[agent_a],
                tools=[fetch_image],
                providers=[provider],
            )
        assert result.output == "Image shows a cat"
        assert mock._call_count == 2

    @pytest.mark.asyncio
    async def test_no_attachments_backward_compat(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Hello",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "result"
        forward_msgs = [m for m in result.messages if m.type == "forward"]
        assert forward_msgs[0].attachments is None


class TestFinishNudge:
    @pytest.mark.asyncio
    async def test_multiple_nudges_until_finish(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        """Agent is nudged repeatedly until it uses finish()."""
        mock = MockBackend([
            _text("thinking..."),
            _text("still thinking..."),
            _text("almost done..."),
            _finish("done"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Hello",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "done"
        assert mock._call_count == 4

    @pytest.mark.asyncio
    async def test_nudge_message_added_to_context(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        """Nudge adds assistant text + user nudge message to context."""
        from agentouto.runtime import _FINISH_NUDGE

        contexts_seen: list[Context] = []

        class CapturingBackend(ProviderBackend):
            def __init__(self) -> None:
                self._call_count = 0

            async def call(
                self,
                context: Context,
                tools: list[dict[str, Any]],
                agent: Agent,
                provider: Provider,
            ) -> LLMResponse:
                contexts_seen.append(context)
                self._call_count += 1
                if self._call_count == 1:
                    return _text("raw text")
                return _finish("proper result")

        mock = CapturingBackend()
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Hello",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "proper result"
        second_ctx = contexts_seen[1]
        msgs = second_ctx.messages
        assert msgs[-2].role == "assistant"
        assert msgs[-2].content == "raw text"
        assert msgs[-1].role == "user"
        assert _FINISH_NUDGE in (msgs[-1].content or "")


class TestFinishNudgeStreaming:
    @pytest.mark.asyncio
    async def test_stream_text_response_triggers_nudge_then_finish(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        """Streaming: text-only response nudges, finish on retry is accepted."""
        from agentouto.streaming import StreamEvent, async_run_stream

        mock = MockBackend([
            _text("intermediate"),
            _finish("final result"),
        ])
        with patch("agentouto.router.get_backend", return_value=mock):
            events: list[StreamEvent] = []
            async for event in async_run_stream(
                entry=agent_a,
                message="Hello",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            ):
                events.append(event)
        finish_events = [e for e in events if e.type == "finish"]
        assert len(finish_events) == 1
        assert finish_events[0].data["output"] == "final result"
        assert mock._call_count == 2


class TestMessagesAlwaysPopulated:
    @pytest.mark.asyncio
    async def test_messages_without_debug(
        self, agent_a: Agent, provider: Provider, search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="Hello",
                agents=[agent_a],
                tools=[search_tool],
                providers=[provider],
            )
        assert len(result.messages) >= 2
        assert result.messages[0].type == "forward"
        assert result.messages[-1].type == "return"
