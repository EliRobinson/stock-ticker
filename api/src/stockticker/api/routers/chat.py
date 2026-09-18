"""`POST /api/v1/chat` — the AI SDK UI message stream (system design §6).

Left as a stub: the Anthropic tool loop, the SQL guard, and the stream
encoder are a separate, larger piece of work. `stockticker.models.views`
(`TableSpec`/`ChartSpec`) is already in place for whoever picks it up.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["chat"])


@router.post("/chat", responses={501: {"model": ProblemDetail}})
async def chat(request: Request) -> None:
    raise HTTPException(status_code=501, detail="chat not implemented yet")
