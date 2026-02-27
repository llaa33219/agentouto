from __future__ import annotations

# ┌─────────────────────────────────────────────────────────────────────────┐
# │  ⚠️  ANTHROPIC TOS RESTRICTION NOTICE                                  │
# │                                                                         │
# │  Anthropic explicitly prohibits the use of Claude Pro/Max subscription  │
# │  OAuth tokens in third-party applications.  OAuth authentication is     │
# │  authorized ONLY for the official Claude Code CLI and claude.ai.        │
# │                                                                         │
# │  Using this module may result in account suspension or termination.     │
# │  Anthropic has actively enforced this policy, including legal action    │
# │  against third-party tools.                                             │
# │                                                                         │
# │  THIS MODULE IS PROVIDED FOR EDUCATIONAL/RESEARCH PURPOSES ONLY.       │
# │  USE AT YOUR OWN RISK.  The authors assume no liability for any        │
# │  consequences arising from the use of this code.                        │
# │                                                                         │
# │  For production use, please use an API key from console.anthropic.com. │
# └─────────────────────────────────────────────────────────────────────────┘
#
# The following default client_id is COMMENTED OUT due to Anthropic's TOS.
# If you have your own registered OAuth client, you may provide it directly.
#
# _DEFAULT_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

import logging
import secrets
import time

from agentouto.auth import AuthMethod, TokenData
from agentouto.exceptions import AuthError
from agentouto.auth._oauth_common import (
    build_authorize_url,
    exchange_token,
    find_free_port,
    generate_pkce,
    open_browser,
    refresh_access_token,
    wait_for_callback,
)
from agentouto.auth.token_store import TokenStore

logger = logging.getLogger("agentouto")

_ANTHROPIC_AUTH_URL = "https://claude.ai/oauth/authorize"
_ANTHROPIC_TOKEN_URL = "https://claude.ai/oauth/token"

_DEFAULT_SCOPES = "openid profile email offline_access"

_TOS_WARNING = (
    "⚠️  WARNING: Anthropic's Terms of Service prohibit using Claude Pro/Max "
    "subscription OAuth tokens in third-party applications. Using this "
    "authentication method may result in your account being suspended or "
    "terminated. Use API keys from console.anthropic.com for production use."
)


class ClaudeOAuth(AuthMethod):
    """OAuth 2.0 + PKCE authentication for Anthropic Claude.

    ⚠️  **TOS WARNING**: Anthropic explicitly prohibits using Claude Pro/Max
    subscription OAuth tokens outside of the official Claude Code CLI and
    claude.ai. Using this class may result in account suspension.

    For production use, please use an API key from console.anthropic.com.

    Usage (at your own risk)::

        auth = ClaudeOAuth(client_id="your-registered-client-id")
        await auth.ensure_authenticated()
        token = await auth.get_token()
    """

    def __init__(
        self,
        client_id: str,
        *,
        scopes: str = _DEFAULT_SCOPES,
        auth_url: str = _ANTHROPIC_AUTH_URL,
        token_url: str = _ANTHROPIC_TOKEN_URL,
        store_name: str = "claude_oauth",
        token_store: TokenStore | None = None,
        suppress_warning: bool = False,
    ) -> None:
        self._client_id = client_id
        self._scopes = scopes
        self._auth_url = auth_url
        self._token_url = token_url
        self._store_name = store_name
        self._token_store = token_store or TokenStore()
        self._tokens: TokenData | None = None
        self._warning_shown = suppress_warning

    def _show_warning(self) -> None:
        if not self._warning_shown:
            logger.warning(_TOS_WARNING)
            print(f"\n{_TOS_WARNING}\n")
            self._warning_shown = True

    async def get_token(self) -> str:
        self._show_warning()
        if self._tokens is None:
            self._tokens = self._token_store.load(self._store_name)
        if self._tokens is None:
            raise AuthError(
                "anthropic", "Not authenticated. Call ensure_authenticated() first."
            )
        if self._is_expired():
            await self._refresh()
        return self._tokens.access_token

    async def ensure_authenticated(self) -> None:
        self._show_warning()

        self._tokens = self._token_store.load(self._store_name)
        if self._tokens is not None:
            if not self._is_expired():
                logger.info("Claude OAuth: Using cached tokens")
                return
            if self._tokens.refresh_token:
                try:
                    await self._refresh()
                    return
                except Exception:
                    logger.warning("Claude OAuth: Token refresh failed, re-authenticating")

        await self._run_auth_flow()

    @property
    def is_authenticated(self) -> bool:
        if self._tokens is None:
            self._tokens = self._token_store.load(self._store_name)
        return self._tokens is not None and not self._is_expired()

    def _is_expired(self) -> bool:
        if self._tokens is None or self._tokens.expires_at is None:
            return True
        return time.time() >= self._tokens.expires_at - 60

    async def _refresh(self) -> None:
        if self._tokens is None or self._tokens.refresh_token is None:
            raise AuthError("anthropic", "No refresh token available")

        logger.info("Claude OAuth: Refreshing access token")
        result = await refresh_access_token(
            self._token_url,
            self._tokens.refresh_token,
            self._client_id,
        )
        self._tokens = TokenData(
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token", self._tokens.refresh_token),
            expires_at=time.time() + result.get("expires_in", 3600),
            scopes=self._scopes.split(),
        )
        self._token_store.save(self._store_name, self._tokens)

    async def _run_auth_flow(self) -> None:
        port = find_free_port()
        redirect_uri = f"http://localhost:{port}/callback"
        code_verifier, code_challenge = generate_pkce()
        state = secrets.token_urlsafe(32)

        authorize_url = build_authorize_url(
            auth_url=self._auth_url,
            client_id=self._client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=self._scopes,
            state=state,
        )

        logger.info("Claude OAuth: Starting authentication flow")
        print("\n🔐 Claude OAuth: Opening browser for authentication...")
        print(f"   If the browser doesn't open, visit: {authorize_url}\n")
        open_browser(authorize_url)

        auth_code, returned_state, error = await wait_for_callback(port)

        if error:
            raise AuthError("anthropic", f"OAuth failed: {error}")
        if auth_code is None:
            raise AuthError("anthropic", "No authorization code received (timeout)")
        if returned_state != state:
            raise AuthError("anthropic", "State mismatch — possible CSRF attack")

        result = await exchange_token(
            self._token_url,
            {
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "client_id": self._client_id,
                "code_verifier": code_verifier,
            },
        )

        self._tokens = TokenData(
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token"),
            expires_at=time.time() + result.get("expires_in", 3600),
            scopes=self._scopes.split(),
        )
        self._token_store.save(self._store_name, self._tokens)
        logger.info("Claude OAuth: Authentication successful")
        print("✅ Claude OAuth: Authentication successful!\n")
