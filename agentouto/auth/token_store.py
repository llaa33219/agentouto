from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agentouto.auth import TokenData

logger = logging.getLogger("agentouto")

_DEFAULT_DIR = Path.home() / ".agentouto" / "tokens"


class TokenStore:
    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or _DEFAULT_DIR

    def _path(self, provider_name: str) -> Path:
        return self._dir / f"{provider_name}.json"

    def save(self, provider_name: str, tokens: TokenData) -> None:
        self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(provider_name)
        data: dict[str, Any] = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at,
            "scopes": tokens.scopes,
            "extra": tokens.extra,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        path.chmod(0o600)
        logger.debug("Saved tokens for %s to %s", provider_name, path)

    def load(self, provider_name: str) -> TokenData | None:
        path = self._path(provider_name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TokenData(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_at=data.get("expires_at"),
                scopes=data.get("scopes", []),
                extra=data.get("extra", {}),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Corrupt token file %s: %s", path, exc)
            return None

    def delete(self, provider_name: str) -> None:
        path = self._path(provider_name)
        if path.exists():
            path.unlink()
            logger.debug("Deleted tokens for %s", provider_name)
