"""OAuth + API-key connect helpers (config dicts / params — no User/Session)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


def oauth_is_configured(
    *,
    client_id: str | None,
    client_secret: str | None,
) -> bool:
    """True when OAuth client id + secret are both non-empty."""
    return bool((client_id or "").strip() and (client_secret or "").strip())


def build_oauth_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    authorize_url: str,
    scopes: str = "openid",
) -> str:
    """Build the xAI (or compatible) authorization-code URL."""
    cid = (client_id or "").strip()
    if not cid:
        raise ValueError("client_id is required")
    base = (authorize_url or "").strip().rstrip("?")
    if not base:
        raise ValueError("authorize_url is required")
    params = {
        "client_id": cid,
        "redirect_uri": (redirect_uri or "").strip(),
        "response_type": "code",
        "scope": (scopes or "openid").strip(),
        "state": state,
    }
    return f"{base}?{urlencode(params)}"


def exchange_oauth_code(
    code: str,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    token_url: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Exchange authorization code for tokens.

    Returns raw token payload (access_token, refresh_token, expires_in, …).
    """
    if not oauth_is_configured(client_id=client_id, client_secret=client_secret):
        raise RuntimeError("xAI OAuth is not configured (client_id/secret missing)")
    cleaned = (code or "").strip()
    if not cleaned:
        raise ValueError("Authorization code is required")
    url = (token_url or "").strip()
    if not url:
        raise ValueError("token_url is required")

    data = {
        "grant_type": "authorization_code",
        "code": cleaned,
        "redirect_uri": (redirect_uri or "").strip(),
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
    }
    try:
        response = httpx.post(
            url,
            data=data,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        logger.exception("xAI OAuth token exchange request failed")
        raise RuntimeError(f"OAuth token exchange failed: {exc}") from exc

    if response.status_code >= 400:
        detail = (response.text or response.reason_phrase or "")[:300]
        logger.error("xAI OAuth token exchange HTTP %s: %s", response.status_code, detail)
        raise RuntimeError(f"OAuth token exchange failed ({response.status_code})")

    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("OAuth token response was not JSON") from exc

    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("OAuth token response missing access_token")
    return payload


def normalize_api_key(api_key: str | None) -> str | None:
    """Strip and return API key, or None if empty."""
    cleaned = (api_key or "").strip()
    return cleaned or None
