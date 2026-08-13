"""Contract tests: OAuth helpers, credential stores, API-key normalize (offline)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from xaikit import (
    DictCredentialStore,
    EnvCredentialStore,
    build_oauth_authorize_url,
    exchange_oauth_code,
    normalize_api_key,
    oauth_is_configured,
)

_AUTHORIZE = "https://auth.example.com/authorize"
_TOKEN = "https://auth.example.com/token"
_REDIRECT = "https://app.example.com/callback"


class _Capture:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
        def _post(url: str, **kwargs: Any) -> httpx.Response:
            self.calls.append({"url": url, **kwargs})
            if response.request is not None:
                return response
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr("xaikit.connect.httpx.post", _post)


def _token_ok(**payload: Any) -> httpx.Response:
    body = {"access_token": "tok-1", "token_type": "Bearer", **payload}
    return httpx.Response(
        200,
        json=body,
        request=httpx.Request("POST", _TOKEN),
    )


def test_build_oauth_authorize_url_params() -> None:
    url = build_oauth_authorize_url(
        client_id="  client-abc  ",
        redirect_uri=_REDIRECT,
        state="nonce-1",
        authorize_url=_AUTHORIZE + "?",
    )
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.example.com"
    assert parsed.path == "/authorize"
    qs = parse_qs(parsed.query)
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["openid"]
    assert qs["client_id"] == ["client-abc"]
    assert qs["redirect_uri"] == [_REDIRECT]
    assert qs["state"] == ["nonce-1"]


def test_build_oauth_authorize_url_custom_scope() -> None:
    url = build_oauth_authorize_url(
        client_id="client-abc",
        redirect_uri=_REDIRECT,
        state="s",
        authorize_url=_AUTHORIZE,
        scopes="openid profile",
    )
    assert parse_qs(urlparse(url).query)["scope"] == ["openid profile"]


def test_build_oauth_authorize_url_empty_scope_defaults_openid() -> None:
    url = build_oauth_authorize_url(
        client_id="client-abc",
        redirect_uri=_REDIRECT,
        state="s",
        authorize_url=_AUTHORIZE,
        scopes="",
    )
    assert parse_qs(urlparse(url).query)["scope"] == ["openid"]


def test_build_oauth_authorize_url_missing_client_id() -> None:
    with pytest.raises(ValueError, match="client_id"):
        build_oauth_authorize_url(
            client_id="  ",
            redirect_uri=_REDIRECT,
            state="s",
            authorize_url=_AUTHORIZE,
        )


def test_build_oauth_authorize_url_missing_authorize_url() -> None:
    with pytest.raises(ValueError, match="authorize_url"):
        build_oauth_authorize_url(
            client_id="client-abc",
            redirect_uri=_REDIRECT,
            state="s",
            authorize_url="  ",
        )


def test_oauth_is_configured() -> None:
    assert oauth_is_configured(client_id="id", client_secret="secret") is True
    assert oauth_is_configured(client_id="  id  ", client_secret="  secret  ") is True
    assert oauth_is_configured(client_id="", client_secret="secret") is False
    assert oauth_is_configured(client_id="id", client_secret="  ") is False
    assert oauth_is_configured(client_id=None, client_secret="secret") is False
    assert oauth_is_configured(client_id="id", client_secret=None) is False


def test_normalize_api_key() -> None:
    assert normalize_api_key("  sk-test  ") == "sk-test"
    assert normalize_api_key("   ") is None
    assert normalize_api_key(None) is None
    assert normalize_api_key("") is None


def test_exchange_oauth_code_posts_form_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _Capture()
    cap.install(monkeypatch, _token_ok(refresh_token="ref-1", expires_in=3600))

    payload = exchange_oauth_code(
        "  auth-code  ",
        client_id=" client-abc ",
        client_secret=" client-secret ",
        redirect_uri=_REDIRECT,
        token_url=_TOKEN,
        timeout=12.0,
    )

    assert payload["access_token"] == "tok-1"
    assert payload["refresh_token"] == "ref-1"
    assert len(cap.calls) == 1
    call = cap.calls[0]
    assert call["url"] == _TOKEN
    assert call["headers"]["Accept"] == "application/json"
    assert call["timeout"] == 12.0
    assert call["data"] == {
        "grant_type": "authorization_code",
        "code": "auth-code",
        "redirect_uri": _REDIRECT,
        "client_id": "client-abc",
        "client_secret": "client-secret",
    }


def test_exchange_oauth_code_empty_code_skips_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _Capture()
    cap.install(monkeypatch, _token_ok())
    with pytest.raises(ValueError, match="Authorization code"):
        exchange_oauth_code(
            "  ",
            client_id="id",
            client_secret="secret",
            redirect_uri=_REDIRECT,
            token_url=_TOKEN,
        )
    assert cap.calls == []


def test_exchange_oauth_code_missing_token_url_skips_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _Capture()
    cap.install(monkeypatch, _token_ok())
    with pytest.raises(ValueError, match="token_url"):
        exchange_oauth_code(
            "code",
            client_id="id",
            client_secret="secret",
            redirect_uri=_REDIRECT,
            token_url="  ",
        )
    assert cap.calls == []


def test_exchange_oauth_code_not_configured_skips_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _Capture()
    cap.install(monkeypatch, _token_ok())
    with pytest.raises(RuntimeError, match="not configured"):
        exchange_oauth_code(
            "code",
            client_id="",
            client_secret="secret",
            redirect_uri=_REDIRECT,
            token_url=_TOKEN,
        )
    assert cap.calls == []


def test_exchange_oauth_code_http_status_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            400,
            text="bad request",
            request=httpx.Request("POST", _TOKEN),
        ),
    )
    with pytest.raises(RuntimeError, match=r"OAuth token exchange failed \(400\)"):
        exchange_oauth_code(
            "code",
            client_id="id",
            client_secret="secret",
            redirect_uri=_REDIRECT,
            token_url=_TOKEN,
        )


def test_exchange_oauth_code_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.connect.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="OAuth token exchange failed"):
        exchange_oauth_code(
            "code",
            client_id="id",
            client_secret="secret",
            redirect_uri=_REDIRECT,
            token_url=_TOKEN,
        )


def test_exchange_oauth_code_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"not-json",
            request=httpx.Request("POST", _TOKEN),
        ),
    )
    with pytest.raises(RuntimeError, match="not JSON"):
        exchange_oauth_code(
            "code",
            client_id="id",
            client_secret="secret",
            redirect_uri=_REDIRECT,
            token_url=_TOKEN,
        )


def test_exchange_oauth_code_missing_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"token_type": "Bearer"},
            request=httpx.Request("POST", _TOKEN),
        ),
    )
    with pytest.raises(RuntimeError, match="access_token"):
        exchange_oauth_code(
            "code",
            client_id="id",
            client_secret="secret",
            redirect_uri=_REDIRECT,
            token_url=_TOKEN,
        )


def test_dict_store_subject_then_default_fallback() -> None:
    store = DictCredentialStore({None: "  default-key  ", "user-a": "  user-a-key  "})
    assert store.get_api_key("user-a") == "user-a-key"
    assert store.get_api_key("missing") == "default-key"
    assert store.get_api_key(None) == "default-key"


def test_dict_store_empty_string_default_key() -> None:
    store = DictCredentialStore({"": "empty-default"})
    assert store.get_api_key("nobody") == "empty-default"
    store.clear("")
    assert store.get_api_key() is None


def test_dict_store_set_and_clear() -> None:
    store = DictCredentialStore()
    store.set_api_key("  k1  ", subject="u1")
    assert store.get_api_key("u1") == "k1"
    with pytest.raises(ValueError, match="API key"):
        store.set_api_key("  ")
    store.clear("u1")
    assert store.get_api_key("u1") is None


def test_env_store_ignores_subject_app_level_only() -> None:
    env = EnvCredentialStore("  env-key  ")
    assert env.get_api_key() == "env-key"
    assert env.get_api_key("user-a") == "env-key"
    assert env.get_api_key("missing") == "env-key"
    assert EnvCredentialStore("  ").get_api_key() is None
    assert EnvCredentialStore(None).get_api_key("anyone") is None


def test_env_store_vs_dict_fallback() -> None:
    """Env is app-level only; Dict falls back from subject miss to default."""
    env = EnvCredentialStore("env-key")
    mapping = DictCredentialStore({"user-a": "user-a-key", None: "dict-default"})
    assert env.get_api_key("user-a") == "env-key"
    assert mapping.get_api_key("user-a") == "user-a-key"
    assert mapping.get_api_key("other") == "dict-default"
    assert env.get_api_key("other") == "env-key"
