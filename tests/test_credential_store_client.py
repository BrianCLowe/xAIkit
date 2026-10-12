"""XaiClient credential store: loopback embeddings, fake keys only."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from xaikit import (
    AsyncXaiClient,
    DictCredentialStore,
    EnvCredentialStore,
    XaiClient,
    default_retry_policy,
)

_EMBED_BODY = (
    b'{"object":"list","model":"v1","data":[{"index":0,"embedding":[0.1],'
    b'"object":"embedding"}],"usage":{"prompt_tokens":1,"total_tokens":1}}'
)


class _Loopback:
    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                parent.requests.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization") or "",
                    }
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(_EMBED_BODY)))
                self.end_headers()
                self.wfile.write(_EMBED_BODY)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        host, port = self._httpd.server_address[:2]
        self.url = f"http://{host}:{port}/v1/embeddings"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


@pytest.fixture
def loopback() -> Iterator[_Loopback]:
    server = _Loopback()
    try:
        yield server
    finally:
        server.close()


def _close_client(client: XaiClient) -> None:
    sdk = getattr(client, "_client", None)
    if sdk is not None and hasattr(sdk, "close"):
        sdk.close()


@contextmanager
def _client(
    monkeypatch: pytest.MonkeyPatch,
    loopback: _Loopback,
    **kwargs: Any,
) -> Iterator[XaiClient]:
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    client = XaiClient(
        provider=None,
        model="grok-3-mini",
        image_model="grok-imagine-image",
        video_model="grok-imagine-video",
        voice_model="grok-voice-think-fast-1.0",
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )
    try:
        yield client
    finally:
        _close_client(client)


def _embed(client: XaiClient) -> None:
    client.embed("hi", model="v1")


def _assert_auth(loopback: _Loopback, authorization: str) -> None:
    assert loopback.requests == [
        {"path": "/v1/embeddings", "authorization": authorization}
    ]
    assert authorization != "Bearer mock"
    assert authorization != "Bearer"
    assert authorization != "Bearer "


def _assert_api_key_error(message: str) -> None:
    assert "api key" in message.lower()


def test_dict_store_subject_sends_stored_key(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore(
        {"user-a": "fake-user-a-key", None: "fake-default-key"}
    )
    with _client(monkeypatch, loopback, credential_store=store, subject="user-a") as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-user-a-key")


def test_dict_store_subject_miss_uses_default_key(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore(
        {"user-a": "fake-user-a-key", None: "fake-default-key"}
    )
    with _client(
        monkeypatch, loopback, credential_store=store, subject="missing-subject"
    ) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-default-key")


def test_dict_store_none_subject_uses_default_key(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore(
        {"user-a": "fake-user-a-key", None: "fake-default-key"}
    )
    with _client(monkeypatch, loopback, credential_store=store, subject=None) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-default-key")


def test_explicit_api_key_overrides_store(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore(
        {"user-a": "fake-user-a-key", None: "fake-default-key"}
    )
    with _client(
        monkeypatch,
        loopback,
        api_key="fake-explicit-key",
        credential_store=store,
        subject="user-a",
    ) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-explicit-key")


def test_env_store_reads_xai_api_key_at_construction(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "fake-env-key")
    store = EnvCredentialStore()
    monkeypatch.setenv("XAI_API_KEY", "fake-changed-after-build")
    with _client(monkeypatch, loopback, credential_store=store) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-env-key")


def test_env_store_custom_name(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("XAIKIT_FAKE_APP_KEY", "fake-custom-env-key")
    store = EnvCredentialStore(name="XAIKIT_FAKE_APP_KEY")
    monkeypatch.delenv("XAIKIT_FAKE_APP_KEY")
    with _client(monkeypatch, loopback, credential_store=store) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-custom-env-key")


def test_env_store_positional_key_ignores_environment(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "fake-env-key")
    store = EnvCredentialStore("fake-positional-key")
    with _client(monkeypatch, loopback, credential_store=store) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-positional-key")


def test_env_store_unset_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    with pytest.raises(RuntimeError) as excinfo:
        store = EnvCredentialStore()
        with _client(monkeypatch, loopback, credential_store=store) as client:
            _embed(client)
    message = str(excinfo.value)
    _assert_api_key_error(message)
    assert "XAI_API_KEY" in message
    assert loopback.requests == []


def test_env_store_empty_variable_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "   ")
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    with pytest.raises(RuntimeError) as excinfo:
        store = EnvCredentialStore()
        with _client(monkeypatch, loopback, credential_store=store) as client:
            _embed(client)
    message = str(excinfo.value)
    _assert_api_key_error(message)
    assert "XAI_API_KEY" in message
    assert loopback.requests == []


def test_env_store_custom_name_unset_names_that_variable(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "fake-env-key")
    monkeypatch.delenv("XAIKIT_FAKE_APP_KEY", raising=False)
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    with pytest.raises(RuntimeError) as excinfo:
        store = EnvCredentialStore(name="XAIKIT_FAKE_APP_KEY")
        with _client(monkeypatch, loopback, credential_store=store) as client:
            _embed(client)
    message = str(excinfo.value)
    _assert_api_key_error(message)
    assert "XAIKIT_FAKE_APP_KEY" in message
    assert "fake-env-key" not in message
    assert loopback.requests == []


def test_explicit_whitespace_is_trimmed(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    with _client(monkeypatch, loopback, api_key="  fake-ws-key  ") as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-ws-key")


def test_explicit_tab_and_newline_whitespace_is_trimmed(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    with _client(monkeypatch, loopback, api_key="\tfake-explicit-tab\n") as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-explicit-tab")


def test_env_store_whitespace_is_trimmed_on_the_request(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "\t fake-env-ws-key \n")
    store = EnvCredentialStore()
    with _client(monkeypatch, loopback, credential_store=store) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-env-ws-key")


def test_dict_store_whitespace_key_is_trimmed_on_the_request(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore({"user-a": "  fake-user-a-key  "})
    with _client(monkeypatch, loopback, credential_store=store, subject="user-a") as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-user-a-key")


@pytest.mark.parametrize(
    ("stored", "authorization"),
    [
        ("bearer fake-lower-key", "Bearer fake-lower-key"),
        ("BEARER fake-upper-key", "Bearer fake-upper-key"),
        ("BeArEr fake-mixed-key", "Bearer fake-mixed-key"),
        ("Bearer   fake-multi-key", "Bearer fake-multi-key"),
        ("Bearer\tfake-tab-key", "Bearer fake-tab-key"),
        ("Bearer \t fake-tab-space-key", "Bearer fake-tab-space-key"),
        ("  Bearer fake-b-key ", "Bearer fake-b-key"),
        ("BearerToken", "Bearer BearerToken"),
    ],
)
def test_dict_store_normalizes_bearer_prefix(
    monkeypatch: pytest.MonkeyPatch,
    loopback: _Loopback,
    stored: str,
    authorization: str,
) -> None:
    store = DictCredentialStore({None: stored})
    with _client(monkeypatch, loopback, credential_store=store, subject=None) as client:
        _embed(client)
    _assert_auth(loopback, authorization)


def test_explicit_api_key_bearer_prefix_beats_store(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore({None: "fake-stored-key"})
    with _client(
        monkeypatch,
        loopback,
        api_key="Bearer fake-explicit-key",
        credential_store=store,
    ) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-explicit-key")


def test_explicit_api_key_bearer_prefix_with_extra_whitespace(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    with _client(
        monkeypatch, loopback, api_key="  Bearer \t fake-explicit-pad  "
    ) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-explicit-pad")


def test_env_store_bare_bearer_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "Bearer")
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    store = EnvCredentialStore()
    with pytest.raises(RuntimeError) as excinfo:
        with _client(monkeypatch, loopback, credential_store=store) as client:
            _embed(client)
    _assert_api_key_error(str(excinfo.value))
    assert loopback.requests == []


def test_env_store_bearer_token_is_untouched(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "BearerToken")
    store = EnvCredentialStore()
    with _client(monkeypatch, loopback, credential_store=store) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer BearerToken")


def test_env_store_bearer_prefix_is_normalized(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "  bearer \t fake-env-bearer  ")
    store = EnvCredentialStore()
    with _client(monkeypatch, loopback, credential_store=store) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-env-bearer")


@pytest.mark.parametrize("raw", ["Bearer", "bearer", "BEARER", "  Bearer  ", "Bearer   "])
def test_bare_bearer_explicit_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback, raw: str
) -> None:
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    with pytest.raises(RuntimeError) as excinfo:
        with _client(monkeypatch, loopback, api_key=raw) as client:
            _embed(client)
    _assert_api_key_error(str(excinfo.value))
    assert loopback.requests == []


@pytest.mark.parametrize("raw", ["Bearer", "bearer", "BEARER", "  Bearer  "])
def test_bare_bearer_store_key_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback, raw: str
) -> None:
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    store = DictCredentialStore({None: raw})
    with pytest.raises(RuntimeError) as excinfo:
        with _client(monkeypatch, loopback, credential_store=store) as client:
            _embed(client)
    _assert_api_key_error(str(excinfo.value))
    assert loopback.requests == []


def test_empty_store_key_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    store = DictCredentialStore({None: "   ", "user-a": ""})
    with pytest.raises(RuntimeError) as excinfo:
        with _client(
            monkeypatch, loopback, credential_store=store, subject="user-a"
        ) as client:
            _embed(client)
    _assert_api_key_error(str(excinfo.value))
    assert loopback.requests == []


def test_store_key_strips_only_one_bearer_prefix(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore({None: "Bearer Bearer fake-x"})
    with _client(monkeypatch, loopback, credential_store=store) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer Bearer fake-x")


def test_explicit_bare_bearer_falls_through_to_store(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore({None: "fake-store-key"})
    with _client(
        monkeypatch, loopback, api_key="Bearer", credential_store=store
    ) as client:
        _embed(client)
    _assert_auth(loopback, "Bearer fake-store-key")


def test_explicit_bare_bearer_without_store_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    with pytest.raises(RuntimeError) as excinfo:
        with _client(monkeypatch, loopback, api_key="Bearer") as client:
            _embed(client)
    _assert_api_key_error(str(excinfo.value))
    assert loopback.requests == []


def test_positional_blank_env_store_does_not_read_environment(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "fake-env-key")
    monkeypatch.setattr("xaikit.client.XAI_EMBEDDINGS_URL", loopback.url)
    store = EnvCredentialStore("   ")
    with pytest.raises(RuntimeError) as excinfo:
        with _client(monkeypatch, loopback, credential_store=store) as client:
            _embed(client)
    _assert_api_key_error(str(excinfo.value))
    assert "fake-env-key" not in str(excinfo.value)
    assert loopback.requests == []


def _run_async_embed(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback, **kwargs: Any
) -> None:
    monkeypatch.setattr("xaikit.async_client.XAI_EMBEDDINGS_URL", loopback.url)

    async def _run() -> None:
        client = AsyncXaiClient(
            provider=None,
            model="grok-3-mini",
            image_model="grok-imagine-image",
            video_model="grok-imagine-video",
            voice_model="grok-voice-think-fast-1.0",
            retry_policy=default_retry_policy(max_attempts=1),
            **kwargs,
        )
        try:
            await client.embed("hi", model="v1")
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_async_dict_store_subject_sends_stored_key(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore(
        {"user-a": "fake-user-a-key", None: "fake-default-key"}
    )
    _run_async_embed(monkeypatch, loopback, credential_store=store, subject="user-a")
    _assert_auth(loopback, "Bearer fake-user-a-key")


def test_async_explicit_api_key_overrides_store(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore(
        {"user-a": "fake-user-a-key", None: "fake-default-key"}
    )
    _run_async_embed(
        monkeypatch,
        loopback,
        api_key="fake-explicit-key",
        credential_store=store,
        subject="user-a",
    )
    _assert_auth(loopback, "Bearer fake-explicit-key")


def test_async_explicit_api_key_bearer_prefix_beats_store(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore({None: "fake-stored-key"})
    _run_async_embed(
        monkeypatch,
        loopback,
        api_key="Bearer fake-explicit-key",
        credential_store=store,
    )
    _assert_auth(loopback, "Bearer fake-explicit-key")


@pytest.mark.parametrize(
    ("stored", "authorization"),
    [
        ("bearer fake-lower-key", "Bearer fake-lower-key"),
        ("BEARER fake-upper-key", "Bearer fake-upper-key"),
        ("BeArEr fake-mixed-key", "Bearer fake-mixed-key"),
        ("Bearer   fake-multi-key", "Bearer fake-multi-key"),
        ("Bearer\tfake-tab-key", "Bearer fake-tab-key"),
        ("Bearer \t fake-tab-space-key", "Bearer fake-tab-space-key"),
        ("  Bearer fake-b-key ", "Bearer fake-b-key"),
        ("BearerToken", "Bearer BearerToken"),
        ("Bearer Bearer fake-x", "Bearer Bearer fake-x"),
    ],
)
def test_async_dict_store_normalizes_bearer_prefix(
    monkeypatch: pytest.MonkeyPatch,
    loopback: _Loopback,
    stored: str,
    authorization: str,
) -> None:
    store = DictCredentialStore({None: stored})
    _run_async_embed(monkeypatch, loopback, credential_store=store, subject=None)
    _assert_auth(loopback, authorization)


def test_async_env_store_reads_xai_api_key_at_construction(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "fake-env-key")
    store = EnvCredentialStore()
    monkeypatch.setenv("XAI_API_KEY", "fake-changed-after-build")
    _run_async_embed(monkeypatch, loopback, credential_store=store)
    _assert_auth(loopback, "Bearer fake-env-key")


def test_async_env_store_bearer_prefix_is_normalized(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "  BEARER \t fake-env-bearer  ")
    store = EnvCredentialStore()
    _run_async_embed(monkeypatch, loopback, credential_store=store)
    _assert_auth(loopback, "Bearer fake-env-bearer")


def test_async_explicit_bare_bearer_falls_through_to_store(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    store = DictCredentialStore({None: "fake-store-key"})
    _run_async_embed(
        monkeypatch, loopback, api_key="Bearer", credential_store=store
    )
    _assert_auth(loopback, "Bearer fake-store-key")


def test_async_explicit_bare_bearer_without_store_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback
) -> None:
    monkeypatch.setattr("xaikit.async_client.XAI_EMBEDDINGS_URL", loopback.url)
    with pytest.raises(RuntimeError) as excinfo:
        _run_async_embed(monkeypatch, loopback, api_key="Bearer")
    _assert_api_key_error(str(excinfo.value))
    assert loopback.requests == []


@pytest.mark.parametrize("raw", ["Bearer", "bearer", "BEARER", "  Bearer  "])
def test_async_bare_bearer_store_key_raises_before_network(
    monkeypatch: pytest.MonkeyPatch, loopback: _Loopback, raw: str
) -> None:
    monkeypatch.setattr("xaikit.async_client.XAI_EMBEDDINGS_URL", loopback.url)
    store = DictCredentialStore({None: raw})
    with pytest.raises(RuntimeError) as excinfo:
        _run_async_embed(monkeypatch, loopback, credential_store=store)
    _assert_api_key_error(str(excinfo.value))
    assert loopback.requests == []
