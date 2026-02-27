from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger("agentouto")


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_browser(url: str) -> None:
    """Open a URL in the user's default browser."""
    logger.info("Opening browser: %s", url)
    webbrowser.open(url)


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback parameters."""

    auth_code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "error" in params:
            _CallbackHandler.error = params["error"][0]
        elif "code" in params:
            _CallbackHandler.auth_code = params["code"][0]
            _CallbackHandler.state = params.get("state", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if _CallbackHandler.error:
            body = (
                "<html><body><h2>Authentication Failed</h2>"
                f"<p>Error: {_CallbackHandler.error}</p>"
                "<p>You can close this window.</p></body></html>"
            )
        else:
            body = (
                "<html><body><h2>Authentication Successful!</h2>"
                "<p>You can close this window and return to the terminal.</p>"
                "</body></html>"
            )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("OAuth callback: " + format, *args)


async def wait_for_callback(
    port: int, timeout: float = 120.0,
) -> tuple[str | None, str | None, str | None]:
    """Start a local HTTP server and wait for the OAuth callback.

    Returns (auth_code, state, error).
    """
    _CallbackHandler.auth_code = None
    _CallbackHandler.state = None
    _CallbackHandler.error = None

    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 1.0

    def _serve() -> None:
        while _CallbackHandler.auth_code is None and _CallbackHandler.error is None:
            server.handle_request()

    thread = Thread(target=_serve, daemon=True)
    thread.start()

    elapsed = 0.0
    interval = 0.5
    while elapsed < timeout:
        if _CallbackHandler.auth_code is not None or _CallbackHandler.error is not None:
            break
        await asyncio.sleep(interval)
        elapsed += interval

    server.server_close()

    if _CallbackHandler.auth_code is None and _CallbackHandler.error is None:
        return None, None, "timeout"

    return _CallbackHandler.auth_code, _CallbackHandler.state, _CallbackHandler.error


async def exchange_token(
    token_url: str,
    params: dict[str, str],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens via HTTP POST."""
    request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        request_headers.update(headers)

    try:
        import aiohttp
    except ModuleNotFoundError:
        raise ModuleNotFoundError(
            "aiohttp is required for OAuth authentication. "
            "Install it with: pip install agentouto[oauth]"
        ) from None

    async with aiohttp.ClientSession() as session:
        async with session.post(
            token_url, data=params, headers=request_headers,
        ) as resp:
            body = await resp.json()
            if resp.status != 200:
                from agentouto.exceptions import AuthError
                error_desc = body.get("error_description", body.get("error", "unknown"))
                raise AuthError("oauth", f"Token exchange failed ({resp.status}): {error_desc}")
            return body


async def refresh_access_token(
    token_url: str,
    refresh_token: str,
    client_id: str,
    client_secret: str | None = None,
) -> dict[str, Any]:
    """Refresh an expired access token."""
    params: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        params["client_secret"] = client_secret
    return await exchange_token(token_url, params)


def build_authorize_url(
    auth_url: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    scope: str,
    state: str | None = None,
    extra_params: dict[str, str] | None = None,
) -> str:
    """Build the OAuth authorization URL."""
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": scope,
    }
    if state:
        params["state"] = state
    if extra_params:
        params.update(extra_params)
    return f"{auth_url}?{urlencode(params)}"
