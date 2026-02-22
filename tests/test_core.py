from __future__ import annotations

import enum
from typing import Annotated, Literal

import pytest

from agentouto.agent import Agent
from agentouto.context import Attachment, Context, ContextMessage, ToolCall
from agentouto.message import Message
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, _content_outside_reasoning
from agentouto.providers.anthropic import _parse_max_tokens_from_error
from agentouto.providers.openai import _parse_tool_arguments
from agentouto.tool import Tool, ToolResult


class _Color(enum.Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class _Priority(enum.Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


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
        assert a.max_output_tokens is None
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

    def test_annotated_description(self) -> None:
        @Tool
        def search(query: Annotated[str, "The search keyword or query"]) -> str:
            """Search the web."""
            return query

        props = search.parameters["properties"]
        assert props["query"]["type"] == "string"
        assert props["query"]["description"] == "The search keyword or query"
        assert search.parameters["required"] == ["query"]

    def test_annotated_multiple_params(self) -> None:
        @Tool
        def search(
            query: Annotated[str, "Search keywords"],
            max_results: Annotated[int, "Maximum number of results"] = 10,
        ) -> str:
            """Search."""
            return query

        props = search.parameters["properties"]
        assert props["query"]["type"] == "string"
        assert props["query"]["description"] == "Search keywords"
        assert props["max_results"]["type"] == "integer"
        assert props["max_results"]["description"] == "Maximum number of results"
        assert props["max_results"]["default"] == 10
        assert search.parameters["required"] == ["query"]

    def test_literal_string_values(self) -> None:
        @Tool
        def set_mode(mode: Literal["fast", "balanced", "thorough"]) -> str:
            """Set processing mode."""
            return mode

        props = set_mode.parameters["properties"]
        assert props["mode"]["type"] == "string"
        assert props["mode"]["enum"] == ["fast", "balanced", "thorough"]
        assert set_mode.parameters["required"] == ["mode"]

    def test_literal_int_values(self) -> None:
        @Tool
        def set_level(level: Literal[1, 2, 3]) -> str:
            """Set level."""
            return str(level)

        props = set_level.parameters["properties"]
        assert props["level"]["type"] == "integer"
        assert props["level"]["enum"] == [1, 2, 3]

    def test_enum_string_values(self) -> None:
        @Tool
        def paint(color: _Color) -> str:
            """Paint with a color."""
            return color.value

        props = paint.parameters["properties"]
        assert props["color"]["type"] == "string"
        assert props["color"]["enum"] == ["red", "green", "blue"]
        assert paint.parameters["required"] == ["color"]

    def test_enum_int_values(self) -> None:
        @Tool
        def set_priority(priority: _Priority) -> str:
            """Set priority."""
            return str(priority.value)

        props = set_priority.parameters["properties"]
        assert props["priority"]["type"] == "integer"
        assert props["priority"]["enum"] == [1, 2, 3]

    def test_default_value_in_schema(self) -> None:
        @Tool
        def search(query: str, limit: int = 10, verbose: bool = False) -> str:
            """Search."""
            return query

        props = search.parameters["properties"]
        assert "default" not in props["query"]
        assert props["limit"]["default"] == 10
        assert props["verbose"]["default"] is False
        assert search.parameters["required"] == ["query"]

    def test_enum_default_value(self) -> None:
        @Tool
        def paint(color: _Color = _Color.RED) -> str:
            """Paint."""
            return color.value

        props = paint.parameters["properties"]
        assert props["color"]["default"] == "red"
        assert "required" not in paint.parameters

    def test_annotated_with_literal(self) -> None:
        @Tool
        def configure(
            mode: Annotated[Literal["fast", "slow"], "Processing speed mode"],
        ) -> str:
            """Configure."""
            return mode

        props = configure.parameters["properties"]
        assert props["mode"]["type"] == "string"
        assert props["mode"]["enum"] == ["fast", "slow"]
        assert props["mode"]["description"] == "Processing speed mode"

    def test_annotated_with_enum(self) -> None:
        @Tool
        def paint(color: Annotated[_Color, "Pick a color"]) -> str:
            """Paint."""
            return color.value

        props = paint.parameters["properties"]
        assert props["color"]["type"] == "string"
        assert props["color"]["enum"] == ["red", "green", "blue"]
        assert props["color"]["description"] == "Pick a color"

    def test_annotated_non_string_metadata_ignored(self) -> None:
        @Tool
        def process(value: Annotated[str, 42, True]) -> str:
            """Process."""
            return value

        props = process.parameters["properties"]
        assert props["value"]["type"] == "string"
        assert "description" not in props["value"]

    def test_annotated_with_default(self) -> None:
        @Tool
        def fetch(
            url: Annotated[str, "The URL to fetch"],
            timeout: Annotated[int, "Timeout in seconds"] = 30,
        ) -> str:
            """Fetch a URL."""
            return url

        props = fetch.parameters["properties"]
        assert props["url"]["description"] == "The URL to fetch"
        assert "default" not in props["url"]
        assert props["timeout"]["description"] == "Timeout in seconds"
        assert props["timeout"]["default"] == 30
        assert fetch.parameters["required"] == ["url"]

    def test_combined_rich_schema(self) -> None:
        @Tool
        def search_web(
            query: Annotated[str, "Search keywords"],
            max_results: Annotated[int, "Max results to return"] = 10,
            language: Literal["ko", "en", "ja"] = "ko",
        ) -> str:
            """Search the web for information."""
            return query

        schema = search_web.to_schema()
        assert schema["name"] == "search_web"
        assert schema["description"] == "Search the web for information."

        props = schema["parameters"]["properties"]
        assert props["query"] == {"type": "string", "description": "Search keywords"}
        assert props["max_results"] == {
            "type": "integer",
            "description": "Max results to return",
            "default": 10,
        }
        assert props["language"] == {
            "type": "string",
            "enum": ["ko", "en", "ja"],
            "default": "ko",
        }
        assert schema["parameters"]["required"] == ["query"]

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


# --- Reasoning Tag Handling ---


class TestContentOutsideReasoning:
    """Tests for _content_outside_reasoning (provider-level utility)."""

    def test_think_tag(self) -> None:
        assert _content_outside_reasoning("<think>reasoning</think>answer") == "answer"

    def test_thinking_tag(self) -> None:
        assert _content_outside_reasoning("<thinking>reasoning</thinking>answer") == "answer"

    def test_reason_tag(self) -> None:
        assert _content_outside_reasoning("<reason>reasoning</reason>answer") == "answer"

    def test_reasoning_tag(self) -> None:
        assert _content_outside_reasoning("<reasoning>reasoning</reasoning>answer") == "answer"

    def test_multiline(self) -> None:
        content = "<think>\nI need to call search(query='test')\nLet me think...\n</think>\nThe answer is 42."
        assert _content_outside_reasoning(content) == "The answer is 42."

    def test_unclosed_tag(self) -> None:
        assert _content_outside_reasoning("<think>reasoning without closing tag") == ""

    def test_multiple_tags(self) -> None:
        content = "<think>first</think> middle <think>second</think> end"
        assert _content_outside_reasoning(content) == "middle  end"

    def test_no_tags(self) -> None:
        assert _content_outside_reasoning("plain text") == "plain text"

    def test_empty_string(self) -> None:
        assert _content_outside_reasoning("") == ""

    def test_tool_call_inside_think(self) -> None:
        content = '<think>I should call search_web(query="AI") to find info</think>Here is my response.'
        assert _content_outside_reasoning(content) == "Here is my response."

    def test_only_reasoning(self) -> None:
        assert _content_outside_reasoning("<think>all reasoning, no answer</think>") == ""

    def test_mismatched_tags_stripped_to_end(self) -> None:
        assert _content_outside_reasoning("<think>content</reasoning>") == ""

    def test_text_surrounding_tag(self) -> None:
        assert _content_outside_reasoning("Before<think>middle</think>after") == "Beforeafter"


class TestContextReasoningPreservation:
    """Context stores original content including reasoning tags."""

    def test_add_assistant_text_preserves_tags(self) -> None:
        ctx = Context("sys")
        ctx.add_assistant_text("<think>reasoning</think>The answer is 42.")
        assert ctx.messages[0].content == "<think>reasoning</think>The answer is 42."

    def test_add_assistant_text_no_tags(self) -> None:
        ctx = Context("sys")
        ctx.add_assistant_text("plain response")
        assert ctx.messages[0].content == "plain response"

    def test_add_assistant_text_only_reasoning_preserved(self) -> None:
        ctx = Context("sys")
        ctx.add_assistant_text("<think>only reasoning</think>")
        assert ctx.messages[0].content == "<think>only reasoning</think>"

    def test_add_assistant_tool_calls_preserves_tags(self) -> None:
        ctx = Context("sys")
        tc = ToolCall(id="tc1", name="search", arguments={"q": "test"})
        ctx.add_assistant_tool_calls([tc], content="<think>let me search</think>Searching now.")
        msg = ctx.messages[0]
        assert msg.content == "<think>let me search</think>Searching now."
        assert msg.tool_calls is not None

    def test_add_assistant_tool_calls_only_reasoning_preserved(self) -> None:
        ctx = Context("sys")
        tc = ToolCall(id="tc1", name="search", arguments={"q": "test"})
        ctx.add_assistant_tool_calls([tc], content="<think>only reasoning</think>")
        msg = ctx.messages[0]
        assert msg.content == "<think>only reasoning</think>"
        assert msg.tool_calls is not None

    def test_add_assistant_tool_calls_none_content(self) -> None:
        ctx = Context("sys")
        tc = ToolCall(id="tc1", name="search", arguments={"q": "test"})
        ctx.add_assistant_tool_calls([tc], content=None)
        msg = ctx.messages[0]
        assert msg.content is None


class TestLLMResponseContentWithoutReasoning:
    """LLMResponse.content_without_reasoning strips reasoning tags."""

    def test_with_reasoning(self) -> None:
        resp = LLMResponse(content="<think>deep thought</think>The answer is 42.")
        assert resp.content_without_reasoning == "The answer is 42."
        assert resp.content == "<think>deep thought</think>The answer is 42."

    def test_tool_calls_preserved_with_reasoning_content(self) -> None:
        tc = ToolCall(id="1", name="search", arguments={"q": "test"})
        resp = LLMResponse(
            content="<think>I should call search</think>Here is my answer.",
            tool_calls=[tc],
        )
        assert resp.tool_calls == [tc]
        assert resp.content == "<think>I should call search</think>Here is my answer."
        assert resp.content_without_reasoning == "Here is my answer."

    def test_none_content(self) -> None:
        resp = LLMResponse(content=None)
        assert resp.content_without_reasoning is None

    def test_no_tags(self) -> None:
        resp = LLMResponse(content="plain response")
        assert resp.content_without_reasoning == "plain response"

    def test_only_reasoning_returns_none(self) -> None:
        resp = LLMResponse(content="<think>all reasoning</think>")
        assert resp.content_without_reasoning is None


# --- Tool Argument Parsing ---


class TestParseToolArguments:
    def test_valid_json_object(self) -> None:
        assert _parse_tool_arguments('{"query": "AI"}') == {"query": "AI"}

    def test_valid_nested_object(self) -> None:
        raw = '{"query": "AI", "options": {"limit": 10}}'
        assert _parse_tool_arguments(raw) == {"query": "AI", "options": {"limit": 10}}

    def test_none_returns_empty(self) -> None:
        assert _parse_tool_arguments(None) == {}

    def test_empty_string_returns_empty(self) -> None:
        assert _parse_tool_arguments("") == {}

    def test_whitespace_only_returns_empty(self) -> None:
        assert _parse_tool_arguments("   \n\t  ") == {}

    def test_markdown_code_fence_json(self) -> None:
        raw = '```json\n{"query": "test"}\n```'
        assert _parse_tool_arguments(raw) == {"query": "test"}

    def test_markdown_code_fence_plain(self) -> None:
        raw = '```\n{"query": "test"}\n```'
        assert _parse_tool_arguments(raw) == {"query": "test"}

    def test_markdown_fence_with_extra_whitespace(self) -> None:
        raw = '```json\n  {"query": "test"}  \n```'
        assert _parse_tool_arguments(raw) == {"query": "test"}

    def test_markdown_fence_empty_body(self) -> None:
        assert _parse_tool_arguments('```json\n\n```') == {}

    def test_number_string_returns_empty(self) -> None:
        assert _parse_tool_arguments("42") == {}

    def test_json_array_returns_empty(self) -> None:
        assert _parse_tool_arguments('["a", "b"]') == {}

    def test_json_string_returns_empty(self) -> None:
        assert _parse_tool_arguments('"just a string"') == {}

    def test_json_boolean_returns_empty(self) -> None:
        assert _parse_tool_arguments("true") == {}

    def test_json_null_returns_empty(self) -> None:
        assert _parse_tool_arguments("null") == {}

    def test_malformed_json_returns_empty(self) -> None:
        assert _parse_tool_arguments('{"query": "test",}') == {}

    def test_truncated_json_repaired(self) -> None:
        assert _parse_tool_arguments('{"query": "te') == {"query": "te"}

    def test_plain_text_returns_empty(self) -> None:
        assert _parse_tool_arguments("not json at all") == {}

    def test_surrounding_whitespace_stripped(self) -> None:
        assert _parse_tool_arguments('  {"key": "val"}  ') == {"key": "val"}

    def test_no_raw_key_in_result(self) -> None:
        result = _parse_tool_arguments("invalid json!!!")
        assert "raw" not in result

    def test_incomplete_json_missing_brace(self) -> None:
        assert _parse_tool_arguments('{"query": "test"') == {"query": "test"}

    def test_incomplete_json_nested(self) -> None:
        raw = '{"query": "AI", "options": {"limit": 10}'
        assert _parse_tool_arguments(raw) == {"query": "AI", "options": {"limit": 10}}

    def test_incomplete_json_with_array(self) -> None:
        raw = '{"tags": ["a", "b"'
        assert _parse_tool_arguments(raw) == {"tags": ["a", "b"]}

    def test_incomplete_json_truncated_string(self) -> None:
        raw = '{"query": "hello wor'
        result = _parse_tool_arguments(raw)
        assert result.get("query", "").startswith("hello wor")

    def test_incomplete_json_completely_broken(self) -> None:
        assert _parse_tool_arguments('{"query":') == {}


# --- Anthropic Max Tokens Discovery ---


class TestParseMaxTokensFromError:
    def test_standard_format(self) -> None:
        msg = "max_tokens: 999999 > 64000, which is the maximum allowed number of output tokens for claude-sonnet-4-5-20250929"
        assert _parse_max_tokens_from_error(msg) == 64000

    def test_opus_format(self) -> None:
        msg = "max_tokens: 21333 > 4096, which is the maximum allowed number of output tokens for claude-3-opus-20240229"
        assert _parse_max_tokens_from_error(msg) == 4096

    def test_fallback_regex(self) -> None:
        msg = "Your requested 'max_tokens' value is too large. The maximum value for model 'claude-3-5-sonnet-20240620' is 8192."
        assert _parse_max_tokens_from_error(msg) == 8192

    def test_no_match(self) -> None:
        msg = "Connection refused"
        assert _parse_max_tokens_from_error(msg) is None

    def test_empty_string(self) -> None:
        assert _parse_max_tokens_from_error("") is None

    def test_wrapped_error_json(self) -> None:
        msg = '{"type":"error","error":{"type":"invalid_request_error","message":"max_tokens: 999999 > 16384, which is the maximum allowed number of output tokens for claude-3-haiku-20240307"}}'
        assert _parse_max_tokens_from_error(msg) == 16384


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
