"""Examples/docs only: thin FastAPI routes wrapping :class:`xaikit.XaiClient`.

This is **not** XaiKit product identity and is **not** installed with the package.
Apps that want REST can copy this pattern; the sticky surface is the typed Python API.

Starlette note: FastAPI is Starlette-based — the same thin wrap works on a bare
``Starlette`` app (route callables that invoke ``client.chat`` / return JSON).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from xaikit import XaiClient


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    purpose: str | None = Field(
        default=None,
        description="Required when the injected XaiClient has a UsageMeter.",
    )
    temperature: float = 0.7
    max_tokens: int | None = None
    system_prompt: str | None = None
    thought_level: str | None = None
    effort: str | None = None
    parent_id: str | None = None


class ChatResponse(BaseModel):
    content: str
    model: str | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None


def create_xaikit_router(client: XaiClient, *, prefix: str = "") -> APIRouter:
    """Return a mountable router that delegates to an injected :class:`XaiClient`."""
    router = APIRouter(prefix=prefix, tags=["xaikit-example"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        return {
            "ok": True,
            "model": client.model,
            "thought_level": client.thought_level,
            "surface": "examples/docs only — not XaiKit product identity",
        }

    @router.post("/chat", response_model=ChatResponse)
    def chat(body: ChatRequest) -> ChatResponse:
        messages = [m.model_dump() for m in body.messages]
        try:
            resp = client.chat(
                messages,
                purpose=body.purpose,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                system_prompt=body.system_prompt,
                thought_level=body.thought_level,
                effort=body.effort,
                parent_id=body.parent_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return ChatResponse(
            content=resp.content,
            model=resp.model,
            usage=resp.usage,
            finish_reason=resp.finish_reason,
        )

    return router


def create_app(client: XaiClient) -> FastAPI:
    """Build a tiny demo app with ``GET /status`` and ``POST /chat``."""
    app = FastAPI(
        title="XaiKit HTTP mount example",
        description=(
            "Examples/docs only. Prefer the typed ``XaiClient`` API in real apps; "
            "use this pattern only when you want a thin REST wrapper."
        ),
        version="0.0.0-example",
    )
    app.include_router(create_xaikit_router(client))
    return app
