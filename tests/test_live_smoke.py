"""Optional live xAI smokes — skipped unless XAITKIT_LIVE=1 and XAI_API_KEY.

Run from repo root::

    XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live -v
"""

from __future__ import annotations

import os

import pytest

from xaikit import (
    BOOTSTRAP_MODEL,
    EnvCredentialStore,
    InMemoryUsageSink,
    UsageMeter,
    XaiClient,
    cheapest_model,
    clear_catalog_cache,
    default_retry_policy,
    inject_catalog,
    list_models,
    set_test_fetch,
)

_RUN_LIVE = os.environ.get("XAITKIT_LIVE", "").strip().lower() in {"1", "true", "yes"}
_HAS_KEY = bool(os.environ.get("XAI_API_KEY", "").strip())

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _RUN_LIVE,
        reason="set XAITKIT_LIVE=1 to run live xAI smokes",
    ),
    pytest.mark.skipif(not _HAS_KEY, reason="XAI_API_KEY not set"),
]


@pytest.fixture(autouse=True)
def _reset_catalog() -> None:
    inject_catalog(None)
    set_test_fetch(None)
    clear_catalog_cache()
    yield
    inject_catalog(None)
    set_test_fetch(None)
    clear_catalog_cache()


@pytest.fixture(scope="module")
def api_key() -> str:
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    assert key
    return key


@pytest.fixture(scope="module")
def client(api_key: str) -> XaiClient:
    return XaiClient(
        credential_store=EnvCredentialStore(api_key),
        model=BOOTSTRAP_MODEL,
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )


def test_live_list_models_includes_bootstrap(api_key: str) -> None:
    models = list_models(api_key=api_key, force_refresh=True, allow_fixture_fallback=False)
    ids = {m.id for m in models}
    assert models, "SDK catalog was empty"
    assert any("grok" in mid.lower() for mid in ids), ids
    cheap = cheapest_model(models)
    assert cheap
    assert cheap in ids


def test_live_chat_returns_content(client: XaiClient) -> None:
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    resp = metered.chat(
        [{"role": "user", "content": "Reply with exactly: LIVE_CHAT_OK"}],
        purpose="live.chat",
        temperature=0,
        max_tokens=32,
    )
    assert "LIVE_CHAT_OK" in (resp.content or "")
    assert resp.model == BOOTSTRAP_MODEL
    events = list(sink.iter_events())
    assert events and events[0].success is True
    assert events[0].modality == "chat"


def test_live_chat_json_returns_object(client: XaiClient) -> None:
    data = client.chat_json(
        'Return JSON: {"ok": true, "tag": "live"}',
        temperature=0,
        thought_level="low",
    )
    assert isinstance(data, dict)
    assert data.get("ok") is True or data.get("tag") == "live" or "ok" in data


def test_live_chat_stream_accumulates(client: XaiClient) -> None:
    chunks = list(
        client.chat_stream(
            [{"role": "user", "content": "Reply with exactly: LIVE_STREAM_OK"}],
            temperature=0,
            max_tokens=32,
        )
    )
    assert chunks
    text = chunks[-1].accumulated or "".join(c.delta for c in chunks)
    assert "LIVE_STREAM_OK" in text


def test_live_tts_returns_audio(client: XaiClient) -> None:
    audio, content_type = client.synthesize_speech("XaiKit live smoke.")
    assert audio
    assert len(audio) > 64
    assert content_type.startswith("audio/") or content_type == "application/octet-stream"


def test_live_stt_roundtrip_from_tts(client: XaiClient) -> None:
    audio, content_type = client.synthesize_speech("The word is pineapple.")
    suffix = "mp3"
    if "wav" in content_type:
        suffix = "wav"
    elif "ogg" in content_type or "opus" in content_type:
        suffix = "ogg"
    text = client.transcribe(
        audio,
        filename=f"live.{suffix}",
        content_type=content_type if content_type.startswith("audio/") else "audio/mpeg",
        language="en",
    )
    assert text.strip()
    assert "pineapple" in text.lower()


def test_live_generate_image_returns_url_or_b64(client: XaiClient) -> None:
    out = client.generate_image(
        "A tiny red cube on a white background, simple 3D render",
        model="grok-imagine-image",
        n=1,
        aspect_ratio="1:1",
    )
    assert out.get("model") == "grok-imagine-image"
    assert out.get("url") or out.get("b64_json")
