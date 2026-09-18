"""HTTP streaming helpers for the chat route.

Keeps Starlette transport concerns out of `stockticker.ai.stream`, which owns
the UI-message protocol encoder and a framework-free disconnect relay.
"""

from __future__ import annotations

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive

from stockticker.ai.stream import (
    SSE_MEDIA_TYPE,
    UI_MESSAGE_STREAM_HEADERS,
    Producer,
    until_disconnected,
)


class SoleReceiverStreamingResponse(StreamingResponse):
    """A `StreamingResponse` that never reads `receive` itself.

    Under ASGI < 2.4 (uvicorn's HTTP scopes are 2.3) Starlette runs
    `listen_for_disconnect` next to the body, a second loop on `receive`.
    `until_disconnected` already owns `receive`, and ASGI does not promise
    that two readers both see `http.disconnect`, so this listener only waits
    to be cancelled when the body ends."""

    async def listen_for_disconnect(self, receive: Receive) -> None:
        await anyio.sleep_forever()


def ui_message_stream_response(producer: Producer, receive: Receive) -> StreamingResponse:
    return SoleReceiverStreamingResponse(
        until_disconnected(producer, receive),
        media_type=SSE_MEDIA_TYPE,
        headers=UI_MESSAGE_STREAM_HEADERS,
    )
