from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

EventType = Literal[
    "llm_call",
    "llm_response",
    "tool_exec",
    "agent_call",
    "agent_return",
    "finish",
    "error",
]


@dataclass
class AgentEvent:
    event_type: EventType
    agent_name: str
    call_id: str
    parent_call_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)


class EventLog:
    def __init__(self) -> None:
        self._events: list[AgentEvent] = []

    def record(self, event: AgentEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[AgentEvent]:
        return list(self._events)

    def __iter__(self) -> Iterator[AgentEvent]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def filter(
        self,
        agent_name: str | None = None,
        event_type: EventType | None = None,
    ) -> list[AgentEvent]:
        result = self._events
        if agent_name is not None:
            result = [e for e in result if e.agent_name == agent_name]
        if event_type is not None:
            result = [e for e in result if e.event_type == event_type]
        return result

    def format(self) -> str:
        lines: list[str] = []
        for e in self._events:
            tag = f"[{e.agent_name}]"
            cid = e.call_id[:8]
            lines.append(f"{tag:20s} {e.event_type:16s} cid={cid}")
            for k, v in e.details.items():
                val = str(v)
                if len(val) > 120:
                    val = val[:120] + "..."
                lines.append(f"{'':20s}   {k}={val}")
        return "\n".join(lines)
