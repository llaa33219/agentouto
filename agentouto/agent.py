from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Agent:
    name: str
    instructions: str
    model: str
    provider: str
    max_output_tokens: int | None = None
    reasoning: bool = False
    reasoning_effort: str = "medium"
    reasoning_budget: int | None = None
    temperature: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)
