from __future__ import annotations

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

_OPENAI_AUTH_URL = "https://auth.openai.com/oauth/authorize"
_OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"

_DEFAULT_SCOPES = "openid profile email offline_access"


class OpenAIOAuth(AuthMethod):
    """OAuth 2.0 + PKCE authentication for OpenAI (ChatGPT Plus/Pro subscription).

    Allows using your ChatGPT subscription for API access via OAuth,
    similar to how Codex CLI authenticates.

    Usage::

        auth = OpenAIOAuth(client_id="your-client-id")
        await auth.ensure_authenticated()  # Opens browser for login
        token = await auth.get_token()     # Returns valid access token
    """

    def __init__(
        self,
        client_id: str,
        *,
        scopes: str = _DEFAULT_SCOPES,
        auth_url: str = _OPENAI_AUTH_URL,
        token_url: str = _OPENAI_TOKEN_URL,
        store_name: str = "openai_oauth",
        token_store: TokenStore | None = None,
    ) -> None:
        self._client_id = client_id
        self._scopes = scopes
        self._auth_url = auth_url
        self._token_url = token_url
        self._store_name = store_name
        self._token_store = token_store or TokenStore()
        self._tokens: TokenData | None = None

    async def get_token(self) -> str:
        if self._tokens is None:
            self._tokens = self._token_store.load(self._store_name)
        if self._tokens is None:
            raise AuthError(
                "openai", "Not authenticated. Call ensure_authenticated() first."
            )
        if self._is_expired():
            await self._refresh()
        return self._tokens.access_token

    async def ensure_authenticated(self) -> None:
        self._tokens = self._token_store.load(self._store_name)
        if self._tokens is not None:
            if not self._is_expired():
                logger.info("OpenAI OAuth: Using cached tokens")
                return
            if self._tokens.refresh_token:
                try:
                    await self._refresh()
                    return
                except Exception:
                    logger.warning("OpenAI OAuth: Token refresh failed, re-authenticating")

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
            raise AuthError("openai", "No refresh token available")

        logger.info("OpenAI OAuth: Refreshing access token")
        result = await refresh_access_token(
            self._token_url,
            self._tokens.refresh_token,
            self._client_id,
        )
        self._tokens = TokenData(
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token", self._tokens.refresh_token),
            expires_at=time.time() + result.get("expires_in", 900),
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

        logger.info("OpenAI OAuth: Starting authentication flow")
        print("\n🔐 OpenAI OAuth: Opening browser for authentication...")
        print(f"   If the browser doesn't open, visit: {authorize_url}\n")
        open_browser(authorize_url)

        auth_code, returned_state, error = await wait_for_callback(port)

        if error:
            raise AuthError("openai", f"OAuth failed: {error}")
        if auth_code is None:
            raise AuthError("openai", "No authorization code received (timeout)")
        if returned_state != state:
            raise AuthError("openai", "State mismatch — possible CSRF attack")

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
            expires_at=time.time() + result.get("expires_in", 900),
            scopes=self._scopes.split(),
        )
        self._token_store.save(self._store_name, self._tokens)
        logger.info("OpenAI OAuth: Authentication successful")
        print("✅ OpenAI OAuth: Authentication successful!\n")
