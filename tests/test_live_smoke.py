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
    default_retry_policy,
    inject_catalog,
    list_models,
)
from xaikit.catalog import cheapest_model, clear_catalog_cache, resolve_model_selection, set_test_fetch

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
    assert BOOTSTRAP_MODEL in ids
    cheap = cheapest_model(models)
    assert cheap
    assert cheap in ids
    if any(not mid.startswith("grok-build-") and "code-fast" not in mid for mid in ids):
        assert not cheap.startswith("grok-build-")
    for m in models:
        slug = f"{m.id} {' '.join(m.aliases)}".lower()
        if "non-reasoning" in slug.replace("_", "-"):
            assert "reasoning" not in m.capabilities, m.id


def test_live_three_intents_resolve_to_catalog_ids(api_key: str) -> None:
    models = list_models(api_key=api_key, force_refresh=True, allow_fixture_fallback=False)
    ids = {m.id for m in models}
    cheap = resolve_model_selection(intent="cheapest", catalog=models)
    economy = resolve_model_selection(intent="economy", catalog=models)
    best = resolve_model_selection(intent="best", catalog=models)
    assert cheap.model_id in ids
    assert economy.model_id in ids
    assert best.model_id in ids
    by_id = {m.id: m for m in models}
    if (
        by_id[cheap.model_id].input_per_million is not None
        and by_id[best.model_id].input_per_million is not None
    ):
        assert by_id[cheap.model_id].input_per_million <= by_id[best.model_id].input_per_million


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


def test_live_unpinned_client_resolves_and_chats(api_key: str) -> None:
    client = XaiClient(
        api_key=api_key,
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    assert client.model
    resp = client.chat(
        [{"role": "user", "content": "Reply with exactly: UNPIN_OK"}],
        temperature=0,
        max_tokens=16,
    )
    assert "UNPIN_OK" in (resp.content or "")


def test_live_thought_level_high(client: XaiClient) -> None:
    resp = client.chat(
        [{"role": "user", "content": "Reply with exactly: HIGH_OK"}],
        temperature=0,
        max_tokens=32,
        thought_level="high",
    )
    assert "HIGH_OK" in (resp.content or "")


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


def test_live_edit_image_returns_url_or_b64_or_file_id(client: XaiClient) -> None:
    """Uses a public docs URL — no local image file required."""
    out = client.edit_image(
        "Render this as a simple pencil sketch",
        image_url="https://docs.x.ai/assets/api-examples/images/style-realistic.png",
        model="grok-imagine-image",
        n=1,
    )
    assert out.get("model") == "grok-imagine-image"
    assert out.get("url") or out.get("b64_json") or out.get("file_id")


_RUN_LIVE_VIDEO = os.environ.get("XAITKIT_LIVE_VIDEO", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


@pytest.mark.skipif(
    not _RUN_LIVE_VIDEO,
    reason="set XAITKIT_LIVE_VIDEO=1 (video gen is slow/expensive; not part of default live smokes)",
)
def test_live_generate_video_start_returns_request_id(client: XaiClient) -> None:
    """Opt-in start-only smoke — does not wait for the finished clip."""
    out = client.generate_video(
        "A tiny red cube rotating once, plain white background",
        duration=1,
        aspect_ratio="1:1",
        resolution="480p",
        wait=False,
    )
    assert out.get("request_id")


_RUN_LIVE_VOICE = os.environ.get("XAITKIT_LIVE_VOICE", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


@pytest.mark.skipif(
    not _RUN_LIVE_VOICE,
    reason="set XAITKIT_LIVE_VOICE=1 (realtime voice is metered; not part of default live smokes)",
)
def test_live_open_realtime_session_receives_an_event(client: XaiClient) -> None:
    """Opt-in connect smoke — no mic; recv one server event then close."""
    with client.open_realtime_session(
        instructions="You are a test assistant. Keep replies to one word.",
        turn_detection=None,
    ) as session:
        event = session.recv(timeout=30.0)
        assert isinstance(event, (dict, bytes))
        if isinstance(event, dict):
            assert event.get("type")


_RUN_LIVE_STT = os.environ.get("XAITKIT_LIVE_STT", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


@pytest.mark.skipif(
    not _RUN_LIVE_STT,
    reason="set XAITKIT_LIVE_STT=1 (streaming STT is metered; not part of default live smokes)",
)
def test_live_open_stt_session_receives_created_and_done(client: XaiClient) -> None:
    """Opt-in streaming STT smoke — silence PCM, no mic; wait for transcript.done."""
    pcm = bytes(16000 * 2)  # 1 s of 16 kHz s16le silence
    with client.open_stt_session(language="en", interim_results=True) as session:
        created = session.recv(timeout=30.0)
        assert created.get("type") == "transcript.created"
        session.send_audio(pcm)
        session.audio_done()
        kinds: list[str] = []
        while True:
            event = session.recv(timeout=30.0)
            kind = str(event.get("type") or "")
            kinds.append(kind)
            if kind == "transcript.done":
                break
        assert "transcript.done" in kinds


_RUN_LIVE_EMBED = os.environ.get("XAITKIT_LIVE_EMBED", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


@pytest.mark.skipif(
    not _RUN_LIVE_EMBED,
    reason="set XAITKIT_LIVE_EMBED=1 (embeddings are metered; not part of default live smokes)",
)
def test_live_embed_returns_vectors(client: XaiClient) -> None:
    """Opt-in embed smoke — pin model (OpenAPI example is v1; override via env)."""
    model = (os.environ.get("XAITKIT_LIVE_EMBED_MODEL") or "v1").strip() or "v1"
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    out = metered.embed("query: xaikit live smoke", model=model, purpose="live.embed")
    assert out.get("data")
    assert out["data"][0].get("embedding")
    events = list(sink.iter_events())
    assert events and events[0].success is True
    assert events[0].modality == "embed"
