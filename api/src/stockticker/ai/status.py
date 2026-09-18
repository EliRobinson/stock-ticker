"""The AI block of `/api/v1/status`: spend against `AI_SPEND_LIMIT_USD` and
whether Ask can answer. This is the one place that policy lives; the status
router only calls `ai_status`.

`enabled` fails closed: it is false without a key, for a model with no
price, when the ledger cannot be read, and when the spend so far leaves no
room for a typical call's worst case (the same worst case the spend gate
reserves before every call).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.exc import DBAPIError

from stockticker.ai.loop import Limits
from stockticker.ai.pricing import ModelPrice, price_for, worst_case_cost_usd
from stockticker.ai.spend import PostgresSpendLedger
from stockticker.config import Settings
from stockticker.db import get_api_app_writer_engine
from stockticker.logging import get_logger
from stockticker.models.status import AiStatus

logger = get_logger(__name__)

TYPICAL_CALL_INPUT_TOKENS = 40_000
"""The input bound of a first call: tools, the system prompt with the schema,
and a short conversation, counted the way the gate counts it (bytes)."""


def typical_worst_case_usd(price: ModelPrice) -> Decimal:
    return worst_case_cost_usd(
        price, max_input_tokens=TYPICAL_CALL_INPUT_TOKENS, max_output_tokens=Limits().max_output_tokens
    )


async def ai_status(settings: Settings) -> AiStatus:
    limit = settings.ai_spend_limit_usd
    try:
        spent = await PostgresSpendLedger(get_api_app_writer_engine()).spent_usd()
    except DBAPIError as error:
        logger.warning("ai_status_ledger_unreadable", error=str(error).splitlines()[0])
        return AiStatus(spend_usd=0.0, limit_usd=float(limit), enabled=False)
    price = price_for(settings.ai_model)
    enabled = (
        bool(settings.anthropic_api_key)
        and price is not None
        and spent + typical_worst_case_usd(price) <= limit
    )
    return AiStatus(spend_usd=float(spent), limit_usd=float(limit), enabled=enabled)
