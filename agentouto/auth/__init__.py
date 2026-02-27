from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenData:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    scopes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class AuthMethod(ABC):
    @abstractmethod
    async def get_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        ...

    @abstractmethod
    async def ensure_authenticated(self) -> None:
        """Run the authentication flow if not already authenticated."""
        ...

    @property
    @abstractmethod
    def is_authenticated(self) -> bool:
        """Whether valid credentials are currently available."""
        ...


from agentouto.auth.api_key import ApiKeyAuth  # noqa: E402
from agentouto.auth.claude_oauth import ClaudeOAuth  # noqa: E402
from agentouto.auth.google_oauth import GoogleOAuth  # noqa: E402
from agentouto.auth.openai_oauth import OpenAIOAuth  # noqa: E402
from agentouto.auth.token_store import TokenStore  # noqa: E402

__all__ = [
    "AuthMethod",
    "ApiKeyAuth",
    "ClaudeOAuth",
    "GoogleOAuth",
    "OpenAIOAuth",
    "TokenData",
    "TokenStore",
]
