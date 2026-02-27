from __future__ import annotations

from agentouto.auth import AuthMethod


class ApiKeyAuth(AuthMethod):
    """Static API key authentication (backward-compatible wrapper)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def get_token(self) -> str:
        return self._api_key

    async def ensure_authenticated(self) -> None:
        if not self._api_key:
            raise ValueError("API key is not set")

    @property
    def is_authenticated(self) -> bool:
        return bool(self._api_key)
