"""Offline contract tests for AsyncXaiClient (chat + REST + WS + smoke)."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from xaikit import (
    AsyncSttSession,
    AsyncXaiClient,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_EMBEDDINGS_URL,
    XAI_STT_WS_URL,
    default_retry_policy,
)

PUBLIC_ASYNC_METHODS = (
    "chat",
    "chat_json",
    "chat_stream",
    "create_deferred_chat",
    "get_deferred_chat",
    "transcribe",
    "synthesize_speech",
    "list_tts_voices",
    "get_tts_voice",
    "generate_image",
    "edit_image",
    "upload_file",
    "get_file",
    "delete_file",
    "embed",
    "tokenize",
    "create_response",
    "get_response",
    "create_batch",
    "add_batch_requests",
    "get_batch",
    "cancel_batch",
    "list_batches",
    "list_batch_results",
    "create_collection",
    "get_collection",
    "list_collections",
    "delete_collection",
    "upload_document",
    "search_collections",
    "generate_video",
    "extend_video",
    "poll_video",
    "download_video",
    "open_realtime_session",
    "create_realtime_client_secret",
    "open_stt_session",
    "open_tts_session",
)


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> AsyncXaiClient:
    return AsyncXaiClient(
        provider=MockChatProvider(replies=kwargs.pop("replies", "ok")),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
        **kwargs,
    )


def test_import_async_xai_client_from_xaikit() -> None:
    from xaikit import AsyncXaiClient as Imported

    assert Imported is AsyncXaiClient


def test_public_methods_are_awaitable() -> None:
    missing = [name for name in PUBLIC_ASYNC_METHODS if not hasattr(AsyncXaiClient, name)]
    assert missing == []
    for name in PUBLIC_ASYNC_METHODS:
        fn = getattr(AsyncXaiClient, name)
        assert inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn), name


def test_async_chat_forwards_to_mock_and_meters() -> None:
    async def _run() -> None:
        sink = InMemoryUsageSink()
        meter = UsageMeter(sink=sink)
        provider = MockChatProvider(replies="hello from mock")
        client = AsyncXaiClient(
            provider=provider,
            model="grok-3-mini",
            usage_meter=meter,
            retry_policy=default_retry_policy(max_attempts=1),
        )
        resp = await client.chat(
            [{"role": "user", "content": "hi"}],
            purpose="demo.chat",
            temperature=0.2,
            system_prompt="be brief",
        )
        assert resp.content == "hello from mock"
        assert resp.model == "grok-3-mini"
        assert len(provider.calls) == 1
        call = provider.calls[0]
        assert call["kind"] == "complete"
        assert call["temperature"] == 0.2
        assert call["system_prompt"] == "be brief"
        events = list(sink.iter_events())
        assert len(events) == 1
        assert events[0].purpose == "demo.chat"
        assert events[0].modality == "chat"
        assert events[0].success is True

    asyncio.run(_run())


def test_async_chat_stream_yields_chunks() -> None:
    async def _run() -> None:
        provider = MockChatProvider(replies="streamed", stream_chunk_size=4)
        client = AsyncXaiClient(
            provider=provider,
            model="grok-3-mini",
            retry_policy=default_retry_policy(max_attempts=1),
        )
        chunks = []
        async for piece in client.chat_stream([{"role": "user", "content": "hi"}]):
            chunks.append(piece.delta)
        assert "".join(chunks) == "streamed"
        assert provider.calls[0]["kind"] == "stream"

    asyncio.run(_run())


class _AsyncHttpCapture:
    def __init__(self, response: httpx.Response) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = response

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        capture = self

        class FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._timeout = kwargs.get("timeout")

            async def __aenter__(self) -> FakeAsyncClient:
                return self

            async def __aexit__(self, *args: Any) -> bool:
                return False

            async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
                capture.calls.append({"method": method, "url": url, **kwargs})
                response = capture.response
                if response.request is not None:
                    return response
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=response.content,
                    request=httpx.Request(method, url),
                )

        monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)


def test_async_embed_posts_json_with_auth_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        sink = InMemoryUsageSink()
        meter = UsageMeter(sink=sink)
        client = _client(usage_meter=meter)
        payload = {
            "object": "list",
            "model": "v1",
            "data": [{"index": 0, "embedding": [0.1, 0.2], "object": "embedding"}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
        cap = _AsyncHttpCapture(
            httpx.Response(
                200,
                json=payload,
                request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
            )
        )
        cap.install(monkeypatch)
        out = await client.embed(["query: hello"], model="v1", purpose="demo.embed")
        assert out["data"][0]["embedding"] == [0.1, 0.2]
        assert len(cap.calls) == 1
        call = cap.calls[0]
        assert call["method"] == "POST"
        assert call["url"] == XAI_EMBEDDINGS_URL
        assert call["headers"]["Authorization"] == "Bearer test-key"
        assert call["json"] == {"model": "v1", "input": ["query: hello"]}
        ev = list(sink.iter_events())[0]
        assert ev.purpose == "demo.embed"
        assert ev.modality == "embed"
        assert ev.success is True
        assert ev.estimated_usd is None

    asyncio.run(_run())


class FakeAsyncWebSocket:
    def __init__(self, incoming: list[str | bytes] | None = None) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: list[str | bytes] = list(incoming or [])
        self.closed = False

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)

    async def recv(self, timeout: float | None = None) -> str | bytes:
        if not self.incoming:
            raise TimeoutError("no messages")
        return self.incoming.pop(0)

    async def close(self) -> None:
        self.closed = True


class _AsyncWsCapture:
    def __init__(self, incoming: list[str | bytes] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.ws = FakeAsyncWebSocket(incoming)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeAsyncWebSocket:
        async def _connect(uri: str, **kwargs: Any) -> FakeAsyncWebSocket:
            self.calls.append({"uri": uri, **kwargs})
            return self.ws

        monkeypatch.setattr(
            "xaikit.async_client.connect_stt_websocket_async", _connect
        )
        return self.ws


def test_async_open_stt_monkeypatches_connect_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        sink = InMemoryUsageSink()
        meter = UsageMeter(sink=sink)
        client = _client(usage_meter=meter)
        created = json.dumps({"type": "transcript.created"})
        cap = _AsyncWsCapture([created])
        cap.install(monkeypatch)
        session = await client.open_stt_session(
            language="en",
            purpose="demo.stt.stream",
        )
        assert isinstance(session, AsyncSttSession)
        assert len(cap.calls) == 1
        call = cap.calls[0]
        parts = urlsplit(call["uri"])
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == XAI_STT_WS_URL
        query = parse_qs(parts.query)
        assert query["language"] == ["en"]
        assert call["additional_headers"]["Authorization"] == "Bearer test-key"
        await session.close()
        ev = list(sink.iter_events())[0]
        assert ev.purpose == "demo.stt.stream"
        assert ev.modality == "stt"
        assert ev.success is True

    asyncio.run(_run())


def test_purpose_required_when_metered() -> None:
    async def _run() -> None:
        meter = UsageMeter(sink=InMemoryUsageSink())
        client = _client(usage_meter=meter)
        with pytest.raises(ValueError, match="purpose"):
            await client.chat([{"role": "user", "content": "x"}])
        with pytest.raises(ValueError, match="purpose"):
            await client.embed("hello", model="v1")
        with pytest.raises(ValueError, match="purpose"):
            await client.tokenize("hello")

    asyncio.run(_run())


def test_empty_input_guards() -> None:
    async def _run() -> None:
        client = _client()
        with pytest.raises(RuntimeError, match="empty"):
            await client.create_deferred_chat([])
        with pytest.raises(RuntimeError, match="empty"):
            await client.get_deferred_chat("  ")
        with pytest.raises(RuntimeError, match="empty"):
            await client.transcribe(b"")
        with pytest.raises(RuntimeError, match="empty"):
            await client.synthesize_speech("  ")
        with pytest.raises(RuntimeError, match="empty"):
            await client.get_tts_voice("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.generate_image("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.upload_file(b"", "file.txt")
        with pytest.raises(RuntimeError, match="empty"):
            await client.get_file("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.embed("", model="v1")
        with pytest.raises(RuntimeError, match="empty"):
            await client.tokenize("  ")
        with pytest.raises(RuntimeError, match="empty"):
            await client.create_response("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.get_response("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.create_batch("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.add_batch_requests("", [])
        with pytest.raises(RuntimeError, match="empty"):
            await client.get_batch("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.create_collection("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.get_collection("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.search_collections("", "col-1")
        with pytest.raises(RuntimeError, match="empty"):
            await client.generate_video("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.poll_video("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.download_video("")
        with pytest.raises(RuntimeError, match="empty"):
            await client.upload_document("col-1", "doc.txt", b"")

    asyncio.run(_run())


@pytest.mark.parametrize(
    "name,args,kwargs",
    [
        ("chat_json", ("{}",), {}),
        ("list_tts_voices", (), {}),
        ("list_batches", (), {}),
        ("list_collections", (), {}),
        ("cancel_batch", ("batch-1",), {}),
        ("list_batch_results", ("batch-1",), {}),
        ("delete_collection", ("col-1",), {}),
        ("delete_file", ("file-1",), {}),
        ("create_realtime_client_secret", (), {}),
        ("open_tts_session", (), {}),
        ("open_realtime_session", (), {}),
        ("extend_video", ("continue",), {}),
        ("edit_image", ("sketch",), {"image_url": "https://example.com/a.png"}),
    ],
)
def test_long_tail_methods_exist_and_are_coroutines(
    name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> None:
    fn = getattr(AsyncXaiClient, name)
    assert inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)

    async def _run() -> None:
        meter = UsageMeter(sink=InMemoryUsageSink())
        client = _client(usage_meter=meter)
        with pytest.raises(ValueError, match="purpose"):
            await getattr(client, name)(*args, **kwargs)

    asyncio.run(_run())
