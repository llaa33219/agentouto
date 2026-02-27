from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from agentouto.auth import AuthMethod


@dataclass
class Provider:
    name: str
    kind: Literal["openai", "openai_responses", "anthropic", "google"]
    api_key: str = ""
    base_url: str | None = None
    auth: AuthMethod | None = None

    async def resolve_api_key(self) -> str:
        """Return the API key or OAuth token to use for requests."""
        if self.auth is not None:
            return await self.auth.get_token()
        return self.api_key
