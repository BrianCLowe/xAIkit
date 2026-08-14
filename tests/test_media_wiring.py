"""Contract tests: STT / TTS / Imagine REST wiring (URL, auth, body, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TTS_VOICE_ID,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_IMAGES_URL,
    XAI_IMAGE_EDITS_URL,
    XAI_STT_URL,
    XAI_TTS_URL,
    XaiClient,
    default_retry_policy,
)
from xaikit.catalog import (
    contract_imagine_aspect_ratio,
    contract_imagine_quality,
    contract_imagine_resolution,
    imagine_generate_knobs,
    imagine_supports_quality,
)
from xaikit.tts_stream import TTS_MAX_DELTA_CHARS


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


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

        monkeypatch.setattr("xaikit.client.httpx.post", _post)


def test_transcribe_posts_multipart_with_auth_language_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"text": "hello world"},
            request=httpx.Request("POST", XAI_STT_URL),
        ),
    )

    text = client.transcribe(
        b"fake-audio",
        filename="clip.webm",
        content_type="audio/webm",
        language="en",
        purpose="demo.stt",
        parent_id="p1",
        labels={"request_id": "a1"},
    )

    assert text == "hello world"
    assert len(cap.calls) == 1
    call = cap.calls[0]
    assert call["url"] == XAI_STT_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["data"] == {"format": "true", "language": "en"}
    assert call["files"]["file"] == ("clip.webm", b"fake-audio", "audio/webm")
    assert call["timeout"] == 120.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.stt"
    assert ev.modality == "stt"
    assert ev.model == "stt"
    assert ev.success is True
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "a1"


def test_transcribe_rejects_empty_bytes_without_http() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="empty"):
        client.transcribe(b"")


def test_transcribe_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.transcribe(b"x")


def test_synthesize_speech_posts_json_body_and_returns_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"ID3fakeaudio",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )

    audio, content_type = client.synthesize_speech(
        "  say this  ",
        voice_id="ara",
        language="en",
        purpose="demo.tts",
    )

    assert audio == b"ID3fakeaudio"
    assert content_type == "audio/mpeg"
    call = cap.calls[0]
    assert call["url"] == XAI_TTS_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {
        "text": "say this",
        "voice_id": "ara",
        "language": "en",
    }
    assert call["timeout"] == 120.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.tts"
    assert ev.modality == "tts"
    assert ev.model == "tts"
    assert ev.success is True


def test_synthesize_speech_defaults_voice_id(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"audio",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )

    client.synthesize_speech("hi")
    assert cap.calls[0]["json"]["voice_id"] == DEFAULT_TTS_VOICE_ID


def test_synthesize_speech_rejects_empty_text() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="empty"):
        client.synthesize_speech("   ")


def test_synthesize_speech_rejects_over_15k_chars_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"audio",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="15000"):
        client.synthesize_speech("x" * (TTS_MAX_DELTA_CHARS + 1))
    assert cap.calls == []


def test_synthesize_speech_forwards_unary_knobs_nested_output_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"RIFF",
            headers={"content-type": "audio/wav"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )

    audio, content_type = client.synthesize_speech(
        "hello knobs",
        voice_id="ara",
        language="en",
        codec="wav",
        sample_rate=24000,
        speed=1.2,
        optimize_streaming_latency=1,
        text_normalization=True,
        replace={"XAI": "x A I"},
    )

    assert audio == b"RIFF"
    assert content_type == "audio/wav"
    call = cap.calls[0]
    assert call["url"] == XAI_TTS_URL
    assert call["headers"]["Accept"] == "audio/mpeg, application/octet-stream, */*"
    assert call["json"] == {
        "text": "hello knobs",
        "voice_id": "ara",
        "language": "en",
        "output_format": {"codec": "wav", "sample_rate": 24000},
        "speed": 1.2,
        "optimize_streaming_latency": 1,
        "text_normalization": True,
        "replace": {"XAI": "x A I"},
    }
    assert "with_timestamps" not in call["json"]
    assert "bit_rate" not in call["json"]["output_format"]


def test_synthesize_speech_output_format_dict_and_flat_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"ID3",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )

    client.synthesize_speech(
        "hi",
        output_format={"codec": "wav", "sample_rate": 16000, "bit_rate": 64000},
        codec="mp3",
        bit_rate=128000,
    )
    assert cap.calls[0]["json"]["output_format"] == {
        "codec": "mp3",
        "sample_rate": 16000,
        "bit_rate": 128000,
    }


def test_synthesize_speech_omits_unset_optional_knobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"audio",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )

    client.synthesize_speech("hi")
    body = cap.calls[0]["json"]
    assert body == {
        "text": "hi",
        "voice_id": DEFAULT_TTS_VOICE_ID,
        "language": "en",
    }
    assert cap.calls[0]["headers"]["Accept"] == (
        "audio/mpeg, application/octet-stream, */*"
    )


def test_synthesize_speech_rejects_invalid_codec_and_sample_rate_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=b"audio",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="codec"):
        client.synthesize_speech("hi", codec="ogg")
    with pytest.raises(RuntimeError, match="sample_rate"):
        client.synthesize_speech("hi", sample_rate=12000)
    with pytest.raises(RuntimeError, match="bit_rate"):
        client.synthesize_speech("hi", bit_rate=12345)
    with pytest.raises(RuntimeError, match="bit_rate"):
        client.synthesize_speech("hi", codec="wav", bit_rate=128000)
    with pytest.raises(RuntimeError, match="speed"):
        client.synthesize_speech("hi", speed=2.0)
    with pytest.raises(RuntimeError, match="optimize_streaming_latency"):
        client.synthesize_speech("hi", optimize_streaming_latency=9)
    assert cap.calls == []


def test_synthesize_speech_with_timestamps_returns_json_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    envelope = b'{"audio":"YQ==","timestamps":[]}'
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            content=envelope,
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", XAI_TTS_URL),
        ),
    )

    payload, content_type = client.synthesize_speech("hi", with_timestamps=True)
    assert payload == envelope
    assert content_type == "application/json"
    assert cap.calls[0]["json"]["with_timestamps"] is True
    assert cap.calls[0]["headers"]["Accept"].startswith("application/json")


def test_generate_image_posts_model_prompt_aspect_and_clamps_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter, image_model="client-default-image")
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/img.png"}]},
            request=httpx.Request("POST", XAI_IMAGES_URL),
        ),
    )

    out = client.generate_image(
        "  a red cube  ",
        aspect_ratio="16:9",
        n=99,  # clamp to 4
        purpose="demo.imagine",
        labels={"request_id": "img1"},
    )

    assert out["url"] == "https://example.com/img.png"
    assert out["b64_json"] is None
    assert out["model"] == "client-default-image"
    assert out["file_id"] is None

    call = cap.calls[0]
    assert call["url"] == XAI_IMAGES_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"] == {
        "model": "client-default-image",
        "prompt": "a red cube",
        "n": 4,
        "aspect_ratio": "16:9",
    }
    assert call["timeout"] == 180.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.imagine"
    assert ev.modality == "imagine"
    assert ev.model == "client-default-image"
    assert ev.labels["request_id"] == "img1"


def test_generate_image_per_call_model_override_and_omits_aspect_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"b64_json": "abc123"}]},
            request=httpx.Request("POST", XAI_IMAGES_URL),
        ),
    )

    out = client.generate_image("sky", model="grok-imagine-override")

    assert out["b64_json"] == "abc123"
    assert out["url"] is None
    assert out["file_id"] is None
    body = cap.calls[0]["json"]
    assert body["model"] == "grok-imagine-override"
    assert body["n"] == 1
    assert "aspect_ratio" not in body


def test_generate_image_default_model_constant() -> None:
    client = _client()
    assert client.image_model == DEFAULT_IMAGE_MODEL


def test_generate_image_rejects_empty_prompt() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="empty"):
        client.generate_image("  ")


def test_generate_image_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.generate_image("cube")


def test_media_http_error_records_failed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="STT request failed"):
        client.transcribe(b"x", purpose="demo.stt.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "stt"
    assert ev.purpose == "demo.stt.fail"


def test_generate_image_forwards_resolution_quality_response_format_on_2_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/img.png"}]},
            request=httpx.Request("POST", XAI_IMAGES_URL),
        ),
    )

    client.generate_image(
        "a cube",
        model="grok-imagine-image-2.0",
        aspect_ratio="19.5:9",
        resolution="2k",
        quality="low",
        response_format="b64_json",
    )

    assert cap.calls[0]["json"] == {
        "model": "grok-imagine-image-2.0",
        "prompt": "a cube",
        "n": 1,
        "aspect_ratio": "19.5:9",
        "resolution": "2k",
        "quality": "low",
        "response_format": "b64_json",
    }


@pytest.mark.parametrize(
    "model",
    [
        DEFAULT_IMAGE_MODEL,
        "grok-imagine-image",
        "grok-imagine-image-quality",
    ],
)
def test_generate_image_omits_quality_on_non_2_0_skus(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/img.png"}]},
            request=httpx.Request("POST", XAI_IMAGES_URL),
        ),
    )

    client.generate_image(
        "a cube",
        model=model,
        resolution="1k",
        quality="low",
        response_format="b64_json",
    )

    body = cap.calls[0]["json"]
    assert body["model"] == model
    assert body["resolution"] == "1k"
    assert body["response_format"] == "b64_json"
    assert "quality" not in body


def test_generate_image_omits_unknown_aspect_ratio_and_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/img.png"}]},
            request=httpx.Request("POST", XAI_IMAGES_URL),
        ),
    )

    client.generate_image(
        "a cube",
        aspect_ratio="not-a-ratio",
        resolution="4k",
        quality="ultra",
    )

    body = cap.calls[0]["json"]
    assert "aspect_ratio" not in body
    assert "resolution" not in body
    assert "quality" not in body


@pytest.mark.parametrize("aspect_ratio", ["auto", "19.5:9", "20:9", "9:20"])
def test_generate_image_accepts_official_imagine_aspect_ratios(
    monkeypatch: pytest.MonkeyPatch,
    aspect_ratio: str,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/img.png"}]},
            request=httpx.Request("POST", XAI_IMAGES_URL),
        ),
    )

    client.generate_image("a cube", aspect_ratio=aspect_ratio)
    assert cap.calls[0]["json"]["aspect_ratio"] == aspect_ratio


def test_imagine_generate_knob_contraction() -> None:
    assert imagine_supports_quality("grok-imagine-image-2.0") is True
    assert imagine_supports_quality("grok-imagine-image-quality") is False
    assert imagine_supports_quality("grok-imagine-image") is False
    assert contract_imagine_aspect_ratio("auto") == "auto"
    assert contract_imagine_aspect_ratio("19.5:9") == "19.5:9"
    assert contract_imagine_aspect_ratio("square") is None
    assert contract_imagine_resolution("2K") == "2k"
    assert contract_imagine_resolution("4k") is None
    assert contract_imagine_quality("medium", "grok-imagine-image-2.0") == "medium"
    assert contract_imagine_quality("low", DEFAULT_IMAGE_MODEL) is None
    assert contract_imagine_quality("high", "grok-imagine-image-2.0") is None
    knobs = imagine_generate_knobs(
        "grok-imagine-image-quality",
        aspect_ratio="16:9",
        resolution="1k",
        quality="low",
        response_format="b64_json",
    )
    assert knobs == {
        "aspect_ratio": "16:9",
        "resolution": "1k",
        "response_format": "b64_json",
    }


def test_generate_image_surfaces_file_output_file_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "url": "https://example.com/stored.png",
                        "file_output": {"file_id": "file-imagine-1"},
                    }
                ]
            },
            request=httpx.Request("POST", XAI_IMAGES_URL),
        ),
    )

    out = client.generate_image("a cube")
    assert out["file_id"] == "file-imagine-1"
    assert out["url"] == "https://example.com/stored.png"


def test_edit_image_posts_json_url_auth_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter, image_model="client-default-image")
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/edited.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )

    out = client.edit_image(
        "  make it a sketch  ",
        image_url="https://example.com/src.png",
        aspect_ratio="16:9",
        n=99,
        response_format="url",
        purpose="demo.imagine.edit",
        labels={"request_id": "edit1"},
    )

    assert out["url"] == "https://example.com/edited.png"
    assert out["b64_json"] is None
    assert out["model"] == "client-default-image"
    assert out["file_id"] is None

    assert len(cap.calls) == 1
    call = cap.calls[0]
    assert call["url"] == XAI_IMAGE_EDITS_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {
        "model": "client-default-image",
        "prompt": "make it a sketch",
        "n": 4,
        "image": {
            "url": "https://example.com/src.png",
            "type": "image_url",
        },
        "aspect_ratio": "16:9",
        "response_format": "url",
    }
    assert call["timeout"] == 180.0
    assert "files" not in call
    assert "data" not in call

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.imagine.edit"
    assert ev.modality == "imagine"
    assert ev.model == "client-default-image"
    assert ev.success is True
    assert ev.labels["request_id"] == "edit1"


def test_edit_image_file_id_passthrough_and_file_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "b64_json": "abc123",
                        "file_output": {"file_id": "file-out-9"},
                    }
                ]
            },
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )

    out = client.edit_image("sketch", image_file_id="file-in-3")

    assert out["b64_json"] == "abc123"
    assert out["file_id"] == "file-out-9"
    assert cap.calls[0]["json"]["image"] == {"file_id": "file-in-3"}
    assert cap.calls[0]["url"] == XAI_IMAGE_EDITS_URL


def test_edit_image_positional_url_and_data_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/out.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )

    client.edit_image("sketch", "https://example.com/pos.png")
    assert cap.calls[0]["json"]["image"] == {
        "url": "https://example.com/pos.png",
        "type": "image_url",
    }

    cap.calls.clear()
    client.edit_image("sketch", "data:image/png;base64,abc")
    assert cap.calls[0]["json"]["image"] == {
        "url": "data:image/png;base64,abc",
        "type": "image_url",
    }


def test_edit_image_rejects_empty_prompt_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/x.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.edit_image("  ", image_url="https://example.com/src.png")
    assert cap.calls == []


def test_edit_image_rejects_empty_image_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/x.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.edit_image("sketch")
    assert cap.calls == []


def test_edit_image_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.edit_image("sketch", image_url="https://example.com/src.png")


def test_edit_image_images_two_mixed_kinds_wires_images_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/out.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )

    client.edit_image(
        "blend <IMAGE_0> with <IMAGE_1>",
        images=[
            "https://example.com/a.png",
            {"file_id": "file-style-2"},
        ],
    )

    body = cap.calls[0]["json"]
    assert cap.calls[0]["url"] == XAI_IMAGE_EDITS_URL
    assert "image" not in body
    assert body["prompt"] == "blend <IMAGE_0> with <IMAGE_1>"
    assert body["images"] == [
        {"url": "https://example.com/a.png", "type": "image_url"},
        {"file_id": "file-style-2"},
    ]
    assert "files" not in cap.calls[0]
    assert "data" not in cap.calls[0]


def test_edit_image_images_three_mixed_kinds_wires_images_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/out.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )

    client.edit_image(
        "compose three refs",
        images=[
            "https://example.com/a.png",
            "data:image/png;base64,abc",
            {"file_id": "file-3"},
        ],
    )

    body = cap.calls[0]["json"]
    assert "image" not in body
    assert body["images"] == [
        {"url": "https://example.com/a.png", "type": "image_url"},
        {"url": "data:image/png;base64,abc", "type": "image_url"},
        {"file_id": "file-3"},
    ]


def test_edit_image_images_one_item_still_wires_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/out.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )

    client.edit_image("sketch", images=["https://example.com/only.png"])
    body = cap.calls[0]["json"]
    assert "images" not in body
    assert body["image"] == {
        "url": "https://example.com/only.png",
        "type": "image_url",
    }


def test_edit_image_forwards_known_aspect_and_omits_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/out.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )

    client.edit_image(
        "sketch",
        image_url="https://example.com/src.png",
        aspect_ratio="16:9",
    )
    assert cap.calls[0]["json"]["aspect_ratio"] == "16:9"

    cap.calls.clear()
    client.edit_image(
        "sketch",
        image_url="https://example.com/src.png",
        aspect_ratio="21:9",
    )
    assert "aspect_ratio" not in cap.calls[0]["json"]


def test_edit_image_rejects_more_than_three_images_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/x.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )
    with pytest.raises(ValueError, match="at most 3"):
        client.edit_image(
            "too many",
            images=[
                "https://example.com/1.png",
                "https://example.com/2.png",
                "https://example.com/3.png",
                "https://example.com/4.png",
            ],
        )
    assert cap.calls == []


def test_edit_image_rejects_single_and_images_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install(
        monkeypatch,
        httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/x.png"}]},
            request=httpx.Request("POST", XAI_IMAGE_EDITS_URL),
        ),
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        client.edit_image(
            "sketch",
            image_url="https://example.com/src.png",
            images=["https://example.com/other.png", {"file_id": "file-2"}],
        )
    assert cap.calls == []


def test_edit_image_http_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Image edit request failed"):
        client.edit_image(
            "sketch",
            image_url="https://example.com/src.png",
            purpose="demo.imagine.edit.fail",
        )

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "imagine"
    assert ev.purpose == "demo.imagine.edit.fail"
