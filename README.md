# AgentOutO

**멀티 에이전트 특화 Python SDK — 오케스트레이터 없는 피어 간 자유 호출**

A multi-agent Python SDK where every agent is equal. No orchestrator. No hierarchy. No restrictions.

---

## 핵심 철학 (Core Philosophy)

AgentOutO rejects the orchestrator pattern used by existing frameworks (CrewAI, AutoGen, etc.).

> **모든 에이전트는 완전히 대등하다.** Base 에이전트가 존재하지 않는다.
>
> **모든 에이전트는 모든 에이전트를 호출할 수 있다.** 호출 제한이 없다.
>
> **모든 에이전트는 모든 도구를 사용할 수 있다.** 도구 제한이 없다.
>
> **메시지 프로토콜은 전달/반환 2종류뿐이다.**
>
> **사용자는 LLM이 없는 에이전트일 뿐이다.** 별도의 인터페이스, 프로토콜, 도구는 존재하지 않는다.

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
pip install agnetouto
```

Requires Python ≥ 3.11.

---

## Quick Start

```python
from agnetouto import Agent, Tool, Provider, run

# Provider — API connection info only
openai = Provider(name="openai", kind="openai", api_key="sk-...")

# Tool — globally available to all agents
@Tool
def search_web(query: str) -> str:
    """Search the web."""
    return f"Results for: {query}"

# Agent — model settings live here
researcher = Agent(
    name="researcher",
    instructions="Research expert. Search and organize information.",
    model="gpt-4o",
    provider="openai",
)

writer = Agent(
    name="writer",
    instructions="Skilled writer. Turn research into polished reports.",
    model="gpt-4o",
    provider="openai",
)

# Run — user is just an agent without an LLM
result = run(
    entry=researcher,
    message="Write an AI trends report.",
    agents=[researcher, writer],
    tools=[search_web],
    providers=[openai],
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
from agnetouto import Provider

openai = Provider(name="openai", kind="openai", api_key="sk-...")
anthropic = Provider(name="anthropic", kind="anthropic", api_key="sk-ant-...")
google = Provider(name="google", kind="google", api_key="AIza...")

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
from agnetouto import Agent

agent = Agent(
    name="researcher",
    instructions="Research expert.",
    model="gpt-4o",
    provider="openai",
    max_output_tokens=16384,
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
| `max_output_tokens` | Max output tokens | `4096` |
| `reasoning` | Enable reasoning/thinking mode | `False` |
| `reasoning_effort` | Reasoning intensity | `"medium"` |
| `reasoning_budget` | Thinking token budget (Anthropic) | `None` |
| `temperature` | Temperature | `1.0` |
| `extra` | Additional API parameters (free dict) | `{}` |

The SDK uses unified parameter names. Each provider backend maps them internally:

| SDK Parameter | OpenAI | Anthropic | Google Gemini |
|---|---|---|---|
| `max_output_tokens` | `max_completion_tokens` | `max_tokens` | `max_output_tokens` (in generation_config) |
| `reasoning=True` | sends `reasoning_effort` | `thinking={"type": "enabled", "budget_tokens": ...}` | `thinking_config={"thinking_budget": ...}` |
| `reasoning_effort` | top-level `reasoning_effort` | N/A | N/A |
| `reasoning_budget` | N/A | `thinking.budget_tokens` | `thinking_config.thinking_budget` |
| `temperature` (reasoning=True) | **not sent** | **forced to 1** | sent as-is |

See [`ai-docs/PROVIDER_BACKENDS.md`](./ai-docs/PROVIDER_BACKENDS.md) for full mapping details.

### Tool — Global, No Per-Agent Restrictions

```python
from agnetouto import Tool

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

### Message — Forward and Return Only

```python
@dataclass
class Message:
    type: Literal["forward", "return"]
    sender: str
    receiver: str
    content: str
    call_id: str  # Unique tracking ID
```

Two types. No exceptions.

---

## Supported Providers

| Kind | Provider | Compatible With |
|------|----------|-----------------|
| `"openai"` | OpenAI API | vLLM, Ollama, LM Studio, any OpenAI-compatible API |
| `"anthropic"` | Anthropic API | — |
| `"google"` | Google Gemini API | — |

---

## Async Usage

```python
import asyncio
from agnetouto import async_run

result = await async_run(
    entry=researcher,
    message="Write an AI trends report.",
    agents=[researcher, writer, reviewer],
    tools=[search_web, write_file],
    providers=[openai, anthropic, google],
)
```

---

## Package Structure

```
agnetouto/
├── __init__.py          # Public API: Agent, Tool, Provider, run, async_run, Message, RunResult
├── agent.py             # Agent dataclass
├── tool.py              # Tool decorator/class with auto JSON schema generation
├── message.py           # Message dataclass (forward/return)
├── provider.py          # Provider dataclass (API connection info)
├── context.py           # Per-agent conversation context management
├── router.py            # Message routing, system prompt generation, tool schema building
├── runtime.py           # Agent loop engine, parallel execution, run()/async_run()
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
| **6** | CI/CD, tests, PyPI publish | 🔶 Partial (CI/CD + tests done, PyPI pending) |

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
