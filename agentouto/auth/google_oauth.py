from __future__ import annotations

# ┌─────────────────────────────────────────────────────────────────────────┐
# │  ⚠️  GOOGLE ANTIGRAVITY TOS RESTRICTION NOTICE                         │
# │                                                                         │
# │  Google restricts the use of Antigravity/Gemini OAuth tokens in         │
# │  third-party applications.  Google has actively enforced this policy,   │
# │  permanently banning user accounts (including Gmail, Drive, and all     │
# │  other Google services) without prior warning.                          │
# │                                                                         │
# │  THIS MODULE IS PROVIDED FOR EDUCATIONAL/RESEARCH PURPOSES ONLY.       │
# │  USE AT YOUR OWN RISK.  The authors assume no liability for any        │
# │  consequences arising from the use of this code.                        │
# │                                                                         │
# │  For safe usage, create your OWN GCP OAuth 2.0 Client ID at            │
# │  https://console.cloud.google.com/ and use the Gemini API with your    │
# │  own project credentials, which is fully supported by Google.           │
# └─────────────────────────────────────────────────────────────────────────┘
#
# The following default Antigravity client_id is COMMENTED OUT due to
# Google's TOS restrictions.  Using the Antigravity client_id in third-party
# tools has resulted in permanent Google account bans (affecting Gmail,
# Drive, Photos, and ALL Google services).
#
# _ANTIGRAVITY_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
# _ANTIGRAVITY_CLIENT_SECRET = ""  # not publicly disclosed

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

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
_GOOGLE_TOKEN_URL = "https://accounts.google.com/o/oauth2/token"

_DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform "
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile"
)

_TOS_WARNING = (
    "⚠️  WARNING: Google restricts using Antigravity/Gemini OAuth tokens in "
    "third-party applications. Google has permanently banned accounts "
    "(including Gmail, Drive, and ALL Google services) for this. "
    "For safe usage, create your own GCP OAuth Client ID at "
    "https://console.cloud.google.com/"
)


class GoogleOAuth(AuthMethod):
    """OAuth 2.0 authentication for Google Gemini / Antigravity.

    ⚠️  **TOS WARNING**: Google restricts using Antigravity OAuth tokens in
    third-party apps. Account bans affect ALL Google services (Gmail, Drive,
    Photos, etc.).

    **Safe alternative**: Create your own OAuth 2.0 Client ID at
    https://console.cloud.google.com/ — this is fully supported by Google
    and provides free-tier access (60 rpm, 1000 rpd).

    Usage (with your own GCP credentials — safe)::

        auth = GoogleOAuth(
            client_id="your-gcp-client-id.apps.googleusercontent.com",
            client_secret="your-gcp-client-secret",
        )
        await auth.ensure_authenticated()
        token = await auth.get_token()

    Usage (with Antigravity credentials — risky, at your own risk)::

        # See commented-out _ANTIGRAVITY_CLIENT_ID above
        auth = GoogleOAuth(
            client_id="antigravity-client-id",
            client_secret="antigravity-secret",
            suppress_warning=True,  # You accept the risk
        )
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str = "",
        *,
        scopes: str = _DEFAULT_SCOPES,
        auth_url: str = _GOOGLE_AUTH_URL,
        token_url: str = _GOOGLE_TOKEN_URL,
        store_name: str = "google_oauth",
        token_store: TokenStore | None = None,
        suppress_warning: bool = False,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
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
                "google", "Not authenticated. Call ensure_authenticated() first."
            )
        if self._is_expired():
            await self._refresh()
        return self._tokens.access_token

    async def ensure_authenticated(self) -> None:
        self._show_warning()

        self._tokens = self._token_store.load(self._store_name)
        if self._tokens is not None:
            if not self._is_expired():
                logger.info("Google OAuth: Using cached tokens")
                return
            if self._tokens.refresh_token:
                try:
                    await self._refresh()
                    return
                except Exception:
                    logger.warning("Google OAuth: Token refresh failed, re-authenticating")

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
            raise AuthError("google", "No refresh token available")

        logger.info("Google OAuth: Refreshing access token")
        result = await refresh_access_token(
            self._token_url,
            self._tokens.refresh_token,
            self._client_id,
            self._client_secret or None,
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
            extra_params={"access_type": "offline", "prompt": "consent"},
        )

        logger.info("Google OAuth: Starting authentication flow")
        print("\n🔐 Google OAuth: Opening browser for authentication...")
        print(f"   If the browser doesn't open, visit: {authorize_url}\n")
        open_browser(authorize_url)

        auth_code, returned_state, error = await wait_for_callback(port)

        if error:
            raise AuthError("google", f"OAuth failed: {error}")
        if auth_code is None:
            raise AuthError("google", "No authorization code received (timeout)")
        if returned_state != state:
            raise AuthError("google", "State mismatch — possible CSRF attack")

        params: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": self._client_id,
            "code_verifier": code_verifier,
        }
        if self._client_secret:
            params["client_secret"] = self._client_secret

        result = await exchange_token(self._token_url, params)

        self._tokens = TokenData(
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token"),
            expires_at=time.time() + result.get("expires_in", 3600),
            scopes=self._scopes.split(),
        )
        self._token_store.save(self._store_name, self._tokens)
        logger.info("Google OAuth: Authentication successful")
        print("✅ Google OAuth: Authentication successful!\n")
