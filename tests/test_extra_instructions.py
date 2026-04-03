"""Tests for extra_instructions injection at spawn/run time."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agentouto.agent import Agent
from agentouto.context import Context
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend
from agentouto.runtime import async_run, run, run_background, run_background_sync
from agentouto.router import Router
from agentouto.tool import Tool


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
        tool_calls=[_tool_call("finish", "fin_1", message=message)],
    )


def _call_agent(agent_name: str, message: str) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            _tool_call("call_agent", "ca_1", agent_name=agent_name, message=message)
        ],
    )


def _tool_call(tool_name: str, tool_id: str, **kwargs: str) -> Any:
    from agentouto.context import ToolCall

    return ToolCall(id=tool_id, name=tool_name, arguments=dict(kwargs))


# --- Router.build_system_prompt tests ---


class TestBuildSystemPromptWithExtraInstructions:
    """Router.build_system_prompt correctly injects extra_instructions."""

    def test_no_extra_instructions(self) -> None:
        """When extra_instructions is None, no injection appears."""
        router = _make_router()
        agent = router.get_agent("researcher")
        prompt = router.build_system_prompt(agent)
        assert "ADDITIONAL INSTRUCTIONS:" not in prompt

    def test_extra_instructions_injected(self) -> None:
        """When extra_instructions is provided, it appears in prompt."""
        router = _make_router()
        agent = router.get_agent("researcher")
        prompt = router.build_system_prompt(agent, extra_instructions="Be concise.")
        assert "ADDITIONAL INSTRUCTIONS:" in prompt
        assert "Be concise." in prompt

    def test_extra_instructions_not_required(self) -> None:
        """extra_instructions parameter is optional."""
        router = _make_router()
        agent = router.get_agent("researcher")
        # Should not raise
        prompt = router.build_system_prompt(agent)
        assert "ADDITIONAL INSTRUCTIONS:" not in prompt

    def test_extra_instructions_placed_appropriately(self) -> None:
        """extra_instructions appears after agent identity, before agent list."""
        router = _make_router()
        agent = router.get_agent("researcher")
        prompt = router.build_system_prompt(
            agent, extra_instructions="Test instruction"
        )
        lines = prompt.split("\n")
        # Find indices
        identity_idx = next(i for i, l in enumerate(lines) if '"researcher"' in l)
        additional_idx = next(
            i for i, l in enumerate(lines) if "ADDITIONAL INSTRUCTIONS:" in l
        )
        available_idx = next(i for i, l in enumerate(lines) if "Available agents:" in l)
        assert identity_idx < additional_idx < available_idx


# --- Runtime extra_instructions tests ---


class TestExtraInstructionsScopeEntry:
    """extra_instructions_scope='entry' injects only to entry agent."""

    @pytest.mark.asyncio
    async def test_entry_scope_injects_to_entry_agent(self) -> None:
        """Entry agent gets extra_instructions in its system prompt."""
        system_prompts: list[str] = []

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
                system_prompts.append(context.system_prompt)
                self._call_count += 1
                return _finish("done")

        mock = CapturingBackend()
        agent_a = _make_agent("agent_a")

        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="hello",
                agents=[agent_a],
                tools=[],
                providers=[_make_provider()],
                extra_instructions="Be polite.",
                extra_instructions_scope="entry",
            )

        assert result.output == "done"
        assert len(system_prompts) == 1
        assert "Be polite." in system_prompts[0]

    @pytest.mark.asyncio
    async def test_entry_scope_not_propagated_to_sub_agent(self) -> None:
        """Sub-agents called via call_agent do NOT receive extra_instructions."""
        system_prompts: list[tuple[str, str]] = []

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
                system_prompts.append((agent.name, context.system_prompt))
                self._call_count += 1
                if self._call_count == 1:
                    return _call_agent("agent_b", "help")
                return _finish("done")

        mock = CapturingBackend()
        agent_a = _make_agent("agent_a")
        agent_b = _make_agent("agent_b")

        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="start",
                agents=[agent_a, agent_b],
                tools=[],
                providers=[_make_provider()],
                extra_instructions="Special instruction.",
                extra_instructions_scope="entry",
            )

        assert result.output == "done"
        agent_a_prompts = [sp for name, sp in system_prompts if name == "agent_a"]
        agent_b_prompts = [sp for name, sp in system_prompts if name == "agent_b"]
        assert len(agent_a_prompts) >= 1
        assert len(agent_b_prompts) >= 1
        for sp in agent_a_prompts:
            assert "Special instruction." in sp
        for sp in agent_b_prompts:
            assert "Special instruction." not in sp


class TestExtraInstructionsScopeAll:
    """extra_instructions_scope='all' injects to all agents in chain."""

    @pytest.mark.asyncio
    async def test_all_scope_propagates_to_sub_agent(self) -> None:
        """Sub-agents also receive extra_instructions when scope='all'."""
        system_prompts: list[tuple[str, str]] = []

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
                system_prompts.append((agent.name, context.system_prompt))
                self._call_count += 1
                if self._call_count == 1:
                    return _call_agent("agent_b", "help")
                return _finish("done")

        mock = CapturingBackend()
        agent_a = _make_agent("agent_a")
        agent_b = _make_agent("agent_b")

        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="start",
                agents=[agent_a, agent_b],
                tools=[],
                providers=[_make_provider()],
                extra_instructions="Shared instruction.",
                extra_instructions_scope="all",
            )

        assert result.output == "done"
        agent_a_prompts = [sp for name, sp in system_prompts if name == "agent_a"]
        agent_b_prompts = [sp for name, sp in system_prompts if name == "agent_b"]
        assert len(agent_a_prompts) >= 1
        assert len(agent_b_prompts) >= 1
        for sp in agent_a_prompts:
            assert "Shared instruction." in sp
        for sp in agent_b_prompts:
            assert "Shared instruction." in sp

    @pytest.mark.asyncio
    async def test_all_scope_propagates_through_nested_calls(self) -> None:
        """extra_instructions propagates through multiple levels of call_agent."""
        system_prompts: list[tuple[str, str]] = []

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
                system_prompts.append((agent.name, context.system_prompt))
                self._call_count += 1
                if self._call_count == 1:
                    return _call_agent("agent_b", "level 1")
                if self._call_count == 2:
                    return _call_agent("agent_c", "level 2")
                return _finish("done")

        mock = CapturingBackend()
        agent_a = _make_agent("agent_a")
        agent_b = _make_agent("agent_b")
        agent_c = _make_agent("agent_c")

        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="start",
                agents=[agent_a, agent_b, agent_c],
                tools=[],
                providers=[_make_provider()],
                extra_instructions="Universal rule.",
                extra_instructions_scope="all",
            )

        assert result.output == "done"
        for name, sp in system_prompts:
            assert "Universal rule." in sp


class TestExtraInstructionsNone:
    """When extra_instructions is None, nothing is injected."""

    @pytest.mark.asyncio
    async def test_no_extra_instructions_default(self) -> None:
        """Default behavior (no extra_instructions) works without injection."""
        system_prompts: list[str] = []

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
                system_prompts.append(context.system_prompt)
                self._call_count += 1
                return _finish("result")

        mock = CapturingBackend()
        agent_a = _make_agent("agent_a")

        with patch("agentouto.router.get_backend", return_value=mock):
            result = await async_run(
                entry=agent_a,
                message="hello",
                agents=[agent_a],
                tools=[],
                providers=[_make_provider()],
            )

        assert result.output == "result"
        assert len(system_prompts) == 1
        assert "ADDITIONAL INSTRUCTIONS:" not in system_prompts[0]


# --- Background agent tests ---


class TestExtraInstructionsBackground:
    """extra_instructions works correctly with background agents."""

    def test_run_background_sync_accepts_extra_instructions(self) -> None:
        """run_background_sync accepts extra_instructions and extra_instructions_scope params."""
        import inspect

        sig = inspect.signature(run_background_sync)
        params = list(sig.parameters.keys())
        assert "extra_instructions" in params
        assert "extra_instructions_scope" in params


# --- Public API signature tests ---


class TestExtraInstructionsAPI:
    """All public run functions accept extra_instructions parameters."""

    def test_run_signature_has_extra_instructions(self) -> None:
        """run() function has extra_instructions and extra_instructions_scope params."""
        import inspect

        sig = inspect.signature(run)
        params = list(sig.parameters.keys())
        assert "extra_instructions" in params
        assert "extra_instructions_scope" in params

    def test_async_run_signature_has_extra_instructions(self) -> None:
        """async_run() function has extra_instructions and extra_instructions_scope params."""
        import inspect

        sig = inspect.signature(async_run)
        params = list(sig.parameters.keys())
        assert "extra_instructions" in params
        assert "extra_instructions_scope" in params

    def test_run_background_signature_has_extra_instructions(self) -> None:
        """run_background() function has extra_instructions and extra_instructions_scope params."""
        import inspect

        sig = inspect.signature(run_background)
        params = list(sig.parameters.keys())
        assert "extra_instructions" in params
        assert "extra_instructions_scope" in params

    def test_run_background_sync_signature_has_extra_instructions(self) -> None:
        """run_background_sync() function has extra_instructions and extra_instructions_scope params."""
        import inspect

        sig = inspect.signature(run_background_sync)
        params = list(sig.parameters.keys())
        assert "extra_instructions" in params
        assert "extra_instructions_scope" in params


# --- Helper fixtures ---


def _make_router() -> Router:
    agents = [
        Agent(
            name="researcher",
            instructions="Research expert.",
            model="gpt-4o",
            provider="openai",
        ),
        Agent(
            name="writer",
            instructions="Writes reports.",
            model="gpt-4o",
            provider="openai",
        ),
    ]
    providers = [Provider(name="openai", kind="openai", api_key="sk-test")]
    return Router(agents, [], providers)


def _make_agent(name: str) -> Agent:
    return Agent(
        name=name, instructions=f"{name} agent.", model="gpt-4o", provider="openai"
    )


def _make_provider() -> Provider:
    return Provider(name="openai", kind="openai", api_key="sk-test")
