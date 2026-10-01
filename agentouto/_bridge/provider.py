from __future__ import annotations

from typing import TYPE_CHECKING, Any

from coreouto import (
    LLMResponse as CoreLLMResponse,
    Message as CoreMessage,
    ToolCall as CoreToolCall,
    ToolResult as CoreToolResult,
    register_provider,
)

from agentouto._bridge.convert import (
    assistant_core_message,
    blocks_to_attachments,
    context_from_coreouto,
    tool_calls_to_core,
    tool_core_message,
    usage_to_core,
)
from agentouto._bridge.state import RunState, require_run_state
from agentouto._constants import FINISH
from agentouto.tool import ToolResult

if TYPE_CHECKING:
    from coreouto import Tool

    from agentouto.agent import Agent
    from agentouto.context import Context, ToolCall
    from agentouto.providers import LLMResponse
    from agentouto.router import Router


def require_agent(state: RunState) -> Agent:
    """The loop's agent. ``RunState.agent`` is optional only for the
    ``Runtime._execute_tool_call`` seam, which never reaches a provider."""
    if state.agent is None:
        raise RuntimeError("agentouto bridge: RunState has no agent for this call")
    return state.agent


class NoLLMResponseError(Exception):
    """Raised when a streaming backend yields no final ``LLMResponse``."""


_KIND_TO_CORE_PROVIDER: dict[str, str] = {
    "openai": "openai",
    "openai_responses": "openai-response",
    "anthropic": "anthropic",
    "google": "google",
}


def core_provider_name(router: Router, agent: Agent) -> str:
    """Map an agentouto provider ``kind`` to the coreouto registry name.

    coreouto classifies unrecoverable provider stops (refusal / length /
    safety) from a deny-set keyed by these exact registry names, so the
    mapping must stay exact.

    ``Router`` exposes no public provider accessor and ``router.py`` is owned
    by another work unit, so the lookup goes through its provider table.
    """
    provider = router._providers.get(agent.provider)
    if provider is None:
        from agentouto.exceptions import ProviderError

        raise ProviderError(agent.provider, "Provider not found")
    kind = _KIND_TO_CORE_PROVIDER.get(provider.kind)
    if kind is None:
        raise ValueError(f"Unknown provider kind: {provider.kind}")
    return kind


def find_finish(tool_calls: list[ToolCall]) -> ToolCall | None:
    for tc in tool_calls:
        if tc.name == FINISH:
            return tc
    return None


async def resolve_finish_result(
    state: RunState, arguments: dict[str, Any]
) -> str:
    """Turn a ``finish(message=X)`` tool call into the final answer text."""
    override = state.runtime._router.get_builtin_override(FINISH)
    if override is None:
        return str(arguments.get("message", ""))
    try:
        raw = await override.execute(**arguments)
    except Exception as exc:
        return f"Error in finish override: {exc}"
    return raw.content if isinstance(raw, ToolResult) else str(raw)


class DispatchProvider:
    """coreouto ``Provider`` implementation backed by agentouto's backends.

    agentouto's provider backends own the wire format (multimodal tool
    results, JSON-argument repair), so this shim only converts: it rebuilds an
    agentouto ``Context`` from coreouto's message list, calls the backend
    through ``Router`` (the ``router.get_backend`` patch seam), and converts
    the response back.
    """

    # coreouto's loop gates stream-callback injection on ``hasattr(provider,
    # "_stream")``; per-run stream vs. call is decided from ``RunState.stream``
    # so one shared instance can serve concurrent runs.
    _stream = True

    async def create(
        self,
        messages: list[CoreMessage],
        *,
        model: str,
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> CoreLLMResponse:
        state = require_run_state()
        context = context_from_coreouto(messages)
        schemas = state.tool_schemas

        agent = require_agent(state)
        on_stream_text = kwargs.get("_on_stream_text")
        if state.stream and on_stream_text is not None:
            response = await self._stream_call(
                state, agent, context, schemas, on_stream_text
            )
        else:
            response = await state.router.call_llm(agent, context, schemas)

        finish_call = find_finish(response.tool_calls) if response.tool_calls else None
        if finish_call is not None:
            # `finish(message=X)` is rewritten into a plain text response so it
            # is indistinguishable from coreouto's native termination path.
            # Any sibling tool calls are deliberately dropped, matching the
            # previous loop which returned as soon as finish was seen.
            return CoreLLMResponse(
                content=await resolve_finish_result(state, finish_call.arguments),
                tool_calls=[],
                usage=usage_to_core(response.usage),
                stop_reason=response.stop_reason,
            )
        return CoreLLMResponse(
            content=response.content,
            tool_calls=tool_calls_to_core(response.tool_calls),
            usage=usage_to_core(response.usage),
            stop_reason=response.stop_reason,
        )

    async def _stream_call(
        self,
        state: RunState,
        agent: Agent,
        context: Context,
        schemas: list[dict[str, Any]],
        on_stream_text: Any,
    ) -> LLMResponse:
        response: LLMResponse | None = None
        async for chunk in state.router.stream_llm(agent, context, schemas):
            if isinstance(chunk, str):
                await on_stream_text(chunk)
            else:
                response = chunk
        if response is None:
            raise NoLLMResponseError("streaming backend yielded no LLMResponse")
        return response

    def format_assistant_message(self, response: CoreLLMResponse) -> CoreMessage:
        return assistant_core_message(
            response.content, list(response.tool_calls) or None
        )

    def format_tool_result(
        self, tool_call: CoreToolCall, result: CoreToolResult
    ) -> CoreMessage:
        content = result.content
        attachments = None
        if content is None and result.blocks is not None:
            content, attachments = blocks_to_attachments(result.blocks)
        return tool_core_message(
            tool_call.id, tool_call.name, content or "", attachments
        )


_registered = False


def register_dispatch_provider() -> None:
    """Register the shim under coreouto's four canonical provider names.

    Idempotent: coreouto's provider registry is process-global and other
    agentouto runs share it.
    """
    global _registered
    if _registered:
        return
    provider = DispatchProvider()
    for name in _KIND_TO_CORE_PROVIDER.values():
        register_provider(name, provider)
    _registered = True


register_dispatch_provider()