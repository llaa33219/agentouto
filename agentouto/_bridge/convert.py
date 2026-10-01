from __future__ import annotations

import base64
import binascii
from typing import Any

from coreouto import (
    AudioBlock,
    DocumentBlock,
    ImageBlock,
    Message as CoreMessage,
    TextBlock,
    ToolCall as CoreToolCall,
    ToolResult as CoreToolResult,
    Usage as CoreUsage,
    VideoBlock,
)

from agentouto.context import Attachment, Context, ContextMessage, ToolCall
from agentouto.message import Message
from agentouto.providers import Usage

_MEDIA_BLOCKS = (ImageBlock, VideoBlock, AudioBlock, DocumentBlock)


# --- Attachments <-> ContentBlocks ---


def _decode_attachment_data(data: str) -> bytes:
    """Decode an ``Attachment.data`` payload.

    Real payloads are base64, but development/test payloads are frequently not
    (e.g. ``"base64data"``). Decode leniently and fall back to the literal
    bytes so a malformed payload never crashes the loop.
    """
    for candidate in (data, data + "=" * (-len(data) % 4)):
        try:
            return base64.b64decode(candidate, validate=True)
        except (binascii.Error, ValueError):
            continue
    return data.encode("utf-8")


def _media_block(
    mime_type: str, data: bytes | None, url: str | None
) -> ImageBlock | VideoBlock | AudioBlock | DocumentBlock:
    if mime_type.startswith("image/"):
        return ImageBlock(data=data, url=url, mime_type=mime_type)
    if mime_type.startswith("video/"):
        return VideoBlock(data=data, url=url, mime_type=mime_type)
    if mime_type.startswith("audio/"):
        return AudioBlock(data=data, url=url, mime_type=mime_type)
    return DocumentBlock(data=data, url=url, mime_type=mime_type)


def _block_to_attachment(
    block: ImageBlock | VideoBlock | AudioBlock | DocumentBlock,
) -> Attachment:
    mime_type = block.mime_type or ""
    if block.data is not None:
        return Attachment(
            mime_type=mime_type,
            data=base64.b64encode(block.data).decode("ascii"),
        )
    return Attachment(mime_type=mime_type, url=block.url or "")


def attachments_to_blocks(
    attachments: list[Attachment] | None,
) -> list[ImageBlock | VideoBlock | AudioBlock | DocumentBlock]:
    if not attachments:
        return []
    return [
        _media_block(
            att.mime_type,
            _decode_attachment_data(att.data) if att.data is not None else None,
            att.url,
        )
        for att in attachments
    ]


def _split_content(
    content: str | list[Any],
) -> tuple[str, list[Attachment] | None]:
    if isinstance(content, str):
        return content, None
    text_parts: list[str] = []
    attachments: list[Attachment] = []
    for item in content:
        if isinstance(item, TextBlock):
            text_parts.append(item.text)
        elif isinstance(item, _MEDIA_BLOCKS):
            attachments.append(_block_to_attachment(item))
    return "".join(text_parts), attachments or None


def blocks_to_attachments(
    blocks: list[Any] | None,
) -> tuple[str, list[Attachment] | None]:
    return _split_content(list(blocks or []))


# --- Messages <-> ContextMessages ---


def user_core_message(
    content: str, attachments: list[Attachment] | None = None
) -> CoreMessage:
    if not attachments:
        return CoreMessage(role="user", content=content)
    blocks: list[Any] = [TextBlock(text=content)]
    blocks.extend(attachments_to_blocks(attachments))
    return CoreMessage(role="user", content=blocks)


def assistant_core_message(
    content: str | None, tool_calls: list[CoreToolCall] | None = None
) -> CoreMessage:
    return CoreMessage(
        role="assistant",
        content=content or "",
        tool_calls=list(tool_calls) if tool_calls else None,
    )


def tool_core_message(
    tool_call_id: str,
    tool_name: str,
    content: str,
    attachments: list[Attachment] | None = None,
) -> CoreMessage:
    if not attachments:
        return CoreMessage(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
        )
    blocks: list[Any] = [TextBlock(text=content)]
    blocks.extend(attachments_to_blocks(attachments))
    return CoreMessage(
        role="tool", content=blocks, tool_call_id=tool_call_id, name=tool_name
    )


def core_tool_call_to_tool_call(tc: CoreToolCall) -> ToolCall:
    return ToolCall(id=tc.id, name=tc.name, arguments=dict(tc.arguments))


def tool_call_to_core_tool_call(tc: ToolCall) -> CoreToolCall:
    return CoreToolCall(id=tc.id, name=tc.name, arguments=dict(tc.arguments))


def core_message_to_context_message(msg: CoreMessage) -> ContextMessage:
    content, attachments = _split_content(msg.content)
    if msg.role == "assistant":
        # coreouto's Message.content is non-optional; agentouto's is None for
        # tool-call-only turns. Keep the original wire shape.
        assistant_content: str | None = content or None
    else:
        assistant_content = content
    return ContextMessage(
        role=msg.role,
        content=assistant_content,
        tool_calls=[core_tool_call_to_tool_call(tc) for tc in msg.tool_calls]
        if msg.tool_calls
        else None,
        tool_call_id=msg.tool_call_id,
        tool_name=msg.name,
        attachments=attachments,
    )


def context_message_to_core_message(msg: ContextMessage) -> CoreMessage:
    if msg.role == "user":
        return user_core_message(msg.content or "", msg.attachments)
    if msg.role == "assistant":
        return assistant_core_message(
            msg.content,
            [tool_call_to_core_tool_call(tc) for tc in msg.tool_calls]
            if msg.tool_calls
            else None,
        )
    return tool_core_message(
        msg.tool_call_id or "",
        msg.tool_name or "",
        msg.content or "",
        msg.attachments,
    )


def context_from_coreouto(messages: list[CoreMessage]) -> Context:
    """Rebuild the agentouto ``Context`` a backend expects from coreouto messages."""
    system_prompt = ""
    if messages and messages[0].role == "system":
        first = messages[0]
        system_prompt, _ = _split_content(first.content)
    ctx = Context(system_prompt)
    for msg in messages:
        if msg.role == "system":
            continue
        _append_context_message(ctx, core_message_to_context_message(msg))
    return ctx


def build_context(system_prompt: str, messages: list[ContextMessage]) -> Context:
    ctx = Context(system_prompt)
    for msg in messages:
        _append_context_message(ctx, msg)
    return ctx


def _append_context_message(ctx: Context, msg: ContextMessage) -> None:
    if msg.role == "user":
        ctx.add_user(msg.content or "", attachments=msg.attachments)
    elif msg.role == "assistant":
        if msg.tool_calls:
            ctx.add_assistant_tool_calls(msg.tool_calls, msg.content)
        else:
            ctx.add_assistant_text(msg.content or "")
    elif msg.role == "tool":
        ctx.add_tool_result(
            msg.tool_call_id or "",
            msg.tool_name or "",
            msg.content or "",
            attachments=msg.attachments,
        )


def history_entry_to_core_message(msg: Message) -> CoreMessage:
    """Convert one agentouto protocol ``Message`` into a coreouto message.

    Mirrors the historic ``Runtime._add_message_to_context`` prefixing rules:
    forward messages become user turns, return messages become assistant turns.
    """
    if msg.type == "forward":
        if msg.sender == "user":
            return user_core_message(msg.content, msg.attachments)
        return user_core_message(
            f"[Forwarded from {msg.sender}]: {msg.content}", msg.attachments
        )
    return assistant_core_message(f"[Return from {msg.sender}]: {msg.content}")


# --- Tool results ---


def tool_result_to_core(
    tool_call_id: str, content: str, attachments: list[Attachment] | None
) -> CoreToolResult:
    if not attachments:
        return CoreToolResult(tool_call_id=tool_call_id, content=content)
    blocks: list[Any] = [TextBlock(text=content)]
    blocks.extend(attachments_to_blocks(attachments))
    return CoreToolResult(tool_call_id=tool_call_id, blocks=blocks)


# --- Usage / LLMResponse ---


def usage_to_core(usage: Usage | None) -> CoreUsage | None:
    if usage is None:
        return None
    return CoreUsage(
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def tool_calls_to_core(
    tool_calls: list[ToolCall] | None,
) -> list[CoreToolCall]:
    if not tool_calls:
        return []
    return [tool_call_to_core_tool_call(tc) for tc in tool_calls]