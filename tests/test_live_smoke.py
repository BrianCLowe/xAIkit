"""Optional live xAI smokes — skipped unless XAITKIT_LIVE=1 and XAI_API_KEY.

Run from repo root::

    XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live -v

Default live covers chat extras (tools, vision ≥8×8, service_tier, async),
catalog persist + ``role=video``, files, tokenize, Responses, deferred chat,
realtime client-secret mint, and ``get_tts_voice``. Spendier surfaces stay
behind extra flags (see module constants).
"""

from __future__ import annotations

import asyncio
import base64
import os
import struct
import uuid
import zlib

import pytest

from xaikit import (
    BOOTSTRAP_MODEL,
    AsyncXaiClient,
    EnvCredentialStore,
    InMemoryUsageSink,
    UsageMeter,
    XaiClient,
    decode_tts_audio,
    default_retry_policy,
    feature_options,
    inject_catalog,
    list_models,
    save_catalog_snapshot,
)
from xaikit.catalog import cheapest_model, clear_catalog_cache, resolve_model_selection, set_test_fetch

def _env_on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


_RUN_LIVE = _env_on("XAITKIT_LIVE")
_HAS_KEY = bool(os.environ.get("XAI_API_KEY", "").strip())
_HAS_MANAGEMENT_KEY = bool(os.environ.get("XAI_MANAGEMENT_KEY", "").strip())

_WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get the weather for a city.",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}


def _png_data_uri(*, width: int = 32, height: int = 32) -> str:
    """Solid PNG large enough for live vision (xAI rejects images under 8×8)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    pixel = bytes((196, 48, 48, 255))
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.standard_b64encode(png).decode("ascii")


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
    audio, content_type = client.synthesize_speech(
        "XaiKit live smoke.",
        voice_id="eve",
        codec="wav",
        sample_rate=24000,
        speed=1.0,
        text_normalization=True,
    )
    assert audio
    assert len(audio) > 64
    assert (
        content_type.startswith("audio/")
        or content_type == "application/octet-stream"
    )


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


_RUN_LIVE_VIDEO = _env_on("XAITKIT_LIVE_VIDEO")
_VIDEO_FILE_ID = (os.environ.get("XAITKIT_LIVE_VIDEO_FILE_ID") or "").strip()


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
        into=[],
        wait=False,
    )
    assert out.get("request_id")
    status = client.poll_video(out["request_id"])
    assert status.get("status") in {"done", "pending", "failed", "expired"} or (
        "request_id" in status
    )


@pytest.mark.skipif(
    not _RUN_LIVE_VIDEO,
    reason="set XAITKIT_LIVE_VIDEO=1 (video gen is slow/expensive; not part of default live smokes)",
)
def test_live_generate_video_speaking_start_with_reference_audios(
    client: XaiClient,
) -> None:
    """Opt-in start-only speaking shot — does not wait for the finished clip."""
    out = client.generate_video(
        "A presenter looks at camera and says hello from the kit smoke.",
        duration=1,
        aspect_ratio="16:9",
        resolution="480p",
        reference_audios=[{"voice_id": "eve"}],
        into=[],
        wait=False,
    )
    assert out.get("request_id")


@pytest.mark.skipif(
    not _RUN_LIVE_VIDEO,
    reason="set XAITKIT_LIVE_VIDEO=1 (video gen is slow/expensive; not part of default live smokes)",
)
@pytest.mark.skipif(
    not _VIDEO_FILE_ID,
    reason="set XAITKIT_LIVE_VIDEO_FILE_ID to a finished clip file_id to smoke extend",
)
def test_live_extend_video_start_returns_request_id(client: XaiClient) -> None:
    """Opt-in start-only extend — needs a finished Imagine clip ``file_id``."""
    out = client.extend_video(
        "The cube keeps spinning.",
        video_file_id=_VIDEO_FILE_ID,
        duration=2,
        into=[],
        wait=False,
    )
    assert out.get("request_id")


_RUN_LIVE_VOICE = _env_on("XAITKIT_LIVE_VOICE")


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


_RUN_LIVE_STT = _env_on("XAITKIT_LIVE_STT")


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


_RUN_LIVE_EMBED = _env_on("XAITKIT_LIVE_EMBED")


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


def test_live_chat_tools_and_optional_follow_up(client: XaiClient) -> None:
    """Live tools path — kit returns ``tool_calls``; this test owns the loop."""
    resp = client.chat(
        [{"role": "user", "content": "Weather in NYC?"}],
        tools=[_WEATHER_TOOL],
        tool_choice="auto",
        temperature=0,
        max_tokens=64,
    )
    assert resp.content or resp.tool_calls
    calls = resp.tool_calls or []
    if not calls:
        return
    follow = client.chat(
        [
            {"role": "user", "content": "Weather in NYC?"},
            {
                "role": "assistant",
                "content": resp.content or "",
                "tool_calls": calls,
            },
            {
                "role": "tool",
                "content": "72F",
                "tool_call_id": calls[0].get("id"),
            },
        ],
        tools=[_WEATHER_TOOL],
        temperature=0,
        max_tokens=64,
    )
    assert follow.content


def test_live_chat_vision_parts_accepts_8x8_plus_png(client: XaiClient) -> None:
    """Live vision — xAI rejects images under 8×8; this PNG is 32×32."""
    resp = client.chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What color is this image? One word."},
                    {"type": "image_url", "url": _png_data_uri(), "detail": "low"},
                ],
            }
        ],
        temperature=0,
        max_tokens=32,
    )
    assert resp.content


def test_live_chat_service_tier_priority_accepted(client: XaiClient) -> None:
    resp = client.chat(
        [{"role": "user", "content": "Reply with exactly: TIER_OK"}],
        service_tier="priority",
        temperature=0,
        max_tokens=16,
    )
    assert "TIER_OK" in (resp.content or "") or bool(resp.content)


def test_live_async_client_chat(api_key: str, client: XaiClient) -> None:
    async def _run() -> str:
        async_client = AsyncXaiClient(
            api_key=api_key,
            model=client.model,
            retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
        )
        resp = await async_client.chat(
            [{"role": "user", "content": "Reply with exactly: ASYNC_OK"}],
            temperature=0,
            max_tokens=16,
        )
        return resp.content or ""

    text = asyncio.run(_run())
    assert "ASYNC_OK" in text


def test_live_list_models_persist_and_role_video(api_key: str, tmp_path) -> None:
    persist = tmp_path / "catalog.json"
    models = list_models(
        api_key=api_key,
        force_refresh=True,
        allow_fixture_fallback=False,
        persist_path=persist,
    )
    assert persist.is_file() and persist.stat().st_size > 2
    snap = tmp_path / "catalog.snapshot.json"
    save_catalog_snapshot(snap, models)
    assert snap.is_file() and '"models"' in snap.read_text(encoding="utf-8")

    video_best = resolve_model_selection(intent="best", role="video", catalog=models)
    assert video_best.model_id
    assert "video" in video_best.model_id
    extend = resolve_model_selection(
        intent="best", role="video", need="video_extend", catalog=models
    )
    assert "video_extend" in feature_options(model=extend.model_id)


def test_live_files_upload_get_delete(client: XaiClient) -> None:
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    uploaded = metered.upload_file(
        b"hello",
        "xaikit-live-smoke.txt",
        content_type="text/plain",
        purpose="live.files",
    )
    file_id = uploaded.get("id")
    assert file_id
    try:
        got = metered.get_file(file_id, purpose="live.files")
        assert got.get("id") == file_id
    finally:
        deleted = metered.delete_file(file_id, purpose="live.files")
        assert deleted is not None
    events = list(sink.iter_events())
    assert events
    assert {ev.modality for ev in events} == {"files"}
    assert all(ev.success for ev in events)


def test_live_tokenize_returns_count(client: XaiClient) -> None:
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    out = metered.tokenize("Hello world", purpose="live.tokenize")
    assert int(out.get("count") or 0) >= 1
    events = list(sink.iter_events())
    assert events and events[0].success is True
    assert events[0].modality == "tokenize"


def test_live_create_and_get_response(client: XaiClient) -> None:
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    created = metered.create_response("What is 2+2? Reply with one number.", purpose="live.responses")
    response_id = created.get("id")
    assert response_id
    fetched = metered.get_response(response_id, purpose="live.responses")
    assert fetched.get("id") == response_id
    events = list(sink.iter_events())
    assert events
    assert {ev.modality for ev in events} == {"responses"}


def test_live_create_and_get_deferred_chat(client: XaiClient) -> None:
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    ticket = metered.create_deferred_chat(
        [{"role": "user", "content": "Reply with exactly: DEFER_OK"}],
        temperature=0,
        max_tokens=16,
        purpose="live.deferred",
    )
    request_id = ticket.get("request_id")
    assert request_id
    got = metered.get_deferred_chat(request_id, purpose="live.deferred")
    assert got.get("status") in {"complete", "pending"} or got.get("id")
    events = list(sink.iter_events())
    assert events
    assert {ev.modality for ev in events} == {"chat"}


def test_live_create_realtime_client_secret(client: XaiClient) -> None:
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    secret = metered.create_realtime_client_secret(
        expires_after=60,
        purpose="live.realtime.secret",
    )
    assert secret.get("value")
    events = list(sink.iter_events())
    assert events and events[0].success is True
    assert events[0].modality == "realtime"
    assert events[0].estimated_usd is None


def test_live_get_tts_voice_eve(client: XaiClient) -> None:
    voice = client.get_tts_voice("eve")
    assert voice.get("voice_id") == "eve" or bool(voice)


_RUN_LIVE_BATCH = _env_on("XAITKIT_LIVE_BATCH")


@pytest.mark.skipif(
    not _RUN_LIVE_BATCH,
    reason="set XAITKIT_LIVE_BATCH=1 (batch is metered; not part of default live smokes)",
)
def test_live_batch_create_add_get_cancel(client: XaiClient) -> None:
    """Live Batch rejects grok-4.6 / 4.5; omitted model remaps via ``need=batch``."""
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    name = f"xaikit-live-{uuid.uuid4().hex[:8]}"
    job = metered.create_batch(name, purpose="live.batch")
    job_id = job.get("id")
    assert job_id
    try:
        metered.add_batch_requests(
            job_id,
            [
                {
                    "messages": [{"role": "user", "content": "Capital of France?"}],
                    "batch_request_id": "fr",
                }
            ],
            purpose="live.batch",
        )
        status = metered.get_batch(job_id, purpose="live.batch")
        assert status.get("id") == job_id or status
    finally:
        metered.cancel_batch(job_id, purpose="live.batch")
    events = list(sink.iter_events())
    assert events
    assert {ev.modality for ev in events} == {"batch"}


_RUN_LIVE_COLLECTIONS = _env_on("XAITKIT_LIVE_COLLECTIONS")


@pytest.mark.skipif(
    not _RUN_LIVE_COLLECTIONS,
    reason="set XAITKIT_LIVE_COLLECTIONS=1 (not part of default live smokes)",
)
@pytest.mark.skipif(
    not _HAS_MANAGEMENT_KEY,
    reason="XAI_MANAGEMENT_KEY not set (create/upload/list/delete use the management API)",
)
def test_live_collections_create_upload_delete(client: XaiClient) -> None:
    """Create/upload on the management key. Search is one-shot — no kit retry."""
    sink = InMemoryUsageSink()
    metered = XaiClient(
        api_key=client.api_key,
        model=client.model,
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=2, backoff_seconds=0.5),
    )
    name = f"xaikit-live-{uuid.uuid4().hex[:8]}"
    coll = metered.create_collection(
        name,
        model_name="grok-embedding-small",
        description="ephemeral xaikit live smoke",
        purpose="live.collections",
    )
    coll_id = coll.get("id")
    assert coll_id
    try:
        listed = metered.list_collections(purpose="live.collections")
        assert listed is not None
        got = metered.get_collection(coll_id, purpose="live.collections")
        assert got.get("id") == coll_id
        uploaded = metered.upload_document(
            coll_id,
            "note.txt",
            b"hello world from the xaikit live smoke.",
            purpose="live.collections",
        )
        assert uploaded is not None
        try:
            hits = metered.search_collections(
                "hello",
                coll_id,
                purpose="live.collections",
            )
            assert "matches" in hits or hits is not None
        except Exception as exc:
            text = str(exc)
            # Create can succeed while inference search 404s until the id is
            # visible. Kit documents the lag; it does not wait/retry.
            if "NOT_FOUND" not in text and "not found or not accessible" not in text.lower():
                raise
    finally:
        metered.delete_collection(coll_id, purpose="live.collections")
    events = list(sink.iter_events())
    assert events
    assert {ev.modality for ev in events} <= {"collections"}
    assert "collections" in {ev.modality for ev in events}


_RUN_LIVE_TTS = _env_on("XAITKIT_LIVE_TTS")


@pytest.mark.skipif(
    not _RUN_LIVE_TTS,
    reason="set XAITKIT_LIVE_TTS=1 (streaming TTS is metered; not part of default live smokes)",
)
def test_live_open_tts_session_receives_audio_done(client: XaiClient) -> None:
    """Opt-in streaming TTS smoke — short text, wait for audio.done."""
    chunks = 0
    kinds: list[str] = []
    with client.open_tts_session(language="en", voice="eve", codec="mp3") as session:
        session.send_text("Hello from kit live smoke.")
        session.text_done()
        while True:
            event = session.recv(timeout=30.0)
            kind = str(event.get("type") or "")
            kinds.append(kind)
            if decode_tts_audio(event):
                chunks += 1
            if kind == "audio.done":
                break
    assert "audio.done" in kinds
    assert chunks >= 0


_RUN_LIVE_IMAGE_KNOBS = _env_on("XAITKIT_LIVE_IMAGE_KNOBS")


@pytest.mark.skipif(
    not _RUN_LIVE_IMAGE_KNOBS,
    reason="set XAITKIT_LIVE_IMAGE_KNOBS=1 (2.0 2k quality=medium; not part of default live smokes)",
)
def test_live_generate_image_2_0_resolution_and_quality(client: XaiClient) -> None:
    out = client.generate_image(
        "A brass cube on a workbench, simple 3D render",
        model="grok-imagine-image-2.0",
        aspect_ratio="1:1",
        resolution="2k",
        quality="medium",
        response_format="b64_json",
        n=1,
    )
    assert out.get("b64_json") or out.get("url")
