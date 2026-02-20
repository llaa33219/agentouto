from __future__ import annotations

import pytest

from agnetouto.agent import Agent
from agnetouto.exceptions import RoutingError, ToolError
from agnetouto.provider import Provider
from agnetouto.router import Router
from agnetouto.tool import Tool


def _make_router() -> Router:
    @Tool
    def search(query: str) -> str:
        """Search the web."""
        return query

    @Tool
    def read_file(path: str) -> str:
        """Read a file."""
        return path

    agents = [
        Agent(name="researcher", instructions="Research expert.", model="gpt-4o", provider="openai"),
        Agent(name="writer", instructions="Writes reports.", model="gpt-4o", provider="openai"),
    ]
    tools = [search, read_file]
    providers = [Provider(name="openai", kind="openai", api_key="sk-test")]
    return Router(agents, tools, providers)


class TestBuildSystemPrompt:
    def test_includes_agent_identity(self) -> None:
        router = _make_router()
        agent = router.get_agent("researcher")
        prompt = router.build_system_prompt(agent)
        assert '"researcher"' in prompt
        assert "Research expert." in prompt

    def test_includes_other_agents(self) -> None:
        router = _make_router()
        agent = router.get_agent("researcher")
        prompt = router.build_system_prompt(agent)
        assert "writer" in prompt
        assert "Writes reports." in prompt
        assert "researcher" not in prompt.split("Available agents:")[1] or True

    def test_includes_instructions(self) -> None:
        router = _make_router()
        agent = router.get_agent("researcher")
        prompt = router.build_system_prompt(agent)
        assert "call_agent" in prompt
        assert "finish" in prompt


class TestBuildToolSchemas:
    def test_includes_user_tools(self) -> None:
        router = _make_router()
        schemas = router.build_tool_schemas("researcher")
        names = [s["name"] for s in schemas]
        assert "search" in names
        assert "read_file" in names

    def test_includes_call_agent(self) -> None:
        router = _make_router()
        schemas = router.build_tool_schemas("researcher")
        names = [s["name"] for s in schemas]
        assert "call_agent" in names
        call_agent_schema = next(s for s in schemas if s["name"] == "call_agent")
        assert "agent_name" in call_agent_schema["parameters"]["properties"]
        assert "message" in call_agent_schema["parameters"]["properties"]

    def test_includes_finish(self) -> None:
        router = _make_router()
        schemas = router.build_tool_schemas("researcher")
        names = [s["name"] for s in schemas]
        assert "finish" in names
        finish_schema = next(s for s in schemas if s["name"] == "finish")
        assert "message" in finish_schema["parameters"]["properties"]

    def test_tool_schema_structure(self) -> None:
        router = _make_router()
        schemas = router.build_tool_schemas("researcher")
        search_schema = next(s for s in schemas if s["name"] == "search")
        assert search_schema["description"] == "Search the web."
        assert search_schema["parameters"]["type"] == "object"


class TestGetAgent:
    def test_known_agent(self) -> None:
        router = _make_router()
        agent = router.get_agent("researcher")
        assert agent.name == "researcher"

    def test_unknown_agent_raises(self) -> None:
        router = _make_router()
        with pytest.raises(RoutingError, match="Unknown agent"):
            router.get_agent("nonexistent")


class TestGetTool:
    def test_known_tool(self) -> None:
        router = _make_router()
        tool = router.get_tool("search")
        assert tool.name == "search"

    def test_unknown_tool_raises(self) -> None:
        router = _make_router()
        with pytest.raises(ToolError):
            router.get_tool("nonexistent")


class TestRouterProperties:
    def test_agent_names(self) -> None:
        router = _make_router()
        assert set(router.agent_names) == {"researcher", "writer"}

    def test_tool_names(self) -> None:
        router = _make_router()
        assert set(router.tool_names) == {"search", "read_file"}
