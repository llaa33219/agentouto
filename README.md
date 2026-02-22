<p align="center">
  <img src="logo.svg" alt="AgentOutO" width="600">
</p>

<h1 align="center">AgentOutO</h1>

<p align="center"><strong>A multi-agent Python SDK — peer-to-peer free calls with no orchestrator.</strong></p>

Every agent is equal. No orchestrator. No hierarchy. No restrictions.

---

## Core Philosophy

AgentOutO rejects the orchestrator pattern used by existing frameworks (CrewAI, AutoGen, etc.).

> **All agents are fully equal.** There is no base agent.
>
> **Any agent can call any agent.** There are no call restrictions.
>
> **Any agent can use any tool.** There are no tool restrictions.
>
> **The message protocol has exactly two types: forward and return.**
>
> **The user is just an agent without an LLM.** No special interface, protocol, or tools exist for the user.

| Existing Frameworks | AgentOutO |
|---|---|
| Orchestrator-centric hierarchy | Peer-to-peer free calls |
| Base agent required | No base agent |
| Per-agent allowed-call lists | Any agent calls any agent |
| Per-agent tool assignment | All tools are global |
| Complex message protocols | Forward / Return only |
| Top-down message flow | Bidirectional free flow |

---

## Installation

```bash
pip install agentouto
```

Requires Python ≥ 3.11.

---

## Quick Start

```python
from agentouto import Agent, Tool, Provider, run

# Providers — API connection info only
openai = Provider(name="openai", kind="openai", api_key="sk-...")
anthropic = Provider(name="anthropic", kind="anthropic", api_key="sk-ant-...")
google = Provider(name="google", kind="google", api_key="AIza...")

# Tool — globally available to all agents
@Tool
def search_web(query: str) -> str:
    """Search the web."""
    return f"Results for: {query}"

# Agent — model settings live here
researcher = Agent(
    name="researcher",
    instructions="Research expert. Search and organize information.",
    model="gpt-5.2",
    provider="openai",
)

writer = Agent(
    name="writer",
    instructions="Skilled writer. Turn research into polished reports.",
    model="claude-sonnet-4-6",
    provider="anthropic",
)

reviewer = Agent(
    name="reviewer",
    instructions="Critical reviewer. Verify facts and improve quality.",
    model="gemini-3.1-pro",
    provider="google",
)

# Run — user is just an agent without an LLM
result = run(
    entry=researcher,
    message="Write an AI trends report.",
    agents=[researcher, writer, reviewer],
    tools=[search_web],
    providers=[openai, anthropic, google],
)

print(result.output)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        run()                            │
│              (User = LLM-less agent)                    │
│                         │                               │
│                    Forward Message                      │
│                         ▼                               │
│  ┌─────────────── Agent Loop ──────────────────┐        │
│  │                                             │        │
│  │  ┌──→ LLM Call (via Provider Backend)       │        │
│  │  │        │                                 │        │
│  │  │        ├── tool_call  → Tool.execute()   │        │
│  │  │        │                   │             │        │
│  │  │        │              result back ───┐   │        │
│  │  │        │                             │   │        │
│  │  │        ├── call_agent → New Loop ────┤   │        │
│  │  │        │                  │          │   │        │
│  │  │        │             return back ───┐│   │        │
│  │  │        │                            ││   │        │
│  │  │        └── finish → Return Message  ││   │        │
│  │  │                                     ││   │        │
│  │  └────────────── next iteration ◄──────┘┘   │        │
│  └─────────────────────────────────────────────┘        │
│                         │                               │
│                    Return Message                       │
│                         ▼                               │
│                    RunResult.output                     │
└─────────────────────────────────────────────────────────┘
```

### Message Flow — Peer to Peer

```
[User]  ──(forward)──→  [Agent A]
                            │
                            ├──(forward)──→ [Agent B]
                            │                 ├──(forward)──→ [Agent C]
                            │                 │                  │
                            │                 │←──(return)──────┘
                            │                 │
                            │←──(return)─────┘
                            │
                            └──(return)──→  [User]
```

User→A and A→B use the **exact same mechanism**. There is no special user protocol.

### Parallel Calls

```
[Agent A]
    ├──(forward)──→ [Agent B]  ─┐
    ├──(forward)──→ [Agent C]   ├── asyncio.gather — all run concurrently
    └──(forward)──→ [Agent D]  ─┘
                                │
    ←──(3 returns, batched)────┘
```

---

## Core Concepts

### Provider — API Connection Only

Providers hold API credentials. No model settings, no inference config.

```python
from agentouto import Provider

openai = Provider(name="openai", kind="openai", api_key="sk-...")        # gpt-5.2, gpt-5.3-codex, o3, o4-mini
anthropic = Provider(name="anthropic", kind="anthropic", api_key="sk-ant-...")  # claude-opus-4-6, claude-sonnet-4-6
google = Provider(name="google", kind="google", api_key="AIza...")        # gemini-3.1-pro, gemini-3-flash

# OpenAI-compatible APIs (vLLM, Ollama, LM Studio, etc.)
local = Provider(name="local", kind="openai", base_url="http://localhost:11434/v1")
```

| Field | Description | Required |
|-------|-------------|----------|
| `name` | Identifier for the provider | ✅ |
| `kind` | API type: `"openai"`, `"anthropic"`, `"google"` | ✅ |
| `api_key` | API key | ✅ |
| `base_url` | Custom endpoint URL (for compatible APIs) | ❌ |

### Agent — Model Settings Live Here

```python
from agentouto import Agent

agent = Agent(
    name="researcher",
    instructions="Research expert.",
    model="gpt-5.2",
    provider="openai",
    reasoning=True,
    reasoning_effort="high",
    temperature=1.0,
)
```

| Field | Description | Default |
|-------|-------------|---------|
| `name` | Agent name | (required) |
| `instructions` | Role description | (required) |
| `model` | Model name | (required) |
| `provider` | Provider name | (required) |
| `max_output_tokens` | Max output tokens | `None` (auto) |
| `reasoning` | Enable reasoning/thinking mode | `False` |
| `reasoning_effort` | Reasoning intensity | `"medium"` |
| `reasoning_budget` | Thinking token budget (Anthropic) | `None` |
| `temperature` | Temperature | `1.0` |
| `extra` | Additional API parameters (free dict) | `{}` |

The SDK uses unified parameter names. Each provider backend maps them internally:

| SDK Parameter | OpenAI | Anthropic | Google Gemini |
|---|---|---|---|
| `max_output_tokens` | `max_completion_tokens` (omitted when `None`) | `max_tokens` (auto-probed when `None`) | `max_output_tokens` (omitted when `None`) |
| `reasoning=True` | sends `reasoning_effort` | `thinking={"type": "enabled", "budget_tokens": ...}` | `thinking_config={"thinking_budget": ...}` |
| `reasoning_effort` | top-level `reasoning_effort` | N/A | N/A |
| `reasoning_budget` | N/A | `thinking.budget_tokens` | `thinking_config.thinking_budget` |
| `temperature` (reasoning=True) | **not sent** | **forced to 1** | sent as-is |

See [`ai-docs/PROVIDER_BACKENDS.md`](./ai-docs/PROVIDER_BACKENDS.md) for full mapping details.

### Tool — Global, No Per-Agent Restrictions

```python
from agentouto import Tool

@Tool
def search_web(query: str) -> str:
    """Search the web."""
    return f"Results for: {query}"

# Async tools are supported
@Tool
async def fetch_data(url: str) -> str:
    """Fetch data from URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.text()
```

Tools are automatically converted to JSON schemas from function signatures and docstrings. All agents can use all tools.

#### Rich Parameter Schemas

Use `Annotated` for parameter descriptions, `Literal` for allowed values, `Enum` for enumerated types, and default values — all reflected in the JSON schema sent to the LLM:

```python
from typing import Annotated, Literal
from agentouto import Tool

@Tool
def search_web(
    query: Annotated[str, "Search keywords or question"],
    max_results: Annotated[int, "Maximum number of results to return"] = 10,
    language: Literal["ko", "en", "ja"] = "ko",
) -> str:
    """Search the web for information."""
    ...
```

This generates a detailed schema that helps the LLM use tools correctly:

```json
{
  "properties": {
    "query": {"type": "string", "description": "Search keywords or question"},
    "max_results": {"type": "integer", "description": "Maximum number of results to return", "default": 10},
    "language": {"type": "string", "enum": ["ko", "en", "ja"], "default": "ko"}
  },
  "required": ["query"]
}
```

Plain type hints (without `Annotated`) continue to work as before.

Tools can also return rich results with file attachments using `ToolResult`:

```python
from agentouto import Tool, ToolResult, Attachment

@Tool
def fetch_image(url: str) -> ToolResult:
    """Fetch an image from URL."""
    data = download_and_base64_encode(url)
    return ToolResult(
        content="Image fetched successfully.",
        attachments=[Attachment(mime_type="image/png", data=data)],
    )
```

When a tool returns `ToolResult` with attachments, the LLM can visually analyze the images. Regular `str` returns remain fully supported.

### Multimodal Attachments

Agents can receive file attachments (images, audio, video, PDFs) via the `Attachment` dataclass:

```python
@dataclass
class Attachment:
    mime_type: str                # "image/png", "audio/mp3", "video/mp4"
    data: str | None = None       # base64-encoded data
    url: str | None = None        # URL reference (mutually exclusive with data)
    name: str | None = None       # optional filename
```

Pass attachments to `run()` or `async_run()`:

```python
from agentouto import run, Attachment

result = run(
    entry=vision_agent,
    message="Analyze this image.",
    agents=[vision_agent],
    tools=[],
    providers=[openai],
    attachments=[
        Attachment(mime_type="image/png", data=base64_string),
        Attachment(mime_type="image/jpeg", url="https://example.com/photo.jpg"),
    ],
)
```

All three provider backends (OpenAI, Anthropic, Google) convert attachments to their native multimodal format automatically.

### Message — Forward and Return Only

```python
@dataclass
class Message:
    type: Literal["forward", "return"]
    sender: str
    receiver: str
    content: str
    call_id: str  # Unique tracking ID
    attachments: list[Attachment] | None = None
```

Two types. No exceptions.

---

## Supported Providers

| Kind | Provider | Example Models | Compatible With |
|------|----------|----------------|-----------------|
| `"openai"` | OpenAI API | `gpt-5.2`, `gpt-5.3-codex`, `o3`, `o4-mini` | vLLM, Ollama, LM Studio, any OpenAI-compatible API |
| `"anthropic"` | Anthropic API | `claude-opus-4-6`, `claude-sonnet-4-6` | AWS Bedrock, Google Vertex AI, Ollama, LiteLLM, any Anthropic-compatible API |
| `"google"` | Google Gemini API | `gemini-3.1-pro`, `gemini-3-flash` | — |

---

## Async Usage

```python
import asyncio
from agentouto import async_run

result = await async_run(
    entry=researcher,
    message="Write an AI trends report.",
    agents=[researcher, writer, reviewer],  # Each agent can use any model/provider
    tools=[search_web, write_file],
    providers=[openai, anthropic, google],   # Mix providers freely
)
```

### Streaming

```python
from agentouto import async_run_stream

async for event in async_run_stream(
    entry=researcher,
    message="Write an AI trends report.",
    agents=[researcher, writer, reviewer],
    tools=[search_web],
    providers=[openai, anthropic, google],
):
    if event.type == "token":
        print(event.data["token"], end="", flush=True)
    elif event.type == "finish":
        print(f"\n--- {event.agent_name} finished ---")
```

---

## Package Structure

```
agentouto/
├── __init__.py          # Public API exports (Agent, Tool, Provider, Attachment, ToolResult, ...)
├── agent.py             # Agent dataclass
├── tool.py              # Tool decorator/class with auto JSON schema, ToolResult
├── message.py           # Message dataclass (forward/return)
├── provider.py          # Provider dataclass (API connection info)
├── context.py           # Attachment, ContextMessage, per-agent conversation context
├── router.py            # Message routing, system prompt generation, tool schema building
├── runtime.py           # Agent loop engine, parallel execution, run()/async_run()
├── streaming.py         # async_run_stream(), StreamEvent
├── event_log.py         # AgentEvent, EventLog — structured event recording
├── tracing.py           # Trace, Span — call tree builder from event logs
├── _constants.py        # Shared constants (CALL_AGENT, FINISH)
├── exceptions.py        # ProviderError, AgentError, ToolError, RoutingError
└── providers/
    ├── __init__.py      # ProviderBackend ABC, LLMResponse, get_backend()
    ├── openai.py        # OpenAI (+ compatible APIs) implementation
    ├── anthropic.py     # Anthropic implementation
    └── google.py        # Google Gemini implementation
```

---

## Development Status

| Phase | Description | Status |
|-------|-------------|--------|
| **1** | Core classes: Provider, Agent, Tool, Message | ✅ Done |
| **2** | Single agent execution: agent loop + tool calling | ✅ Done |
| **3** | Multi-agent: call_agent + finish + message routing | ✅ Done |
| **4** | Parallel calls: asyncio.gather concurrent execution | ✅ Done |
| **5** | Streaming, logging, tracing, debug mode | ✅ Done |
| **6** | CI/CD, tests, PyPI publish | ✅ Done |
| **7** | Multimodal attachments (Attachment, ToolResult) | ✅ Done |
| **8** | Rich parameter schemas (Annotated, Literal, Enum, default) | ✅ Done |
| **9** | Reasoning tag handling (content preservation, detection prevention) | ✅ Done |
| **10** | Auto max output tokens + safe JSON argument parsing | ✅ Done |

---

## Technical Documentation

For AI contributors and detailed technical reference, see **[`ai-docs/`](./ai-docs/)**:

- [`AI_INSTRUCTIONS.md`](./ai-docs/AI_INSTRUCTIONS.md) — **Read this first.** How to work on this project and update docs.
- [`PHILOSOPHY.md`](./ai-docs/PHILOSOPHY.md) — Core philosophy and inviolable principles.
- [`ARCHITECTURE.md`](./ai-docs/ARCHITECTURE.md) — Package structure, module responsibilities, data flow.
- [`PROVIDER_BACKENDS.md`](./ai-docs/PROVIDER_BACKENDS.md) — Provider system, parameter mapping, API-specific behavior.
- [`MESSAGE_PROTOCOL.md`](./ai-docs/MESSAGE_PROTOCOL.md) — Message types, routing rules, parallel calls, agent loop.
- [`CONVENTIONS.md`](./ai-docs/CONVENTIONS.md) — Coding conventions, patterns, naming, style guide.
- [`ROADMAP.md`](./ai-docs/ROADMAP.md) — Current status, planned features, known issues.

---

## License

Apache License 2.0 — see [LICENSE](./LICENSE) for details.
