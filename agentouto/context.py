from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Attachment:
    mime_type: str
    data: str | None = None
    url: str | None = None
    name: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ContextMessage:
    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    attachments: list[Attachment] | None = None


class Context:
    def __init__(self, system_prompt: str) -> None:
        self._system_prompt = system_prompt
        self._messages: list[ContextMessage] = []

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def messages(self) -> list[ContextMessage]:
        return list(self._messages)

    def add_user(self, content: str, attachments: list[Attachment] | None = None) -> None:
        self._messages.append(ContextMessage(role="user", content=content, attachments=attachments))

    def add_assistant_text(self, content: str) -> None:
        self._messages.append(ContextMessage(role="assistant", content=content))

    def add_assistant_tool_calls(self, tool_calls: list[ToolCall], content: str | None = None) -> None:
        self._messages.append(
            ContextMessage(role="assistant", content=content, tool_calls=tool_calls)
        )

    def add_tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        content: str,
        attachments: list[Attachment] | None = None,
    ) -> None:
        self._messages.append(
            ContextMessage(
                role="tool",
                content=content,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                attachments=attachments,
            )
        )
