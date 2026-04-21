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
    message="Write an AI trends report.",
    starting_agents=[researcher, writer, reviewer],
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
openai_resp = Provider(name="openai-resp", kind="openai_responses", api_key="sk-...")  # Responses API
anthropic = Provider(name="anthropic", kind="anthropic", api_key="sk-ant-...")  # claude-opus-4-6, claude-sonnet-4-6
google = Provider(name="google", kind="google", api_key="AIza...")        # gemini-3.1-pro, gemini-3-flash

# OpenAI-compatible APIs (vLLM, Ollama, LM Studio, etc.)
local = Provider(name="local", kind="openai", base_url="http://localhost:11434/v1")
```

| Field | Description | Required |
|-------|-------------|----------|
| `name` | Identifier for the provider | ✅ |
| `kind` | API type: `"openai"`, `"openai_responses"`, `"anthropic"`, `"google"` | ✅ |
| `api_key` | API key (not needed when `auth` is set) | ❌ |
| `base_url` | Custom endpoint URL (for compatible APIs) | ❌ |
| `auth` | `AuthMethod` instance for OAuth authentication | ❌ |

### OAuth Authentication

Providers can use OAuth 2.0 instead of static API keys via the `auth` parameter. Install OAuth dependencies:

```bash
pip install agentouto[oauth]
```

**OpenAI OAuth** — Use your ChatGPT Plus/Pro subscription:

```python
from agentouto import Provider, OpenAIOAuth

auth = OpenAIOAuth(client_id="your-client-id")
await auth.ensure_authenticated()  # Opens browser for login

openai = Provider(name="openai", kind="openai", auth=auth)
```

**Claude OAuth** ⚠️ — Anthropic prohibits third-party OAuth usage. Account suspension risk:

```python
from agentouto import Provider, ClaudeOAuth

# ⚠️ TOS VIOLATION RISK — Use API keys from console.anthropic.com instead
auth = ClaudeOAuth(client_id="your-client-id")
await auth.ensure_authenticated()

anthropic = Provider(name="anthropic", kind="anthropic", auth=auth)
```

**Google OAuth** ⚠️ — Google bans accounts using Antigravity OAuth. Use your own GCP credentials:

```python
from agentouto import Provider, GoogleOAuth

# ⚠️ Antigravity OAuth → account ban risk (Gmail, Drive, ALL services)
# Safe: Use your own GCP OAuth Client ID from console.cloud.google.com
auth = GoogleOAuth(
    client_id="your-gcp-client-id.apps.googleusercontent.com",
    client_secret="your-gcp-secret",
)
await auth.ensure_authenticated()

google = Provider(name="google", kind="google", auth=auth)
```

OAuth tokens are automatically cached in `~/.agentouto/tokens/` and refreshed when expired.

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
| `instructions` | Detailed instructions (included in agent's system prompt) | (required) |
| `model` | Model name | (required) |
| `provider` | Provider name | (required) |
| `role` | Short role description (shown in agent list) | `None` (uses instructions) |
| `max_output_tokens` | Max output tokens | `None` (auto) |
| `reasoning` | Enable reasoning/thinking mode | `False` |
| `reasoning_effort` | Reasoning intensity | `"medium"` |
| `reasoning_budget` | Thinking token budget (Anthropic) | `None` |
| `temperature` | Temperature | `1.0` |
| `context_window` | Context window tokens (auto-resolved) | `None` (auto) |
| `extra` | Additional API parameters (free dict) | `{}` |

The SDK uses unified parameter names. Each provider backend maps them internally:

| SDK Parameter | OpenAI (Chat Completions) | OpenAI (Responses) | Anthropic | Google Gemini |
|---|---|---|---|---|
| `max_output_tokens` | `max_completion_tokens` (omitted when `None`) | `max_output_tokens` (omitted when `None`) | `max_tokens` (auto-probed when `None`) | `max_output_tokens` (omitted when `None`) |
| `reasoning=True` | sends `reasoning_effort` | `reasoning={"effort": value}` | `thinking={"type": "enabled", "budget_tokens": ...}` | `thinking_config={"thinking_budget": ...}` |
| `reasoning_effort` | top-level `reasoning_effort` | `reasoning.effort` | N/A | N/A |
| `reasoning_budget` | N/A | N/A | `thinking.budget_tokens` | `thinking_config.thinking_budget` |
| `temperature` (reasoning=True) | **not sent** | **not sent** | **forced to 1** | sent as-is |

`context_window` is auto-resolved from LCW API when `None`. Set explicitly to override. When set, self-summarization triggers at 70% of context limit.

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

### Tool Override and Disable

Built-in tools (`call_agent`, `spawn_background_agent`, `send_message`, `get_messages`, `finish`) can be overridden or disabled at the `run()` level.

#### Disabling Tools

Pass `disabled_tools` to exclude built-in tools from the tool schemas sent to the LLM:

```python
result = run(
    message="Do research.",
    starting_agents=[researcher],
    tools=[search_web],
    providers=[openai],
    disabled_tools={"spawn_background_agent", "get_messages"},
)
# The LLM won't see spawn_background_agent or get_messages in its tool list.
```

#### Overriding Tools

Provide a user tool with the same name as a built-in to replace it:

```python
@Tool
def finish(message: str, confidence: float = 1.0) -> str:
    """Return result with confidence score."""
    return f"[{confidence}] {message}"

result = run(
    message="Analyze this data.",
    starting_agents=[researcher],
    tools=[finish],  # Replaces the built-in finish
    providers=[openai],
)
# result.output will be "[0.85] Analysis complete"
```

Override takes precedence over disable — if a tool is both overridden and in `disabled_tools`, the override is used.

**Note:** `finish` cannot be disabled (raises `ValueError`). Override it instead if you need custom finish behavior.

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
    message="Analyze this image.",
    starting_agents=[vision_agent],
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

### Conversation History

You can pass previous conversation history to an agent to maintain context across calls. Use `RunResult.messages` from a previous run:

```python
from agentouto import run, Agent, Provider

# First conversation
result1 = run(
    message="Research AI trends.",
    starting_agents=[researcher],
    tools=[],
    providers=[openai],
)

# Continue with history
result2 = run(
    message="Write about what you found.",
    starting_agents=[writer, researcher],
    tools=[],
    providers=[openai],
    history=result1.messages,  # Pass previous messages
)
```

You can also use `history` with `call_agent` tool. The LLM can pass conversation history when calling another agent:

```python
# The LLM can call:
call_agent(
    agent_name="writer",
    message="Continue the report.",
    history=[...]  # Optional array of previous Message objects
)
```

History is prepended to the agent's context before the new forward message, allowing the agent to have continuity with previous conversations.

### Extra Instructions at Runtime

You can inject additional instructions into the system prompt at runtime, without modifying agent declarations. This is useful for shared context that changes per execution — like a SOUL.md file defining current project tone.

#### Injecting to Entry Agent Only

```python
# Load shared context that only the entry agent receives
with open("SOUL.md", "r") as f:
    soul_content = f.read()

result = run(
    message="Write an article about AI.",
    starting_agents=[writer, researcher],
    tools=[search_web],
    providers=[openai],
    extra_instructions=soul_content,
    extra_instructions_scope="entry",  # default
)
```

#### Injecting to All Agents

```python
# Load project rules that ALL agents must follow
with open("SOUL.md", "r") as f:
    soul_content = f.read()

result = run(
    message="Write an article about AI.",
    starting_agents=[writer, researcher, reviewer],
    tools=[search_web],
    providers=[openai],
    extra_instructions=soul_content,
    extra_instructions_scope="all",  # propagates to call_agent calls
)
# writer, researcher, reviewer ALL get SOUL.md in their system prompts
```

The instructions are injected as an `ADDITIONAL INSTRUCTIONS:` section in the system prompt, after agent identity but before available agents list.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `extra_instructions` | `None` | Additional text injected into system prompt |
| `extra_instructions_scope` | `"entry"` | `"entry"` → only first agent, `"all"` → all agents including sub-calls |

### Tracking Parallel Agent Calls

Every agent call is automatically assigned a unique `call_id` (UUID), so even when the same agent name is called multiple times in parallel, each invocation is tracked separately.

```python
task_id = run_background(
    message="Research AI trends",
    starting_agents=[researcher, writer, reviewer],
    tools=[search_web],
    providers=[openai],
)
# Returns main task_id: "bg_abc123"
# Additional agents spawned as: "bg_abc123_1", "bg_abc123_2", ...
```

**Example output when the same agent is called in parallel:**
```
user → researcher [call_id=a1b2c3d4] forward
researcher → researcher [call_id=e5f6g7h8] forward
researcher → researcher [call_id=i9j0k1l2] forward
researcher → user [call_id=a1b2c3d4] return
researcher → user [call_id=e5f6g7h8] return
researcher → user [call_id=i9j0k1l2] return
```

**Filtering by receiver to see all calls to a specific agent:**
```python
for msg in result.messages:
    if msg.receiver == "researcher" and msg.type == "forward":
        print(f"call_id={msg.call_id[:8]}: {msg.content[:50]}...")
```

### Background Execution — Isolated Agent Loops

Agents can run in **isolated loops** that can receive messages while running. This enables true concurrent agents that can communicate during execution.

#### Spawning Background Agents

Use `call_agent` with `background=True`, or use `run_background()` directly:

```python
from agentouto import run_background

# Spawn an agent in background — returns immediately with task_id
task_id = run_background(
    message="Research AI trends",
    starting_agents=[researcher, writer],
    tools=[search_web],
    providers=[openai],
)
# task_id = "bg_abc123"

# Or use call_agent with background=True from within an agent
call_agent(
    agent_name="researcher",
    message="Research the latest in AI.",
    background=True,
)
```

`run_background()` also supports `starting_agents` like `run()`:

```python
task_id = run_background(
    message="Research AI trends",
    run_agents=[researcher, writer, reviewer],
    tools=[search_web],
    providers=[openai],
    starting_agents=[writer, reviewer],
)
# Returns main task_id: "bg_abc123"
# Additional agents spawned as: "bg_abc123_1", "bg_abc123_2", ...
```

#### Sending Messages to Running Agents

Use `send_message` to inject messages into a running agent:

```python
from agentouto import send_message

# Send a message to the running agent
send_message(
    task_id="bg_abc123",
    message="Add a section about GPT-5.",
)
# Returns: "Message sent to writer (task_id: bg_abc123)"
```

The agent receives the message as a new user input in its running loop.

#### Getting Status and Messages

Use `get_agent_status` to check on a running agent:

```python
from agentouto import get_agent_status

# Retrieve status, result, and all messages
status = get_agent_status("bg_abc123")
# Returns:
# Task ID: bg_abc123
# Agent: writer
# Status: running
# Messages (3):
#   [forward] user -> writer: Write a report...
#   [return] writer -> user: Here's the report...
```

#### Streaming Events from Background Agents

Use `get_stream_events` to stream events from a background agent:

```python
from agentouto import get_stream_events

async for event in get_stream_events("bg_abc123"):
    if event["type"] == "token":
        print(event["data"]["text"], end="", flush=True)
    elif event["type"] == "finish":
        print(f"\n--- Result: {event['data']['output']} ---")
```

#### Background vs Parallel Calls

| Aspect | `asyncio.gather` Parallel | Isolated Loops |
|--------|---------------------------|----------------|
| Execution | Same loop iteration | Isolated loops |
| Communication | Results only after completion | Real-time messages |
| Independence | Share context | Own context |
| Use case | Fast parallel tasks | Long-running concurrent agents |

#### Example: Concurrent Research and Writing

```python
from agentouto import run_background, send_message, get_agent_status

# Spawn researcher in background
task_id = run_background(
    message="Research AI trends",
    starting_agents=[researcher],
    tools=[search_web],
    providers=[openai],
)
# task_id = "bg_res_001"

# Do other work...

# Send additional instructions
send_message(task_id="bg_res_001", message="Also look at GPT-5")

# Check status
print(get_agent_status("bg_res_001"))
```

See [`ai-docs/MESSAGE_PROTOCOL.md`](./ai-docs/MESSAGE_PROTOCOL.md#11-백그라운드-실행--background-execution) for detailed protocol documentation.

### Bidirectional Messages (on_message)

Agents and users can exchange messages in real-time during `run()` — no background mode needed. The only difference from `run_background()` is that `run()` blocks until the agent finishes.

#### Receiving and Sending Messages

Pass an `on_message` callback that receives `(message, send)`:

```python
def on_message(msg, send):
    print(f"[{msg.sender}] {msg.content}")
    if msg.content == "Need your input":
        send("Approved, proceed.")

result = run(
    message="Write a detailed report.",
    starting_agents=[writer],
    tools=[search_web],
    providers=[openai],
    on_message=on_message,
)
```

- **Agent → User**: Agent calls `send_message(task_id="...", message="...")` → `on_message` fires with the message
- **User → Agent**: Call `send("...")` inside the callback → message is queued and the agent receives it on its next iteration

#### How It Works

1. The user is registered as a loop in `AgentLoopRegistry`
2. The agent's system prompt includes the caller's `task_id`
3. The agent uses `send_message(task_id="...", message="update")` — the same tool used for background agents
4. The callback fires synchronously, receiving `(msg, send)` — call `send()` to reply
5. Messages sent via `send()` are queued and added to the agent's context before the next LLM call
6. Intermediate messages also appear in `RunResult.messages`

#### Streaming Integration

`async_run_stream` also supports `on_message`, plus yields `"user_message"` StreamEvents:

```python
async for event in async_run_stream(
    starting_agents=[writer],
    message="Write report",
    on_message=lambda msg, send: send("keep going") if "stuck" in msg.content else None,
):
    if event.type == "user_message":
        print(f"Progress: {event.data['message']}")
    elif event.type == "finish":
        print(f"Done: {event.data['output']}")
```

#### Agent-to-Agent Messages

`caller_loop_id` is included in all agent system prompts, so sub-agents can send intermediate messages to their caller (not just the user):

```
[User] → [Agent A] → [Agent B]
                       ├── send_message(task_id="A's loop", message="50%")
                       └── finish("done")
```

---

### Starting Agents — Parallel Execution at Run Start

All agents in `starting_agents` execute **simultaneously** in their own loops as equal peers:

```python
result = run(
    message="Research and write about AI trends",
    starting_agents=[researcher, writer, reviewer],  # all run in parallel
    tools=[search_web],
    providers=[openai, anthropic, google],
)
```

Each can call other agents via `call_agent`, use tools, and communicate independently.

#### Agent Participation with `run_agents`

`run_agents` defines the **participant pool** — agents that can execute, call, and perceive each other. If `run_agents` is not specified, it defaults to `starting_agents`.

**Warning:** Putting an agent in `starting_agents` but NOT in `run_agents` is **bad practice**. Such agents cannot participate in the run at all — they cannot execute, call other agents, or be perceived. A warning is issued in this case.

```python
# Good: all participants can see each other
result = run(
    message="Research and write about AI trends",
    starting_agents=[researcher, writer, reviewer],
    run_agents=[researcher, writer, reviewer],  # All participate
    tools=[search_web],
    providers=[openai, anthropic, google],
)

# Bad: reviewer in starting_agents but not in run_agents
# This will issue a warning — reviewer cannot participate!
result = run(
    message="...",
    starting_agents=[researcher, writer, reviewer],
    run_agents=[researcher, writer],  # reviewer NOT in participants
    ...
)
```

This is useful for:
- Restricting which agents can be called in a specific run
- Creating isolated teams within a larger agent pool
- Enforcing role boundaries

Both parameters work with `run()`, `async_run()`, `run_background()`, and `run_background_sync()`.

---

### Parallel Output Format

When multiple agents run in parallel (via `starting_agents` or `call_agent`), their results are returned with XML-style tags for clear attribution:

```python
# Single agent run — plain output
result = run(message="...", starting_agents=[researcher])
# result.output = "Research findings..."

# Multiple parallel agents — tagged output
result = run(
    message="...",
    starting_agents=[researcher, writer, reviewer],
)
# result.output =
# [researcher]Research findings...[/researcher]
# [writer]Written report...[/writer]
# [reviewer]Review complete...[/reviewer]
```

The same format applies to `call_agent` results:

```python
# Within an agent, calling another agent returns tagged output
call_agent(agent_name="writer", message="Write a summary")
# Returns: "[writer]Summary text...[/writer]"
```

This ensures the user (treated as an agent without an LLM) can parse and understand which agent produced which output.

---

### Debug Mode (Optional)

For structured event logs and call tree visualization, enable `debug=True`:

```python
result = run(..., debug=True)

# Print the call tree
print(result.format_trace())

# Access event log for filtering by agent or event type
events = result.event_log.filter(event_type="agent_call")
for e in events:
    print(f"{e.agent_name}: {e.call_id[:8]} from parent={e.parent_call_id}")
```

Debug mode is optional — basic call tracking via `call_id` in `RunResult.messages` works without it.

See [`ai-docs/MESSAGE_PROTOCOL.md`](./ai-docs/MESSAGE_PROTOCOL.md#10-병렬로-호출된-동일-이름-에이전트-추적) for detailed tracking documentation.

---

## Supported Providers

| Kind | Provider | Example Models | Compatible With |
|------|----------|----------------|-----------------|
| `"openai"` | OpenAI Chat Completions API | `gpt-5.2`, `gpt-5.3-codex`, `o3`, `o4-mini` | vLLM, Ollama, LM Studio, any OpenAI-compatible API |
| `"openai_responses"` | OpenAI Responses API | `gpt-5.2`, `gpt-5.3-codex`, `o3`, `o4-mini` | — |
| `"anthropic"` | Anthropic API | `claude-opus-4-6`, `claude-sonnet-4-6` | AWS Bedrock, Google Vertex AI, Ollama, LiteLLM, any Anthropic-compatible API |
| `"google"` | Google Gemini API | `gemini-3.1-pro`, `gemini-3-flash` | — |

---

## Async Usage

```python
import asyncio
from agentouto import async_run

result = await async_run(
    message="Write an AI trends report.",
    starting_agents=[researcher, writer, reviewer],
    tools=[search_web, write_file],
    providers=[openai, anthropic, google],
)
```

You can also pass conversation history and extra instructions:

```python
result = await async_run(
    message="Continue the report.",
    starting_agents=[writer, researcher],
    tools=[],
    providers=[openai],
    history=previous_result.messages,  # Pass previous messages
    extra_instructions="Use a professional tone.",  # Inject into system prompt
)
```

### Streaming

```python
from agentouto import async_run_stream

async for event in async_run_stream(
    message="Write an AI trends report.",
    starting_agents=[researcher, writer, reviewer],
    tools=[search_web],
    providers=[openai, anthropic, google],
):
    if event.type == "token":
        print(event.data["token"], end="", flush=True)
    elif event.type == "finish":
        print(f"\n--- {event.agent_name} finished ---")
    # call_id and parent_call_id are available on all events for tracing
    print(f"[{event.type}] call_id={event.call_id[:8]} parent={event.parent_call_id}")
```

Streaming also supports history and extra instructions:

```python
async for event in async_run_stream(
    message="Continue writing.",
    starting_agents=[writer, researcher],
    tools=[],
    providers=[openai],
    history=previous_result.messages,
    extra_instructions="Focus on technical details.",  # Inject into system prompt
):
    ...
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
├── loop_manager.py      # Background agent loops, message queues, AgentLoopRegistry
├── streaming.py         # async_run_stream(), StreamEvent
├── event_log.py         # AgentEvent, EventLog — structured event recording
├── tracing.py           # Trace, Span — call tree builder from event logs
├── _constants.py        # Shared constants (CALL_AGENT, FINISH)
├── exceptions.py        # ProviderError, AgentError, ToolError, RoutingError, AuthError
├── auth/
│   ├── __init__.py      # AuthMethod ABC, TokenData, TokenStore, OAuth implementations
│   ├── api_key.py       # ApiKeyAuth — static API key wrapper
│   ├── openai_oauth.py  # OpenAIOAuth — OpenAI ChatGPT subscription OAuth
│   ├── claude_oauth.py  # ClaudeOAuth — Anthropic Claude OAuth (⚠️ TOS restricted)
│   ├── google_oauth.py  # GoogleOAuth — Google Gemini/Antigravity OAuth (⚠️ TOS restricted)
│   ├── token_store.py   # TokenStore — secure token persistence (~/.agentouto/tokens/)
│   └── _oauth_common.py # PKCE, local callback server, browser auth, token exchange
└── providers/
    ├── __init__.py      # ProviderBackend ABC, LLMResponse, get_backend()
    ├── openai.py        # OpenAI Chat Completions (+ compatible APIs) implementation
    ├── openai_responses.py  # OpenAI Responses API implementation
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
| **13** | OpenAI Responses API backend (`openai_responses`) + tool-result attachment routing | ✅ Done |
| **15** | OAuth authentication (OpenAI, Claude, Google) | ✅ Done |
| **16** | Conversation history (`history` parameter) | ✅ Done |
| **17** | Background execution + inter-agent messaging | ✅ Done |
| **18** | Background streaming + unified API (send_message, get_agent_status, run_background) | ✅ Done |
| **19** | Runtime extra_instructions injection (extra_instructions + extra_instructions_scope parameters) | ✅ Done |
| **20** | Starting agents (all parallel) + visibility scoping (run_agents) + tagged output format | ✅ Done |
| **21** | Built-in tool override/disable (`disabled_tools` parameter) | ✅ Done |
| **22** | Intermediate messages (`on_message` callback, `user_message` StreamEvent) | ✅ Done |

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
