"""Resolve the inference base URL and join REST and websocket paths onto it.

Precedence is the constructor argument, then the ``XAI_BASE_URL`` environment
variable, then :data:`DEFAULT_BASE_URL`. Blank values are skipped. The choice
is fixed when a client is constructed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://api.x.ai/v1"
XAI_BASE_URL_ENV = "XAI_BASE_URL"

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def strip_one_trailing_slash(url: str) -> str:
    """Remove a single trailing slash. The path is otherwise unchanged."""
    if url.endswith("/"):
        return url[:-1]
    return url


def websocket_origin(http_base: str) -> str:
    """Map ``https`` to ``wss`` and ``http`` to ``ws``. Host, port, and path stay."""
    base = strip_one_trailing_slash(http_base)
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    raise ValueError("base_url scheme must be http or https")


def join_url(base: str, suffix: str) -> str:
    """Join ``suffix`` onto ``base`` after stripping one trailing slash."""
    root = strip_one_trailing_slash(base)
    tail = suffix[1:] if suffix.startswith("/") else suffix
    if not tail:
        return root
    return f"{root}/{tail}"


@dataclass(frozen=True, slots=True)
class ResolvedBase:
    """One client's normalized inference base."""

    base_url: str
    scheme: str
    host: str
    port: int | None
    path: str
    ws_base: str
    chat_over_rest: bool
    models_over_rest: bool
    grpc_api_host: str | None
    grpc_insecure: bool

    @property
    def is_default(self) -> bool:
        return self.base_url == DEFAULT_BASE_URL


def resolve_base_url(explicit: str | None = None) -> ResolvedBase:
    """Arg, then ``XAI_BASE_URL``, then the default. Blank means unset."""
    if not _blank(explicit):
        raw = str(explicit).strip()
    else:
        env_value = os.environ.get(XAI_BASE_URL_ENV)
        if not _blank(env_value):
            raw = str(env_value).strip()
        else:
            raw = DEFAULT_BASE_URL
    return parse_base_url(raw)


def parse_base_url(raw: str) -> ResolvedBase:
    """Validate and normalize a base URL. Raises ``ValueError`` when it is unusable.

    The error text never includes the raw URL, so userinfo cannot leak.
    """
    text = strip_one_trailing_slash(str(raw).strip())
    parts = urlsplit(text)
    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError("base_url scheme must be http or https")
    if parts.username is not None or parts.password is not None:
        raise ValueError("base_url must not include userinfo")
    host = parts.hostname
    if not host:
        raise ValueError("base_url must include a host")
    if parts.query:
        raise ValueError("base_url must not include a query")
    if parts.fragment:
        raise ValueError("base_url must not include a fragment")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("base_url port is invalid") from exc

    path = parts.path or ""
    if ":" in host:
        host_render = f"[{host}]"
    else:
        host_render = host
    netloc = f"{host_render}:{port}" if port is not None else host_render
    base_url = f"{scheme}://{netloc}{path}"
    ws_scheme = "wss" if scheme == "https" else "ws"
    ws_base = f"{ws_scheme}://{netloc}{path}"
    chat_over_rest = path not in ("", "/v1")
    models_over_rest = base_url != DEFAULT_BASE_URL
    if base_url == DEFAULT_BASE_URL:
        grpc_api_host = None
        grpc_insecure = False
    else:
        grpc_api_host = netloc
        grpc_insecure = scheme == "http"
    return ResolvedBase(
        base_url=base_url,
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        ws_base=ws_base,
        chat_over_rest=chat_over_rest,
        models_over_rest=models_over_rest,
        grpc_api_host=grpc_api_host,
        grpc_insecure=grpc_insecure,
    )


def rebase_url(url: str, resolved: ResolvedBase) -> str:
    """Keep a default-base URL byte-identical. Otherwise swap in this client's prefix.

    ``url`` is a constant built from :data:`DEFAULT_BASE_URL` (HTTP or websocket).
    The suffix after that prefix is kept as given. Nothing appends ``/v1``.
    """
    if resolved.is_default:
        return url
    http_prefix = DEFAULT_BASE_URL
    ws_prefix = websocket_origin(DEFAULT_BASE_URL)
    if url.startswith(http_prefix):
        return resolved.base_url + url[len(http_prefix) :]
    if url.startswith(ws_prefix):
        return resolved.ws_base + url[len(ws_prefix) :]
    return url


XAI_STT_URL = join_url(DEFAULT_BASE_URL, "stt")
XAI_TTS_URL = join_url(DEFAULT_BASE_URL, "tts")
XAI_TTS_VOICES_URL = join_url(DEFAULT_BASE_URL, "tts/voices")
XAI_IMAGES_URL = join_url(DEFAULT_BASE_URL, "images/generations")
XAI_IMAGE_EDITS_URL = join_url(DEFAULT_BASE_URL, "images/edits")
XAI_FILES_URL = join_url(DEFAULT_BASE_URL, "files")
XAI_EMBEDDINGS_URL = join_url(DEFAULT_BASE_URL, "embeddings")
XAI_TOKENIZE_URL = join_url(DEFAULT_BASE_URL, "tokenize-text")
XAI_RESPONSES_URL = join_url(DEFAULT_BASE_URL, "responses")
XAI_CHAT_COMPLETIONS_URL = join_url(DEFAULT_BASE_URL, "chat/completions")
XAI_DEFERRED_CHAT_URL = join_url(DEFAULT_BASE_URL, "chat/deferred-completion")
XAI_REALTIME_CLIENT_SECRETS_URL = join_url(DEFAULT_BASE_URL, "realtime/client_secrets")
XAI_VIDEOS_URL = join_url(DEFAULT_BASE_URL, "videos/generations")
XAI_VIDEO_EXTENSIONS_URL = join_url(DEFAULT_BASE_URL, "videos/extensions")
XAI_VIDEO_STATUS_URL = join_url(DEFAULT_BASE_URL, "videos/{request_id}")

_WS_ROOT = websocket_origin(DEFAULT_BASE_URL)
XAI_STT_WS_URL = join_url(_WS_ROOT, "stt")
XAI_TTS_WS_URL = join_url(_WS_ROOT, "tts")
XAI_REALTIME_URL = join_url(_WS_ROOT, "realtime")
