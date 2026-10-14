"""Custom voice models, client-side checks, and response parsing.

HTTP lives on ``XaiClient`` and ``AsyncXaiClient``. This module stays free of
those clients so both can share one contract.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from xaikit.base_url import XAI_CUSTOM_VOICES_URL
from xaikit.errors import CustomVoiceError

CUSTOM_VOICE_TIMEOUT = 30.0
CUSTOM_VOICE_LONG_TIMEOUT = 120.0

OP_CREATE = "custom_voices.create"
OP_LIST = "custom_voices.list"
OP_GET = "custom_voices.get"
OP_UPDATE = "custom_voices.update"
OP_DELETE = "custom_voices.delete"
OP_DOWNLOAD = "custom_voices.download"

_VOICE_ID = re.compile(r"^[a-z0-9]{8}$")
_DETAIL_LIMIT = 500

CustomVoiceGender = Literal["male", "female", "neutral"]
CustomVoiceAge = Literal["young", "middle-aged", "old"]
CustomVoiceUseCase = Literal[
    "conversational",
    "narration",
    "characters",
    "educational",
    "advertisement",
    "social_media",
    "entertainment",
]
CustomVoiceTone = Literal[
    "warm",
    "casual",
    "professional",
    "friendly",
    "authoritative",
    "expressive",
    "calm",
]

_GENDERS: tuple[str, ...] = ("male", "female", "neutral")
_AGES: tuple[str, ...] = ("young", "middle-aged", "old")
_USE_CASES: tuple[str, ...] = (
    "conversational",
    "narration",
    "characters",
    "educational",
    "advertisement",
    "social_media",
    "entertainment",
)
_TONES: tuple[str, ...] = (
    "warm",
    "casual",
    "professional",
    "friendly",
    "authoritative",
    "expressive",
    "calm",
)
_ENUMS: dict[str, tuple[str, ...]] = {
    "gender": _GENDERS,
    "age": _AGES,
    "use_case": _USE_CASES,
    "tone": _TONES,
}
_TEXT_FIELDS: tuple[str, ...] = ("name", "description", "accent", "language")
_PATCH_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "gender",
    "accent",
    "age",
    "language",
    "use_case",
    "tone",
)
_CREATE_FIELDS: tuple[str, ...] = _PATCH_FIELDS

# Prefer the documented IANA types. The stdlib maps .wav to audio/x-wav.
_CONTENT_TYPES: dict[str, str] = {
    ".wav": "audio/wav",
    ".wave": "audio/wav",
    ".mp3": "audio/mpeg",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".webm": "audio/webm",
    ".aac": "audio/aac",
}
_CONTENT_TYPE_ALIASES: dict[str, str] = {
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/x-mpeg": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
}


class _UnsetType:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _UnsetType()


class CustomVoice(BaseModel):
    """One custom voice. Unknown enum values and extra fields are kept."""

    model_config = ConfigDict(extra="allow")

    voice_id: str
    name: str | None = None
    description: str | None = None
    gender: CustomVoiceGender | str | None = None
    accent: str | None = None
    age: CustomVoiceAge | str | None = None
    language: str | None = None
    use_case: CustomVoiceUseCase | str | None = None
    tone: CustomVoiceTone | str | None = None
    created_at: str | None = None


class CustomVoicePage(BaseModel):
    """One page from ``GET /v1/custom-voices``."""

    model_config = ConfigDict(extra="allow")

    voices: list[CustomVoice]
    pagination_token: str | None = None


def require_custom_voice_api_key(api_key: str | None) -> str:
    """Return a non-empty key or raise before any request."""
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError(
            "xAI credentials not configured. Pass api_key= or inject a "
            "CredentialStore before custom voice API calls."
        )
    return key


def check_voice_id(voice_id: object) -> str:
    """Accept only an 8 character lowercase id. Do not strip or recase it."""
    if isinstance(voice_id, str) and _VOICE_ID.fullmatch(voice_id):
        return voice_id
    raise ValueError("voice_id must match ^[a-z0-9]{8}$")


def check_limit(limit: object) -> int | None:
    """``None`` omits the query. Otherwise an int from 1 to 1000 inclusive."""
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer from 1 to 1000")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be an integer from 1 to 1000")
    return limit


def check_enum(field: str, value: object) -> None:
    """Reject a value outside the documented set. ``None`` means omit."""
    if value is None:
        return
    allowed = _ENUMS[field]
    if isinstance(value, str) and value in allowed:
        return
    choices = ", ".join(allowed)
    raise ValueError(f"{field} must be one of: {choices}")


def _check_text(field: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, str):
        return
    raise ValueError(f"{field} must be a string")


def list_query(
    limit: int | None,
    pagination_token: str | None,
) -> dict[str, Any] | None:
    """Query items in a stable order. ``None`` means no query string."""
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if pagination_token is not None:
        params["pagination_token"] = pagination_token
    if not params:
        return None
    return params


def _guess_content_type(filename: str, explicit: str | None) -> str:
    if explicit is not None and str(explicit).strip():
        media = str(explicit).split(";")[0].strip()
        return _CONTENT_TYPE_ALIASES.get(media, media) or "application/octet-stream"
    ext = Path(filename).suffix.lower()
    mapped = _CONTENT_TYPES.get(ext)
    if mapped:
        return mapped
    guessed, _encoding = mimetypes.guess_type(filename)
    if not guessed:
        return "application/octet-stream"
    return _CONTENT_TYPE_ALIASES.get(guessed, guessed)


def _filename_from_source(
    file: object,
    *,
    explicit: str | None,
    path_name: str | None,
) -> str:
    if explicit is not None and str(explicit).strip():
        return Path(str(explicit).strip()).name
    if path_name:
        return path_name
    name = getattr(file, "name", None)
    if isinstance(name, str) and name.strip():
        base = Path(name).name
        if base and base not in {".", ".."}:
            return base
    return "reference.wav"


def _read_file_bytes(file: object) -> tuple[bytes, str | None]:
    """Return file bytes and a path basename, or raise ``ValueError``."""
    if file is None:
        raise ValueError("file is required")
    if isinstance(file, (bytes, bytearray, memoryview)):
        return bytes(file), None
    if isinstance(file, (str, Path)) or isinstance(file, os.PathLike):
        path = Path(os.fspath(file))
        if not path.is_file():
            raise ValueError("file is required")
        return path.read_bytes(), path.name
    read = getattr(file, "read", None)
    if not callable(read):
        raise ValueError("file is required")
    try:
        data = read()
    except OSError as exc:
        raise ValueError("file is required") from exc
    if isinstance(data, str):
        raise ValueError("file must be binary")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("file must be binary")
    return bytes(data), None


def prepare_create(
    file: object,
    *,
    name: str | None = None,
    description: str | None = None,
    gender: str | None = None,
    accent: str | None = None,
    age: str | None = None,
    language: str | None = None,
    use_case: str | None = None,
    tone: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> tuple[bytes, str, str, dict[str, str]]:
    """Validate a create call and return bytes, filename, type, and form fields.

    Unset fields are omitted. Enum checks and the non-empty file check both
    finish before the caller opens a socket.
    """
    values: dict[str, object] = {
        "name": name,
        "description": description,
        "gender": gender,
        "accent": accent,
        "age": age,
        "language": language,
        "use_case": use_case,
        "tone": tone,
    }
    for field in _TEXT_FIELDS:
        _check_text(field, values[field])
    for field in _ENUMS:
        check_enum(field, values[field])

    data, path_name = _read_file_bytes(file)
    if not data:
        raise ValueError("file is required")
    chosen_name = _filename_from_source(
        file, explicit=filename, path_name=path_name
    )
    chosen_type = _guess_content_type(chosen_name, content_type)
    fields: dict[str, str] = {}
    for field in _CREATE_FIELDS:
        value = values[field]
        if value is None:
            continue
        fields[field] = str(value)
    return data, chosen_name, chosen_type, fields


def prepare_update(voice_id: object, values: dict[str, object]) -> tuple[str, dict[str, Any]]:
    """Validate a PATCH. Omitted keys stay out. ``None`` is JSON null.

    ``values`` uses :data:`UNSET` for arguments the caller did not pass.
    An empty string raises. A body with no keys raises.
    """
    checked = check_voice_id(voice_id)
    body: dict[str, Any] = {}
    for field in _PATCH_FIELDS:
        if field not in values:
            continue
        value = values[field]
        if value is UNSET:
            continue
        if value is None:
            body[field] = None
            continue
        if isinstance(value, str) and value == "":
            raise ValueError(f"{field} must not be an empty string")
        if field in _ENUMS:
            check_enum(field, value)
        elif not isinstance(value, str):
            raise ValueError(f"{field} must be a string or null")
        body[field] = value
    if not body:
        raise ValueError("update requires at least one field")
    return checked, body


def patch_bytes(body: dict[str, Any]) -> bytes:
    """JSON object with default spacing so nulls and key order stay exact."""
    return json.dumps(body).encode("utf-8")


def redact_secret(text: str, secret: str | None) -> str:
    """Remove the configured API key from text that might be logged or raised."""
    if not text or not secret:
        return text
    cleaned = text.replace(secret, "[redacted]")
    return cleaned


def custom_voice_failure(response: httpx.Response, api_key: str) -> CustomVoiceError:
    """Build a redacted :class:`CustomVoiceError` for any HTTP status >= 400."""
    raw = response.text if response.text else (response.reason_phrase or "")
    detail = redact_secret(str(raw), api_key)[:_DETAIL_LIMIT]
    status = int(response.status_code)
    message = redact_secret(
        f"Custom voice request failed ({status}): {detail}",
        api_key,
    )
    return CustomVoiceError(message, status_code=status)


def custom_voice_retryable(exc: BaseException) -> bool:
    """Retry HTTP 500 and transport errors. Never retry 4xx."""
    if isinstance(exc, CustomVoiceError):
        return exc.status_code == 500
    return isinstance(exc, httpx.TransportError)


def content_type_from_response(response: httpx.Response) -> str:
    """Media type from the header, or ``application/octet-stream`` when absent."""
    raw = response.headers.get("content-type")
    if raw is None:
        return "application/octet-stream"
    media = str(raw).split(";")[0].strip()
    if not media:
        return "application/octet-stream"
    return media


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("Custom voice response was not JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Custom voice response was not a JSON object")
    return payload


def parse_voice(response: httpx.Response) -> CustomVoice:
    """Parse a voice object. Unknown enums and extra fields are kept."""
    try:
        return CustomVoice.model_validate(_json_object(response))
    except Exception as exc:
        raise RuntimeError("Custom voice response did not match the voice object") from exc


def parse_page(response: httpx.Response) -> CustomVoicePage:
    """Parse a page. An empty ``voices`` list is a valid page."""
    try:
        return CustomVoicePage.model_validate(_json_object(response))
    except Exception as exc:
        raise RuntimeError("Custom voice response did not match a voice page") from exc


def item_url(voice_id: str, *, audio: bool = False) -> str:
    """Default-host URL. Callers rebase it onto the client base."""
    url = f"{XAI_CUSTOM_VOICES_URL}/{voice_id}"
    if audio:
        return f"{url}/audio"
    return url
