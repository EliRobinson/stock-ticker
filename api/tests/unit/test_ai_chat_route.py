"""`POST /api/v1/chat` over HTTP: headers, no compression, the no-key stream,
and problem+json for a body that is not a conversation."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware
from support.ai_fakes import parse_sse

from stockticker.api.app import create_app
from stockticker.config import get_settings

BODY = {
    "id": "chat-1",
    "messages": [{"id": "u1", "role": "user", "parts": [{"type": "text", "text": "Top 5 by market cap?"}]}],
    "trigger": "submit-message",
    "messageId": None,
}


@pytest_asyncio.fixture
async def app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


async def post(app: FastAPI, json: object, **headers: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        return await client.post("/api/v1/chat", json=json, headers=headers)


async def test_streams_the_ui_message_protocol_headers(app: FastAPI) -> None:
    response = await post(app, BODY)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert "x-request-id" in response.headers


async def test_without_a_key_the_stream_says_ai_is_off(app: FastAPI) -> None:
    parts = parse_sse((await post(app, BODY)).text)
    assert parts[1:] == [
        {"type": "error", "errorText": "AI is off. ANTHROPIC_API_KEY is not set."},
        {"type": "finish", "finishReason": "error"},
        "[DONE]",
    ]
    assert isinstance(parts[0], dict) and parts[0]["type"] == "start"


async def test_the_stream_is_never_compressed(app: FastAPI) -> None:
    app.add_middleware(GZipMiddleware, minimum_size=1)
    response = await post(app, BODY, **{"accept-encoding": "gzip"})
    assert "content-encoding" not in response.headers
    assert response.text.startswith("data: ")


@pytest.mark.parametrize(
    "body",
    [
        {"messages": []},
        {"messages": [{"role": "assistant", "parts": [{"type": "text", "text": "hi"}]}]},
        {"messages": [{"role": "robot", "parts": []}]},
        {"id": "x"},
    ],
)
async def test_a_body_that_is_not_a_conversation_is_a_422_problem(app: FastAPI, body: object) -> None:
    response = await post(app, body)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 422


def test_openapi_documents_the_data_view_part(app: FastAPI) -> None:
    spec = app.openapi()
    content = spec["paths"]["/api/v1/chat"]["post"]["responses"]["200"]["content"]
    assert content["text/event-stream"]["schema"] == {"$ref": "#/components/schemas/DataViewPart"}
    data = spec["components"]["schemas"]["DataViewPart"]["properties"]["data"]
    assert data["discriminator"]["propertyName"] == "kind"
