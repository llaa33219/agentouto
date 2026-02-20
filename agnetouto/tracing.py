from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agnetouto.event_log import EventLog


@dataclass
class Span:
    agent_name: str
    call_id: str
    parent_call_id: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    children: list[Span] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    result: str | None = None

    @property
    def duration(self) -> float:
        if self.end_time <= 0 or self.start_time <= 0:
            return 0.0
        return self.end_time - self.start_time


class Trace:
    def __init__(self, event_log: EventLog) -> None:
        self._root: Span | None = None
        self._spans: dict[str, Span] = {}
        self._build(event_log)

    @property
    def root(self) -> Span | None:
        return self._root

    def _build(self, event_log: EventLog) -> None:
        for event in event_log:
            cid = event.call_id
            if cid not in self._spans:
                self._spans[cid] = Span(
                    agent_name=event.agent_name,
                    call_id=cid,
                    parent_call_id=event.parent_call_id,
                )
            span = self._spans[cid]

            if event.event_type == "agent_call":
                span.start_time = event.timestamp
            elif event.event_type in ("agent_return", "finish"):
                span.end_time = event.timestamp
                result = event.details.get("result")
                if result is not None:
                    span.result = str(result)
            elif event.event_type == "tool_exec":
                span.tool_calls.append(event.details)

        for span in self._spans.values():
            if span.parent_call_id and span.parent_call_id in self._spans:
                self._spans[span.parent_call_id].children.append(span)
            elif self._root is None:
                self._root = span

    def print_tree(self) -> str:
        if self._root is None:
            return "(empty trace)"
        lines: list[str] = []
        self._format_span(self._root, lines, "", True)
        return "\n".join(lines)

    def _format_span(
        self, span: Span, lines: list[str], prefix: str, is_last: bool
    ) -> None:
        connector = "└── " if is_last else "├── "
        dur = f"{span.duration:.2f}s" if span.duration > 0 else "..."
        lines.append(f"{prefix}{connector}[{span.agent_name}] ({dur})")

        child_prefix = prefix + ("    " if is_last else "│   ")

        for tc in span.tool_calls:
            name = tc.get("tool_name", "?")
            lines.append(f"{child_prefix}  ⚡ {name}")

        for i, child in enumerate(span.children):
            self._format_span(
                child, lines, child_prefix, i == len(span.children) - 1
            )
