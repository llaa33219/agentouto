from __future__ import annotations

import pytest

from agnetouto.agent import Agent
from agnetouto.context import Context, ContextMessage, ToolCall
from agnetouto.message import Message
from agnetouto.provider import Provider
from agnetouto.tool import Tool


# --- Message ---


class TestMessage:
    def test_forward_message(self) -> None:
        msg = Message(type="forward", sender="user", receiver="agent_a", content="hello")
        assert msg.type == "forward"
        assert msg.sender == "user"
        assert msg.receiver == "agent_a"
        assert msg.content == "hello"
        assert len(msg.call_id) > 0

    def test_return_message(self) -> None:
        msg = Message(type="return", sender="agent_a", receiver="user", content="done")
        assert msg.type == "return"

    def test_auto_call_id_unique(self) -> None:
        m1 = Message(type="forward", sender="a", receiver="b", content="x")
        m2 = Message(type="forward", sender="a", receiver="b", content="x")
        assert m1.call_id != m2.call_id

    def test_custom_call_id(self) -> None:
        msg = Message(type="forward", sender="a", receiver="b", content="x", call_id="abc123")
        assert msg.call_id == "abc123"


# --- Agent ---


class TestAgent:
    def test_defaults(self) -> None:
        a = Agent(name="test", instructions="do stuff", model="gpt-4o", provider="openai")
        assert a.name == "test"
        assert a.instructions == "do stuff"
        assert a.model == "gpt-4o"
        assert a.provider == "openai"
        assert a.max_output_tokens == 4096
        assert a.reasoning is False
        assert a.reasoning_effort == "medium"
        assert a.reasoning_budget is None
        assert a.temperature == 1.0
        assert a.extra == {}

    def test_custom_values(self) -> None:
        a = Agent(
            name="thinker",
            instructions="think hard",
            model="claude-opus-4-6",
            provider="anthropic",
            max_output_tokens=16384,
            reasoning=True,
            reasoning_effort="high",
            reasoning_budget=10240,
            temperature=0.5,
            extra={"top_p": 0.9},
        )
        assert a.max_output_tokens == 16384
        assert a.reasoning is True
        assert a.reasoning_budget == 10240
        assert a.extra == {"top_p": 0.9}


# --- Provider ---


class TestProvider:
    def test_basic(self) -> None:
        p = Provider(name="openai", kind="openai", api_key="sk-test")
        assert p.name == "openai"
        assert p.kind == "openai"
        assert p.api_key == "sk-test"
        assert p.base_url is None

    def test_with_base_url(self) -> None:
        p = Provider(
            name="local", kind="openai", api_key="none",
            base_url="http://localhost:11434/v1",
        )
        assert p.base_url == "http://localhost:11434/v1"


# --- Tool ---


class TestTool:
    def test_basic_function(self) -> None:
        @Tool
        def greet(name: str) -> str:
            """Say hello."""
            return f"Hello, {name}!"

        assert greet.name == "greet"
        assert greet.description == "Say hello."
        assert greet.parameters["type"] == "object"
        assert "name" in greet.parameters["properties"]
        assert greet.parameters["properties"]["name"]["type"] == "string"
        assert greet.parameters["required"] == ["name"]

    def test_multiple_param_types(self) -> None:
        @Tool
        def compute(text: str, count: int, rate: float, verbose: bool) -> str:
            """Compute something."""
            return "done"

        props = compute.parameters["properties"]
        assert props["text"]["type"] == "string"
        assert props["count"]["type"] == "integer"
        assert props["rate"]["type"] == "number"
        assert props["verbose"]["type"] == "boolean"
        assert set(compute.parameters["required"]) == {"text", "count", "rate", "verbose"}

    def test_optional_params(self) -> None:
        @Tool
        def search(query: str, limit: int = 10) -> str:
            """Search."""
            return query

        assert search.parameters["required"] == ["query"]

    def test_no_docstring(self) -> None:
        @Tool
        def bare(x: str) -> str:
            return x

        assert bare.description == ""

    def test_to_schema(self) -> None:
        @Tool
        def my_tool(a: str) -> str:
            """Does things."""
            return a

        schema = my_tool.to_schema()
        assert schema["name"] == "my_tool"
        assert schema["description"] == "Does things."
        assert schema["parameters"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_execute_sync(self) -> None:
        @Tool
        def add(a: int, b: int) -> str:
            return str(int(a) + int(b))

        result = await add.execute(a=3, b=4)
        assert result == "7"

    @pytest.mark.asyncio
    async def test_execute_async(self) -> None:
        @Tool
        async def async_greet(name: str) -> str:
            return f"Hi {name}"

        result = await async_greet.execute(name="World")
        assert result == "Hi World"


# --- Context ---


class TestContext:
    def test_initial_state(self) -> None:
        ctx = Context("You are a helper.")
        assert ctx.system_prompt == "You are a helper."
        assert ctx.messages == []

    def test_add_user(self) -> None:
        ctx = Context("sys")
        ctx.add_user("hello")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "user"
        assert ctx.messages[0].content == "hello"

    def test_add_assistant_text(self) -> None:
        ctx = Context("sys")
        ctx.add_assistant_text("response")
        assert ctx.messages[0].role == "assistant"
        assert ctx.messages[0].content == "response"

    def test_add_assistant_tool_calls(self) -> None:
        ctx = Context("sys")
        tc = ToolCall(id="tc1", name="search", arguments={"q": "test"})
        ctx.add_assistant_tool_calls([tc], content="thinking...")
        msg = ctx.messages[0]
        assert msg.role == "assistant"
        assert msg.content == "thinking..."
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"

    def test_add_tool_result(self) -> None:
        ctx = Context("sys")
        ctx.add_tool_result("tc1", "search", "found it")
        msg = ctx.messages[0]
        assert msg.role == "tool"
        assert msg.content == "found it"
        assert msg.tool_call_id == "tc1"
        assert msg.tool_name == "search"

    def test_messages_returns_copy(self) -> None:
        ctx = Context("sys")
        ctx.add_user("hello")
        msgs = ctx.messages
        msgs.append(ContextMessage(role="user", content="extra"))
        assert len(ctx.messages) == 1
