"""`POST /api/v1/chat` over HTTP: headers, no compression, the no-key stream,
and problem+json for a body that is not a conversation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from ai_fakes import (
    ScriptedAnthropic,
    make_deps,
    message_end,
    message_start,
    parse_sse,
    part_types,
    text_block,
)
from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

from stockticker.api.app import create_app
from stockticker.api.routers import chat as chat_router
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
        {
            "messages": [
                {"role": "user", "parts": [{"type": "text", "text": "q"}]},
                {"role": "assistant", "parts": [{"type": "tool-run_sql", "state": "output-available"}]},
            ]
        },
    ],
)
async def test_a_body_that_is_not_a_conversation_is_a_422_problem(app: FastAPI, body: object) -> None:
    response = await post(app, body)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 422


async def test_a_part_type_this_server_does_not_know_still_streams_an_answer(app: FastAPI) -> None:
    message = {
        "id": "u1",
        "role": "user",
        "parts": [{"type": "hologram", "x": 1}, {"type": "text", "text": "q"}],
    }
    response = await post(app, {**BODY, "messages": [message]})
    assert response.status_code == 200
    assert part_types(response.text)[-1] == "[DONE]"


def test_openapi_documents_the_data_view_part(app: FastAPI) -> None:
    spec = app.openapi()
    content = spec["paths"]["/api/v1/chat"]["post"]["responses"]["200"]["content"]
    assert content["text/event-stream"]["schema"] == {"$ref": "#/components/schemas/DataViewPart"}
    data = spec["components"]["schemas"]["DataViewPart"]["properties"]["data"]
    assert data["discriminator"]["propertyName"] == "kind"


def test_openapi_documents_the_request_body(app: FastAPI) -> None:
    body = app.openapi()["paths"]["/api/v1/chat"]["post"]["requestBody"]
    schema = body["content"]["application/json"]["schema"]
    assert "messages" in schema["properties"]
    assert "$ref" not in str(schema)


async def test_a_body_over_1_mb_is_a_413_problem(app: FastAPI) -> None:
    big = {**BODY, "messages": [BODY["messages"][0]] * 60, "padding": "x" * (1024 * 1024)}  # type: ignore[index]
    response = await post(app, big)
    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "The request is larger than 1 MB. Start a new chat."


async def test_an_overlong_text_part_is_a_422_problem(app: FastAPI) -> None:
    body = {"messages": [{"role": "user", "parts": [{"type": "text", "text": "x" * 32_001}]}]}
    response = await post(app, body)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


class AsgiClient:
    """Drives the app at the ASGI level: sends the body, then holds every
    later `receive` until `leave()`, counting how many wait at once."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.sent_body = False
        self.gone = asyncio.Event()
        self.waiting = 0
        self.most_waiting = 0
        self.sent: list[dict[str, Any]] = []
        self.chunk_arrived = asyncio.Event()

    def leave(self) -> None:
        self.gone.set()

    async def receive(self) -> dict[str, Any]:
        if not self.sent_body:
            self.sent_body = True
            return {"type": "http.request", "body": self.body, "more_body": False}
        self.waiting += 1
        self.most_waiting = max(self.most_waiting, self.waiting)
        try:
            await self.gone.wait()
        finally:
            self.waiting -= 1
        return {"type": "http.disconnect"}

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        self.chunk_arrived.set()

    def body_text(self) -> str:
        return "".join(m.get("body", b"").decode() for m in self.sent if m["type"] == "http.response.body")


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_one_reader_waits_for_the_disconnect_and_it_cancels_the_answer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, spec_version: str
) -> None:
    # uvicorn's HTTP scopes say 2.3, where Starlette's StreamingResponse would
    # add its own receive loop; under 2.4 it would add none.
    anthropic = ScriptedAnthropic(
        message_start() + text_block(0, "a", "b") + message_end("end_turn"), stall_after_first_chunk=True
    )
    monkeypatch.setattr(chat_router, "build_chat_deps", lambda settings: make_deps(anthropic))
    body = json.dumps(BODY).encode()
    client = AsgiClient(body)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/chat",
        "raw_path": b"/api/v1/chat",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    served = asyncio.create_task(app(scope, client.receive, client.send))  # type: ignore[arg-type]
    while "text-start" not in part_types(client.body_text()):
        client.chunk_arrived.clear()
        await asyncio.wait_for(client.chunk_arrived.wait(), timeout=2)
    await asyncio.sleep(0.05)
    assert client.most_waiting == 1

    client.leave()
    await asyncio.wait_for(served, timeout=2)
    await asyncio.wait_for(anthropic.stream_closed.wait(), timeout=2)
    assert part_types(client.body_text()) == ["start", "start-step", "text-start"]
    assert client.most_waiting == 1
