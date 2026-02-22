from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from agentouto.context import Attachment


@dataclass
class Message:
    type: Literal["forward", "return"]
    sender: str
    receiver: str
    content: str
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    attachments: list[Attachment] | None = None
