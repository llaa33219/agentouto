from __future__ import annotations

import pytest

from agnetouto.event_log import AgentEvent, EventLog
from agnetouto.tracing import Span, Trace


def _make_event(
    event_type: str,
    agent_name: str,
    call_id: str,
    parent_call_id: str | None = None,
    timestamp: float = 0.0,
    **details: object,
) -> AgentEvent:
    return AgentEvent(
        event_type=event_type,  # type: ignore[arg-type]
        agent_name=agent_name,
        call_id=call_id,
        parent_call_id=parent_call_id,
        timestamp=timestamp,
        details=dict(details),
    )


# --- EventLog ---


class TestEventLog:
    def test_record_and_len(self) -> None:
        log = EventLog()
        assert len(log) == 0
        log.record(_make_event("agent_call", "a", "c1"))
        assert len(log) == 1
        log.record(_make_event("finish", "a", "c1"))
        assert len(log) == 2

    def test_iter(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1"))
        log.record(_make_event("finish", "a", "c1"))
        events = list(log)
        assert len(events) == 2
        assert events[0].event_type == "agent_call"
        assert events[1].event_type == "finish"

    def test_events_returns_copy(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1"))
        events = log.events
        events.append(_make_event("finish", "a", "c1"))
        assert len(log) == 1

    def test_format(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "researcher", "abcdef12", message="hello"))
        formatted = log.format()
        assert "[researcher]" in formatted
        assert "agent_call" in formatted
        assert "abcdef12"[:8] in formatted

    def test_filter_by_agent_name(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1"))
        log.record(_make_event("agent_call", "b", "c2"))
        log.record(_make_event("finish", "a", "c1"))
        filtered = log.filter(agent_name="a")
        assert len(filtered) == 2
        assert all(e.agent_name == "a" for e in filtered)

    def test_filter_by_event_type(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1"))
        log.record(_make_event("llm_call", "a", "c1"))
        log.record(_make_event("finish", "a", "c1"))
        filtered = log.filter(event_type="llm_call")
        assert len(filtered) == 1
        assert filtered[0].event_type == "llm_call"

    def test_filter_combined(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1"))
        log.record(_make_event("agent_call", "b", "c2"))
        log.record(_make_event("finish", "a", "c1"))
        filtered = log.filter(agent_name="a", event_type="finish")
        assert len(filtered) == 1
        assert filtered[0].agent_name == "a"
        assert filtered[0].event_type == "finish"


# --- Trace ---


class TestTrace:
    def test_empty_event_log(self) -> None:
        log = EventLog()
        trace = Trace(log)
        assert trace.root is None
        assert trace.print_tree() == "(empty trace)"

    def test_single_agent(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1", timestamp=1.0))
        log.record(_make_event("llm_call", "a", "c1", timestamp=1.1))
        log.record(_make_event("finish", "a", "c1", timestamp=2.0, result="done"))
        trace = Trace(log)
        assert trace.root is not None
        assert trace.root.agent_name == "a"
        assert trace.root.call_id == "c1"
        assert trace.root.duration > 0
        assert trace.root.result == "done"

    def test_parent_child_spans(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1", timestamp=1.0))
        log.record(_make_event("agent_call", "b", "c2", parent_call_id="c1", timestamp=1.5))
        log.record(_make_event("agent_return", "b", "c2", parent_call_id="c1", timestamp=2.0, result="sub"))
        log.record(_make_event("finish", "a", "c1", timestamp=3.0, result="main"))
        trace = Trace(log)
        assert trace.root is not None
        assert trace.root.agent_name == "a"
        assert len(trace.root.children) == 1
        child = trace.root.children[0]
        assert child.agent_name == "b"
        assert child.call_id == "c2"

    def test_tool_calls_in_span(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1", timestamp=1.0))
        log.record(_make_event("tool_exec", "a", "c1", tool_name="search", arguments={"q": "test"}))
        log.record(_make_event("finish", "a", "c1", timestamp=2.0))
        trace = Trace(log)
        assert trace.root is not None
        assert len(trace.root.tool_calls) == 1
        assert trace.root.tool_calls[0]["tool_name"] == "search"

    def test_print_tree_output(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "main_agent", "c1", timestamp=1.0))
        log.record(_make_event("tool_exec", "main_agent", "c1", tool_name="search"))
        log.record(_make_event("agent_call", "helper", "c2", parent_call_id="c1", timestamp=1.5))
        log.record(_make_event("agent_return", "helper", "c2", parent_call_id="c1", timestamp=2.0))
        log.record(_make_event("finish", "main_agent", "c1", timestamp=3.0))
        tree = Trace(log).print_tree()
        assert "main_agent" in tree
        assert "helper" in tree
        assert "⚡ search" in tree

    def test_parallel_children(self) -> None:
        log = EventLog()
        log.record(_make_event("agent_call", "a", "c1", timestamp=1.0))
        log.record(_make_event("agent_call", "b", "c2", parent_call_id="c1", timestamp=1.1))
        log.record(_make_event("agent_call", "c", "c3", parent_call_id="c1", timestamp=1.1))
        log.record(_make_event("agent_return", "b", "c2", parent_call_id="c1", timestamp=2.0))
        log.record(_make_event("agent_return", "c", "c3", parent_call_id="c1", timestamp=2.5))
        log.record(_make_event("finish", "a", "c1", timestamp=3.0))
        trace = Trace(log)
        assert trace.root is not None
        assert len(trace.root.children) == 2
        child_names = {c.agent_name for c in trace.root.children}
        assert child_names == {"b", "c"}


class TestSpan:
    def test_duration_zero_when_no_times(self) -> None:
        span = Span(agent_name="a", call_id="c1")
        assert span.duration == 0.0

    def test_duration_calculated(self) -> None:
        span = Span(agent_name="a", call_id="c1", start_time=1.0, end_time=3.5)
        assert span.duration == pytest.approx(2.5)
