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
        tool_calls=[
            ToolCall(id="fin_1", name="finish", arguments={"message": message})
        ],
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
        ToolCall(id=tc_id, name=name, arguments=args) for name, tc_id, args in calls
    ]
    return LLMResponse(content=None, tool_calls=tool_calls)


# --- Fixtures ---


@pytest.fixture
def provider() -> Provider:
    return Provider(name="openai", kind="openai", api_key="sk-test")


@pytest.fixture
def agent_a() -> Agent:
    return Agent(
        name="agent_a", instructions="Agent A.", model="gpt-4o", provider="openai"
    )


@pytest.fixture
def agent_b() -> Agent:
    return Agent(
        name="agent_b", instructions="Agent B.", model="gpt-4o", provider="openai"
    )


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
    async def test_text_response_is_final_answer(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """A text response with no tool calls IS the final answer.

        The loop ends immediately — the text becomes the run output and the
        provider is called exactly once (no nudge, no retry).
        """
        mock = MockBackend([_text("Hello from LLM")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Say hello",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "Hello from LLM"
        assert mock._call_count == 1


class TestSingleAgentFinish:
    @pytest.mark.asyncio
    async def test_llm_calls_finish(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("Final answer")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Give me the answer",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "Final answer"


class TestSingleAgentToolCall:
    @pytest.mark.asyncio
    async def test_tool_call_then_finish(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend(
            [
                _tool_call("search", "tc1", query="AI trends"),
                _finish("Based on search: AI is trending"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Search for AI trends",
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
        mock = MockBackend(
            [
                _call_agent("agent_b", "Please help me"),
                _finish("I helped you"),
                _finish("Done with help from B"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                run_agents=[agent_a, agent_b],
                message="Do something complex",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "Done with help from B"
        assert mock._call_count == 3


class TestDebugMode:
    @pytest.mark.asyncio
    async def test_debug_populates_messages(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("debug result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Test debug",
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
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Test",
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
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("traced")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Trace me",
                tools=[search_tool],
                providers=[provider],
                debug=True,
            )
        assert result.trace is not None
        assert result.trace.root is not None
        assert result.trace.root.agent_name == "agent_a"

    @pytest.mark.asyncio
    async def test_format_trace(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("traced")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Trace me",
                tools=[search_tool],
                providers=[provider],
                debug=True,
            )
        tree = result.format_trace()
        assert "agent_a" in tree

    @pytest.mark.asyncio
    async def test_format_trace_without_debug(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("no debug")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="No debug",
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
        mock = MockBackend(
            [
                _call_agent("agent_b", "Help"),
                _finish("Helped"),
                _finish("All done"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                run_agents=[agent_a, agent_b],
                message="Start",
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
        mock = MockBackend(
            [
                _multi_tool_calls(
                    ("search", "tc1", {"query": "hello"}),
                    ("uppercase", "tc2", {"text": "world"}),
                ),
                _finish("Got both results"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Do two things",
                tools=[search_tool, upper_tool],
                providers=[provider],
            )
        assert result.output == "Got both results"
        assert mock._call_count == 2


class TestAttachmentsPassthrough:
    @pytest.mark.asyncio
    async def test_attachments_passed_to_context(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("analyzed")])
        att = Attachment(mime_type="image/png", data="base64data")
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Analyze this image",
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
        self,
        agent_a: Agent,
        provider: Provider,
    ) -> None:
        @Tool
        def fetch_image(url: str) -> ToolResult:
            """Fetch an image."""
            return ToolResult(
                content="fetched",
                attachments=[Attachment(mime_type="image/png", data="imgdata")],
            )

        mock = MockBackend(
            [
                _tool_call("fetch_image", "tc1", url="https://example.com/img.png"),
                _finish("Image shows a cat"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Fetch and analyze the image",
                tools=[fetch_image],
                providers=[provider],
            )
        assert result.output == "Image shows a cat"
        assert mock._call_count == 2

    @pytest.mark.asyncio
    async def test_no_attachments_backward_compat(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Hello",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "result"
        forward_msgs = [m for m in result.messages if m.type == "forward"]
        assert forward_msgs[0].attachments is None


class TestLoopTermination:
    @pytest.mark.asyncio
    async def test_empty_text_response_continues_loop(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """Empty content with no tool calls means 'still working'.

        The empty response is not deliverable, so the loop continues and the
        next (non-empty) response terminates the run.
        """
        mock = MockBackend([_text(""), _finish("real result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Hello",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "real result"
        assert mock._call_count == 2

    @pytest.mark.asyncio
    async def test_finish_with_other_tool_calls_executes_no_tools(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """A finish call in the same batch short-circuits the other calls."""
        search_calls: list[str] = []

        @Tool
        def search(query: str) -> str:
            """Search the web."""
            search_calls.append(query)
            return f"Results for: {query}"

        mock = MockBackend(
            [
                _multi_tool_calls(
                    ("finish", "fin_1", {"message": "done"}),
                    ("search", "tc1", {"query": "should not run"}),
                )
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Hello",
                tools=[search],
                providers=[provider],
            )
        assert result.output == "done"
        assert mock._call_count == 1
        assert search_calls == []

    @pytest.mark.asyncio
    async def test_finish_override_error_returns_error_string(
        self,
        agent_a: Agent,
        provider: Provider,
    ) -> None:
        """A raising finish override is surfaced as the run output."""

        @Tool
        def finish(message: str) -> str:
            """Finish that always fails."""
            raise RuntimeError("boom")

        mock = MockBackend([_finish("x")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Do work",
                tools=[finish],
                providers=[provider],
            )
        assert result.output == "Error in finish override: boom"
        assert mock._call_count == 1


class TestFinishNudgeStreaming:
    @pytest.mark.asyncio
    async def test_stream_text_response_is_final_answer(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """Streaming: a text response emits tokens, then one finish event."""
        from agentouto.streaming import StreamEvent, async_run_stream

        mock = MockBackend([_text("final result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            events: list[StreamEvent] = []
            async for event in async_run_stream(
                starting_agents=[agent_a],
                message="Hello",
                tools=[search_tool],
                providers=[provider],
            ):
                events.append(event)
        token_events = [e for e in events if e.type == "token"]
        assert any(e.data["text"] == "final result" for e in token_events)
        finish_events = [e for e in events if e.type == "finish"]
        assert len(finish_events) == 1
        assert finish_events[0].data["output"] == "final result"
        assert mock._call_count == 1


class TestMessagesAlwaysPopulated:
    @pytest.mark.asyncio
    async def test_messages_without_debug(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend([_finish("result")])
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Hello",
                tools=[search_tool],
                providers=[provider],
            )
        assert len(result.messages) >= 2
        assert result.messages[0].type == "forward"
        assert result.messages[-1].type == "return"


class TestToolCallErrorHandling:
    """Errors from confused or invalid tool/agent calls are caught, not crashed."""

    @pytest.mark.asyncio
    async def test_unknown_tool_error_no_crash(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        mock = MockBackend(
            [
                _tool_call("nonexistent", "tc1"),
                _finish("ok"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Use nonexistent tool",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "ok"

    @pytest.mark.asyncio
    async def test_agent_as_tool_error_message(
        self,
        agent_a: Agent,
        agent_b: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """Calling an agent name as a tool gives a helpful error."""
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
                self._call_count += 1
                if self._call_count == 1:
                    return _tool_call("agent_b", "tc1")
                contexts_seen.append(context)
                return _finish("ok")

        mock = CapturingBackend()
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                run_agents=[agent_a, agent_b],
                message="Call agent_b as tool",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "ok"
        error_msg = contexts_seen[0].messages[-1].content or ""
        assert "is an agent, not a tool" in error_msg
        assert "call_agent" in error_msg

    @pytest.mark.asyncio
    async def test_tool_as_agent_error_message(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """Calling a tool name via call_agent gives a helpful error."""
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
                self._call_count += 1
                if self._call_count == 1:
                    return _call_agent("search", "find something")
                contexts_seen.append(context)
                return _finish("ok")

        mock = CapturingBackend()
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Call search as agent",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "ok"
        error_msg = contexts_seen[0].messages[-1].content or ""
        assert "is a tool, not an agent" in error_msg

    @pytest.mark.asyncio
    async def test_unknown_agent_error_message(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """Calling a completely unknown agent name gives available agents."""
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
                self._call_count += 1
                if self._call_count == 1:
                    return _call_agent("nobody", "hi")
                contexts_seen.append(context)
                return _finish("ok")

        mock = CapturingBackend()
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Call unknown agent",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "ok"
        error_msg = contexts_seen[0].messages[-1].content or ""
        assert "Unknown agent" in error_msg
        assert "Available agents" in error_msg

    @pytest.mark.asyncio
    async def test_unknown_tool_error_lists_available(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        """Calling a completely unknown tool name gives available tools."""
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
                self._call_count += 1
                if self._call_count == 1:
                    return _tool_call("nonexistent", "tc1")
                contexts_seen.append(context)
                return _finish("ok")

        mock = CapturingBackend()
        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                starting_agents=[agent_a],
                message="Use nonexistent tool",
                tools=[search_tool],
                providers=[provider],
            )
        assert result.output == "ok"
        error_msg = contexts_seen[0].messages[-1].content or ""
        assert "Unknown tool" in error_msg
        assert "Available tools" in error_msg


class TestStreamingErrorHandling:
    """Streaming path handles invalid tool/agent calls without crashing."""

    @pytest.mark.asyncio
    async def test_stream_unknown_tool_no_crash(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        from agentouto.streaming import StreamEvent, async_run_stream

        mock = MockBackend(
            [
                _tool_call("nonexistent", "tc1"),
                _finish("ok"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            events: list[StreamEvent] = []
            async for event in async_run_stream(
                starting_agents=[agent_a],
                message="Use nonexistent",
                tools=[search_tool],
                providers=[provider],
            ):
                events.append(event)
        finish_events = [e for e in events if e.type == "finish"]
        assert len(finish_events) == 1
        assert finish_events[0].data["output"] == "ok"

    @pytest.mark.asyncio
    async def test_stream_agent_as_tool_no_crash(
        self,
        agent_a: Agent,
        agent_b: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        from agentouto.streaming import StreamEvent, async_run_stream

        mock = MockBackend(
            [
                _tool_call("agent_b", "tc1"),
                _finish("ok"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            events: list[StreamEvent] = []
            async for event in async_run_stream(
                starting_agents=[agent_a, agent_b],
                message="Call agent_b as tool",
                tools=[search_tool],
                providers=[provider],
            ):
                events.append(event)
        finish_events = [e for e in events if e.type == "finish"]
        assert len(finish_events) == 1
        assert finish_events[0].data["output"] == "ok"

    @pytest.mark.asyncio
    async def test_stream_tool_as_agent_no_crash(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        from agentouto.streaming import StreamEvent, async_run_stream

        mock = MockBackend(
            [
                _call_agent("search", "find something"),
                _finish("ok"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            events: list[StreamEvent] = []
            async for event in async_run_stream(
                starting_agents=[agent_a],
                message="Call search as agent",
                tools=[search_tool],
                providers=[provider],
            ):
                events.append(event)
        finish_events = [e for e in events if e.type == "finish"]
        assert len(finish_events) == 1
        assert finish_events[0].data["output"] == "ok"

    @pytest.mark.asyncio
    async def test_stream_unknown_agent_no_crash(
        self,
        agent_a: Agent,
        provider: Provider,
        search_tool: Tool,
    ) -> None:
        from agentouto.streaming import StreamEvent, async_run_stream

        mock = MockBackend(
            [
                _call_agent("nobody", "hi"),
                _finish("ok"),
            ]
        )
        with patch("agentouto.router.get_backend", return_value=mock):
            events: list[StreamEvent] = []
            async for event in async_run_stream(
                starting_agents=[agent_a],
                message="Call unknown agent",
                tools=[search_tool],
                providers=[provider],
            ):
                events.append(event)
        finish_events = [e for e in events if e.type == "finish"]
        assert len(finish_events) == 1
        assert finish_events[0].data["output"] == "ok"
