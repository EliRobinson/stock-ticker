"""Every message an Ask answer can end with, and how Anthropic errors map to
them. All of it is user-facing chrome: fact, consequence, action."""

from __future__ import annotations

import anthropic

NO_KEY = "AI is off. ANTHROPIC_API_KEY is not set."
DATABASE_UNREACHABLE = "The database is not reachable. Try again."
NO_QUESTION = "There is no question to answer. Send a message."
MESSAGE_TOO_LONG = "This message is too long to answer. Shorten it and send it again."
REFUSED = "The model declined to answer. Rephrase the question."
INTERNAL = "The answer stopped on an internal error. Try again."


def model_unpriced(model: str) -> str:
    return f"AI is off. Model {model} has no configured price."


def too_many_steps(max_steps: int) -> str:
    return f"Stopped after {max_steps} steps without a final answer. Ask a narrower question."


def out_of_time(wall_seconds: float) -> str:
    return f"Stopped after {wall_seconds:g} s without a final answer. Ask a narrower question."


def input_budget_used(max_input_tokens: int) -> str:
    return f"Stopped at this answer's {max_input_tokens:,} input-token limit. Ask a narrower question."


class AnswerStopped(Exception):
    """Ends the answer with an `error` part. `str()` is the user-facing text."""


_RETRYABLE_ERROR_TYPES = frozenset({"rate_limit_error", "overloaded_error", "api_error"})


def is_retryable(error: anthropic.APIStatusError) -> bool:
    """429, 529, and 5xx, including the same errors arriving mid-stream (the
    SDK raises those with the stream's 200 status and the type in the body)."""
    status = error.status_code
    if status in (429, 529) or status >= 500:
        return True
    body = error.body
    if isinstance(body, dict):
        inner = body.get("error")
        if isinstance(inner, dict) and inner.get("type") in _RETRYABLE_ERROR_TYPES:
            return True
    return False


def retry_after_seconds(error: anthropic.APIStatusError) -> float:
    value = error.response.headers.get("retry-after") if error.response is not None else None
    try:
        return max(0.0, float(value)) if value is not None else 1.0
    except ValueError:
        return 1.0


def describe(error: Exception) -> str:
    if isinstance(error, anthropic.AuthenticationError):
        return "Anthropic rejected ANTHROPIC_API_KEY. Set a valid key."
    if isinstance(error, anthropic.PermissionDeniedError):
        return "Anthropic refused the request (403). Check the key's permissions."
    if isinstance(error, anthropic.RateLimitError):
        return "Anthropic rate limit reached. Try again."
    if isinstance(error, anthropic.APIStatusError):
        if is_retryable(error):
            return f"Anthropic returned an error ({_error_type(error)}), so the answer stopped. Try again."
        return (
            f"Anthropic rejected the request ({_error_type(error)}), so the answer stopped. Start a new chat."
        )
    if isinstance(error, anthropic.APIConnectionError):
        return "Anthropic could not be reached. Try again."
    return INTERNAL


def _error_type(error: anthropic.APIStatusError) -> str:
    body = error.body
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("type") or error.status_code)
    return str(error.status_code)
