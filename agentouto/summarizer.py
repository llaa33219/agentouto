from __future__ import annotations

from agentouto.context import Context, ContextMessage

_SUMMARIZE_THRESHOLD = 0.70  # 70% of context window triggers self-summarization
_KEEP_RATIO = 0.3

_SUMMARIZE_SYSTEM = (
    "You are a summarization assistant. Your task is to summarize the conversation history "
    "below into a concise form that preserves key facts, decisions, tool call results, "
    "and important context. "
    "Focus on information that would be needed to continue this conversation meaningfully."
)


def needs_summarization(context: Context, context_window: int) -> bool:
    tokens = estimate_context_tokens(context)
    return tokens > int(context_window * _SUMMARIZE_THRESHOLD)


def build_self_summarize_context(messages_to_summarize: list[ContextMessage], system_prompt: str) -> Context:
    prompt = build_summary_prompt(messages_to_summarize)
    full_prompt = f"""{_SUMMARIZE_SYSTEM}

Below is the conversation history to summarize:

{prompt}

Please provide a concise summary that preserves:
- Key facts and decisions
- Important tool call results
- Context needed to continue the conversation
- Any pending tasks or goals

Summary:"""
    ctx = Context(system_prompt)
    ctx.add_user(full_prompt)
    return ctx


def estimate_context_tokens(context: Context) -> int:
    total = len(context.system_prompt) // 4
    for msg in context.messages:
        total += _estimate_message_tokens(msg)
    return total


def _estimate_message_tokens(msg: ContextMessage) -> int:
    tokens = 0
    if msg.content:
        tokens += len(msg.content) // 4
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tokens += len(tc.name) // 4
            tokens += len(str(tc.arguments)) // 4
    if msg.tool_call_id:
        tokens += 4
    return max(tokens, 1)


def find_summarization_boundary(
    messages: list[ContextMessage], context_window: int
) -> int | None:
    if len(messages) <= 2:
        return None

    keep_budget = int(context_window * _KEEP_RATIO)
    accumulated = 0
    candidate = len(messages)

    for i in range(len(messages) - 1, -1, -1):
        accumulated += _estimate_message_tokens(messages[i])
        if accumulated >= keep_budget:
            candidate = i + 1
            break
    else:
        return None

    candidate = min(candidate, len(messages) - 2)

    while candidate > 0 and messages[candidate].role == "tool":
        candidate -= 1

    if candidate <= 0:
        return None

    return candidate


def build_summary_prompt(messages: list[ContextMessage]) -> str:
    lines: list[str] = []
    for msg in messages:
        if msg.role == "user":
            lines.append(f"User: {msg.content or ''}")
        elif msg.role == "assistant":
            if msg.tool_calls:
                calls = ", ".join(
                    f"{tc.name}({tc.arguments})" for tc in msg.tool_calls
                )
                lines.append(f"Assistant: [Called tools: {calls}]")
                if msg.content:
                    lines.append(f"  Text: {msg.content}")
            else:
                lines.append(f"Assistant: {msg.content or ''}")
        elif msg.role == "tool":
            name = msg.tool_name or "unknown"
            lines.append(f"Tool result ({name}): {msg.content or ''}")
    return "\n".join(lines)
