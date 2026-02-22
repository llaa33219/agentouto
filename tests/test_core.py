from __future__ import annotations

import pytest

from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ContextMessage, ToolCall
from agentouto.message import Message
from agentouto.provider import Provider
from agentouto.tool import Tool, ToolResult


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

    @pytest.mark.asyncio
    async def test_execute_returns_tool_result(self) -> None:
        @Tool
        def fetch_image(url: str) -> ToolResult:
            return ToolResult(
                content="fetched image",
                attachments=[Attachment(mime_type="image/png", data="imgdata")],
            )

        result = await fetch_image.execute(url="https://example.com/img.png")
        assert isinstance(result, ToolResult)
        assert result.content == "fetched image"
        assert result.attachments is not None
        assert len(result.attachments) == 1
        assert result.attachments[0].mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_execute_returns_str_backward_compat(self) -> None:
        @Tool
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        result = await greet.execute(name="World")
        assert isinstance(result, str)
        assert result == "Hello, World!"


# --- Attachment ---


class TestAttachment:
    def test_data_attachment(self) -> None:
        att = Attachment(mime_type="image/png", data="base64data")
        assert att.mime_type == "image/png"
        assert att.data == "base64data"
        assert att.url is None
        assert att.name is None

    def test_url_attachment(self) -> None:
        att = Attachment(mime_type="image/jpeg", url="https://example.com/img.jpg", name="photo.jpg")
        assert att.mime_type == "image/jpeg"
        assert att.data is None
        assert att.url == "https://example.com/img.jpg"
        assert att.name == "photo.jpg"

    def test_defaults(self) -> None:
        att = Attachment(mime_type="audio/mp3")
        assert att.mime_type == "audio/mp3"
        assert att.data is None
        assert att.url is None
        assert att.name is None


# --- ToolResult ---


class TestToolResult:
    def test_basic(self) -> None:
        att = Attachment(mime_type="image/png", data="imgdata")
        tr = ToolResult(content="got image", attachments=[att])
        assert tr.content == "got image"
        assert tr.attachments is not None
        assert len(tr.attachments) == 1
        assert tr.attachments[0].mime_type == "image/png"

    def test_defaults(self) -> None:
        tr = ToolResult(content="text only")
        assert tr.content == "text only"
        assert tr.attachments is None


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

    def test_add_user_with_attachments(self) -> None:
        ctx = Context("sys")
        att = Attachment(mime_type="image/png", data="base64data")
        ctx.add_user("analyze this", attachments=[att])
        msg = ctx.messages[0]
        assert msg.role == "user"
        assert msg.content == "analyze this"
        assert msg.attachments is not None
        assert len(msg.attachments) == 1
        assert msg.attachments[0].mime_type == "image/png"
        assert msg.attachments[0].data == "base64data"

    def test_add_user_without_attachments_backward_compat(self) -> None:
        ctx = Context("sys")
        ctx.add_user("hello")
        msg = ctx.messages[0]
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.attachments is None

    def test_add_tool_result_with_attachments(self) -> None:
        ctx = Context("sys")
        att = Attachment(mime_type="image/jpeg", url="https://example.com/img.jpg")
        ctx.add_tool_result("tc1", "fetch_image", "fetched", attachments=[att])
        msg = ctx.messages[0]
        assert msg.role == "tool"
        assert msg.content == "fetched"
        assert msg.tool_call_id == "tc1"
        assert msg.tool_name == "fetch_image"
        assert msg.attachments is not None
        assert len(msg.attachments) == 1
        assert msg.attachments[0].url == "https://example.com/img.jpg"

    def test_messages_returns_copy(self) -> None:
        ctx = Context("sys")
        ctx.add_user("hello")
        msgs = ctx.messages
        msgs.append(ContextMessage(role="user", content="extra"))
        assert len(ctx.messages) == 1
