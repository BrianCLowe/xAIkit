"""CUT-2026-10-14-xk-host-catalog-created.

HCC-C01 through HCC-C14. Offline only: httpx.get is patched, the key is
``xai-fake``, and no XAI_* env var is set. HCC-C13 is the existing regional,
catalog, and custom base URL suites, which this module does not edit.
"""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from xaikit import MockChatProvider, XaiClient
from xaikit.base_url import DEFAULT_BASE_URL
from xaikit.catalog import (
    _model_ids_from_payload,
    best_model,
    cheapest_model,
    clear_catalog_cache,
    describe_listed_id,
    economy_model,
    fetch_host_catalog,
    inject_catalog,
    model_info_from_image_proto,
    model_info_from_language_proto,
    resolve_model,
    set_test_fetch,
)
from xaikit.types import ModelInfo

KEY = "xai-fake"
REGIONAL = "https://us-east-1.api.x.ai/v1"
IMAGE = "grok-imagine-image"
QUALITY = "grok-imagine-image-quality"
IMAGE_2 = "grok-imagine-image-2.0"
IMAGE_IDS = (IMAGE, QUALITY, IMAGE_2)
CREATED = {
    IMAGE: 1751328000,
    QUALITY: 1759276800,
    IMAGE_2: 1767225600,
}
# Shipped per-call rates make 2.0 the flagship once it is newest, and quality
# the economy pick in the band strictly below it.
_PRICE_NOISE = {
    "input_per_million": 123.0,
    "output_per_million": 456.0,
    "per_call_usd": 0,
    "per_image_usd": 0,
    "role": "chat",
}

_SDK_CATALOG = [
    ModelInfo(
        id="grok-4.7",
        capabilities=["chat"],
        input_per_million=2.0,
        output_per_million=6.0,
        created=20,
    ),
    ModelInfo(
        id="grok-4.3",
        capabilities=["chat"],
        input_per_million=1.25,
        output_per_million=2.5,
        created=10,
    ),
    # Newest created is the cheap image id, so best depends on created.
    # P_CREATED would pick 2.0 instead. Dropping created would pick quality.
    ModelInfo(id=IMAGE, capabilities=["image"], created=300),
    ModelInfo(id=QUALITY, capabilities=["image"], created=200),
    ModelInfo(id=IMAGE_2, capabilities=["image"], created=100),
    ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=20),
    ModelInfo(id="grok-imagine-video", capabilities=["video"], created=10),
    ModelInfo(id="grok-voice-latest", capabilities=["voice"], created=20),
    ModelInfo(id="grok-voice-think-fast-1.0", capabilities=["voice"], created=10),
]


def _image_row(model_id: str, created: Any = None, *, include_created: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": model_id,
        "object": "model",
        "owned_by": "xai",
        **_PRICE_NOISE,
    }
    if include_created:
        row["created"] = created
    return row


def _payload(ids: tuple[str, ...] | list[str], created_for: Any, *, include_created: bool = True) -> dict[str, Any]:
    data = []
    for model_id in ids:
        created = created_for(model_id) if callable(created_for) else created_for
        data.append(_image_row(model_id, created, include_created=include_created))
    return {"object": "list", "data": data}


def _p_created(ids: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
    return _payload(list(ids or IMAGE_IDS), lambda model_id: CREATED[model_id])


def _p_nocreated() -> dict[str, Any]:
    return _payload(IMAGE_IDS, None, include_created=False)


def _p_badcreated() -> dict[str, Any]:
    # "abc", null, and an ISO string. All three stay unset.
    bad = {
        IMAGE: "abc",
        QUALITY: None,
        IMAGE_2: "2026-01-01T00:00:00Z",
    }
    return _payload(IMAGE_IDS, lambda model_id: bad[model_id])


def _p_mixed() -> dict[str, Any]:
    """Created on 2.0 only. The other rows omit the field."""
    return {
        "object": "list",
        "data": [
            _image_row(IMAGE, include_created=False),
            _image_row(QUALITY, None),
            _image_row(IMAGE_2, CREATED[IMAGE_2]),
        ],
    }


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    for name in ("XAI_API_KEY", "XAI_BASE_URL", "XAI_MANAGEMENT_KEY", "XAITKIT_LIVE"):
        monkeypatch.delenv(name, raising=False)
    inject_catalog(None)
    set_test_fetch(None)
    clear_catalog_cache()

    def _host(address: Any) -> str:
        if isinstance(address, tuple) and address:
            return str(address[0])
        return str(address)

    orig = socket.socket.connect
    orig_ex = socket.socket.connect_ex

    def connect(self, address):  # type: ignore[no-untyped-def]
        host = _host(address)
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError(f"non-loopback connection to {host}")
        return orig(self, address)

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        host = _host(address)
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError(f"non-loopback connection to {host}")
        return orig_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield
    inject_catalog(None)
    set_test_fetch(None)
    clear_catalog_cache()


def _patch_get(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, headers: dict[str, str] | None = None, timeout: float | None = None, **_kwargs: Any):
        calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def _fetch(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]):
    calls = _patch_get(monkeypatch, payload)
    rows = fetch_host_catalog(KEY, REGIONAL)
    assert calls
    assert calls[-1]["url"] == f"{REGIONAL}/models"
    assert calls[-1]["headers"]["Authorization"] == f"Bearer {KEY}"
    return rows


def _by_id(rows) -> dict[str, ModelInfo]:
    return {info.id: info for info, _role in rows}


def _image_ids(rows) -> list[ModelInfo]:
    return [info for info, role in rows if role == "image"]


def _assert_shipped_image_prices(info: ModelInfo) -> None:
    assert info.input_per_million == 0.0
    assert info.output_per_million == 0.0
    assert info.per_image_usd is None


def test_hcc_c01_created_populated_on_fetch_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C01: P_CREATED rows keep each id's Unix created time."""
    payload = _p_created()
    parsed = _model_ids_from_payload(payload)
    assert all(isinstance(row, dict) for row in parsed)
    assert [row["id"] for row in parsed] == list(IMAGE_IDS)
    for row in parsed:
        assert type(row["created"]) is int
        assert row["created"] == CREATED[row["id"]]
        assert row["owned_by"] == "xai"

    found = _by_id(_fetch(monkeypatch, payload))
    assert set(found) == set(IMAGE_IDS)
    for model_id, info in found.items():
        assert info.created == CREATED[model_id]
        assert type(info.created) is int
        assert info.owned_by == "xai"
        _assert_shipped_image_prices(info)


def test_hcc_c02_best_is_image_2_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C02: P_CREATED image best is grok-imagine-image-2.0."""
    rows = _image_ids(_fetch(monkeypatch, _p_created()))
    assert best_model(rows, role="image") == IMAGE_2


def test_hcc_c03_economy_is_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C03: P_CREATED image economy is grok-imagine-image-quality."""
    rows = _image_ids(_fetch(monkeypatch, _p_created()))
    assert economy_model(rows, role="image") == QUALITY


def _client(intent: str) -> XaiClient:
    return XaiClient(
        api_key=KEY,
        base_url=REGIONAL,
        intent=intent,
        provider=MockChatProvider("ok"),
    )


def test_hcc_c04_client_best_image_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C04: regional XaiClient intent best resolves image_model to 2.0."""
    _patch_get(monkeypatch, _p_created())
    client = _client("best")
    assert client.image_model == IMAGE_2


def test_hcc_c05_client_economy_image_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C05: regional XaiClient intent economy resolves image_model to quality."""
    _patch_get(monkeypatch, _p_created())
    client = _client("economy")
    assert client.image_model == QUALITY


def test_hcc_c06_reverse_order_same_picks(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C06: P_CREATED in reverse order still picks 2.0 and quality."""
    payload = _p_created(list(reversed(IMAGE_IDS)))
    parsed = _model_ids_from_payload(payload)
    assert [row["id"] for row in parsed] == list(reversed(IMAGE_IDS))
    for row in parsed:
        assert row["created"] == CREATED[row["id"]]
        assert type(row["created"]) is int

    rows = _image_ids(_fetch(monkeypatch, payload))
    found = {info.id: info for info in rows}
    for model_id, info in found.items():
        assert info.created == CREATED[model_id]
        assert type(info.created) is int
    assert best_model(rows, role="image") == IMAGE_2
    assert economy_model(rows, role="image") == QUALITY


def test_hcc_c07_missing_created_matches_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C07: P_NOCREATED best/economy/cheapest stay quality / image / image."""
    rows = _image_ids(_fetch(monkeypatch, _p_nocreated()))
    assert all(info.created is None for info in rows)
    assert best_model(rows, role="image") == QUALITY
    assert economy_model(rows, role="image") == IMAGE
    assert cheapest_model(rows, role="image") == IMAGE

    inject_catalog([ModelInfo(id=QUALITY, capabilities=["image"], created=99)])
    clear_catalog_cache()
    again = _by_id(_fetch(monkeypatch, _p_nocreated()))
    assert again[QUALITY].created == 99
    assert again[IMAGE].created is None
    assert again[IMAGE_2].created is None


def test_hcc_c08_client_missing_created_no_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C08: P_NOCREATED clients resolve to the base image ids and do not raise."""
    _patch_get(monkeypatch, _p_nocreated())
    best = _client("best")
    economy = _client("economy")
    assert best.image_model == QUALITY
    assert economy.image_model == IMAGE


def test_hcc_c09_bad_created_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C09: non-integer created, including ISO strings, is unset and does not raise."""
    rows = _image_ids(_fetch(monkeypatch, _p_badcreated()))
    assert len(rows) == 3
    assert all(info.created is None for info in rows)
    assert best_model(rows, role="image") == QUALITY
    assert economy_model(rows, role="image") == IMAGE
    assert cheapest_model(rows, role="image") == IMAGE


def test_hcc_c10_mixed_created_ranks_missing_as_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C10: created on 2.0 only. Best is 2.0. Economy is the recorded default.

    Rows without created rank as created unset (oldest). That puts quality
    ahead of image in the cheaper band, so economy is grok-imagine-image-quality.
    """
    found = _by_id(_fetch(monkeypatch, _p_mixed()))
    assert found[IMAGE_2].created == CREATED[IMAGE_2]
    assert type(found[IMAGE_2].created) is int
    assert found[IMAGE].created is None
    assert found[QUALITY].created is None
    rows = list(found.values())
    assert best_model(rows, role="image") == IMAGE_2
    recorded_economy = economy_model(rows, role="image")
    assert recorded_economy == QUALITY


def test_hcc_c11_skips_rows_without_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C11: missing ids and non-dict rows are skipped, and do not raise."""
    payload = {
        "object": "list",
        "data": [
            "nope",
            None,
            ["grok-imagine-image"],
            {"object": "model", "owned_by": "xai"},
            {"id": ""},
            {"id": "   ", "created": 1},
            _image_row(IMAGE, CREATED[IMAGE]),
            5,
            _image_row(IMAGE, 1),
        ],
    }
    rows = _fetch(monkeypatch, payload)
    assert [info.id for info, _role in rows] == [IMAGE]
    assert rows[0][0].created == CREATED[IMAGE]

    empty = {"object": "list", "data": ["nope", None, {"object": "model"}, 5]}
    _patch_get(monkeypatch, empty)
    with pytest.raises(RuntimeError, match="empty data list"):
        fetch_host_catalog(KEY, REGIONAL)


def test_hcc_c12_default_host_uses_fake_sdk_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C12: the default host ignores a REST payload and keeps the SDK catalog."""
    calls = _patch_get(monkeypatch, _p_created())

    def _fetch_sdk(_key: str) -> list[ModelInfo]:
        return [row.model_copy() for row in _SDK_CATALOG]

    set_test_fetch(_fetch_sdk)
    clear_catalog_cache()
    expected = {
        "chat": "grok-4.7",
        "image": IMAGE,
        "video": "grok-imagine-video-1.5",
        "voice": "grok-voice-latest",
    }
    for role, model_id in expected.items():
        assert resolve_model(catalog=_SDK_CATALOG, intent="best", role=role) == model_id

    assert DEFAULT_BASE_URL == "https://api.x.ai/v1"
    plain = XaiClient(api_key=KEY, intent="best", provider=MockChatProvider("ok"))
    explicit = XaiClient(
        api_key=KEY,
        base_url=DEFAULT_BASE_URL,
        intent="best",
        provider=MockChatProvider("ok"),
    )
    for client in (plain, explicit):
        assert client.model == expected["chat"]
        assert client.image_model == expected["image"]
        assert client.video_model == expected["video"]
        assert client.voice_model == expected["voice"]
    assert calls == []

    image = model_info_from_image_proto(
        SimpleNamespace(
            name=IMAGE,
            aliases=[],
            version="1",
            image_price=None,
            created=300,
            max_prompt_length=0,
        )
    )
    assert image.created == 300
    assert type(image.created) is int
    language = model_info_from_language_proto(
        SimpleNamespace(
            name="grok-4.7",
            aliases=[],
            version="1",
            output_modalities=[],
            input_modalities=[],
            created=20,
            max_prompt_length=128000,
            prompt_text_token_price=None,
            completion_text_token_price=None,
        )
    )
    assert language.created == 20
    assert type(language.created) is int


def test_hcc_c13_regional_catalog_and_base_url_suites_remain() -> None:
    """HCC-C13: existing regional, catalog, and custom base URL tests stay in place."""
    root = Path(__file__).resolve().parent
    required = {
        "test_regional_endpoint.py": "def test_r1_6_default_host_unchanged",
        "test_catalog.py": "def test_fetch_includes_image_models",
        "test_catalog_role_rules.py": "def test_l1_chat_newer_or_higher_lite_loses_best",
        "test_catalog_snapshot_dates.py": "def test_s1_1_compact_video_plain_beats_snapshot_same_created",
        "test_custom_base_url.py": "def test_u2_1_proxy_parses_chat_image_models_and_async",
    }
    for name, needle in required.items():
        text = (root / name).read_text(encoding="utf-8")
        assert needle in text


def test_hcc_c14_prices_stay_on_shipped_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """HCC-C14: payload prices do not replace shipped or injected rates."""
    payload = {
        "object": "list",
        "data": [
            {
                "id": "grok-4.7",
                "object": "model",
                "owned_by": "xai",
                "created": 1700000000,
                "input_per_million": 0,
                "output_per_million": 0,
                "cached_input_per_million": 0,
                "per_call_usd": 0,
            },
            {
                "id": QUALITY,
                "object": "model",
                "owned_by": "xai",
                "created": CREATED[QUALITY],
                "input_per_million": 0,
                "output_per_million": 0,
                "per_call_usd": 0,
                "per_image_usd": 0,
            },
        ],
    }
    found = _by_id(_fetch(monkeypatch, payload))
    for model_id in ("grok-4.7", QUALITY):
        base, base_role = describe_listed_id(model_id)
        host = found[model_id]
        _role = next(role for info, role in fetch_host_catalog(KEY, REGIONAL) if info.id == model_id)
        assert _role == base_role
        base_dump = base.model_dump()
        host_dump = host.model_dump()
        for key in ("created", "owned_by"):
            base_dump.pop(key)
            host_dump.pop(key)
        assert host_dump == base_dump
        assert host.input_per_million == base.input_per_million
        assert host.output_per_million == base.output_per_million
        assert host.per_image_usd == base.per_image_usd
    assert found["grok-4.7"].input_per_million == 2.0
    assert found["grok-4.7"].output_per_million == 6.0
    assert found["grok-4.7"].created == 1700000000
    assert type(found["grok-4.7"].created) is int
    assert found["grok-4.7"].owned_by == "xai"
    assert found[QUALITY].created == CREATED[QUALITY]
    assert found[QUALITY].owned_by == "xai"

    inject_catalog(
        [
            ModelInfo(
                id="grok-4.7",
                capabilities=["chat"],
                input_per_million=9.0,
                output_per_million=8.0,
                created=5,
            )
        ]
    )
    clear_catalog_cache()
    injected = _by_id(_fetch(monkeypatch, payload))["grok-4.7"]
    assert injected.input_per_million == 9.0
    assert injected.output_per_million == 8.0
    assert injected.created == 1700000000
    assert injected.owned_by == "xai"


def test_model_info_created_coerces_like_base() -> None:
    """ModelInfo.created still accepts the inputs base coerced. Host parsing does not."""
    cases = (
        ("1751328000", 1751328000),
        (1751328000.0, 1751328000),
        (True, 1),
    )
    for raw, expected in cases:
        info = ModelInfo(id="grok-imagine-image", created=raw)
        assert info.created == expected
        assert type(info.created) is int
