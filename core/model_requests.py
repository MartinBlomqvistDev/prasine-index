"""Request options and response checks shared by every Anthropic call site.

The extraction, judge, report and source-document calls all run on models that
can decline a request through a safety classifier, and the judge and report
models accept a server-side fallback to another model when that happens. These
models also reject a forced ``tool_choice``, so the tool-calling sites ask for
the tool in the prompt and try again when the model answers without it. Keeping
the shared rules here means a model swap is a configuration change.
"""

from __future__ import annotations

import anthropic

from core.retry import LLMError

__all__ = [
    "TOOL_CALL_ATTEMPTS",
    "fallback_body",
    "fallback_headers",
    "raise_if_refused",
]

TOOL_CALL_ATTEMPTS = 2
"""How many times a tool-calling site sends the request before giving up.

With ``tool_choice`` on ``auto`` the model can occasionally answer in text
instead of calling the tool; one more attempt is enough to recover from that.
"""

# Models that accept the "default" form of server-side refusal fallback. Haiku
# 5.5 is deliberately absent: it has no server-side fallback.
_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})

_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def fallback_headers(model_id: str) -> dict[str, str] | None:
    """Return the beta header that enables server-side refusal fallback.

    Args:
        model_id: The model the request is sent to.

    Returns:
        The ``anthropic-beta`` header for models that support the fallback,
        otherwise ``None``.
    """
    if model_id not in _FALLBACK_MODELS:
        return None
    return {"anthropic-beta": _FALLBACK_BETA}


def fallback_body(model_id: str) -> dict[str, object] | None:
    """Return the request field that enables server-side refusal fallback.

    With ``fallbacks`` set to ``"default"`` the API reruns a declined request
    on the model Anthropic recommends for the refusal category.

    Args:
        model_id: The model the request is sent to.

    Returns:
        The extra body field for models that support the fallback, otherwise
        ``None``.
    """
    if model_id not in _FALLBACK_MODELS:
        return None
    return {"fallbacks": "default"}


def raise_if_refused(response: anthropic.types.Message, *, agent: str, model_id: str) -> None:
    """Raise when the model declined the request instead of answering it.

    A refusal arrives as a normal response with ``stop_reason == "refusal"``.
    Reading its content as an answer would publish an empty or partial result.

    Args:
        response: The API response.
        agent: Name of the agent that made the call.
        model_id: Model identifier, recorded on the error.

    Raises:
        :py:class:`~core.retry.LLMError`: If the response is a refusal. Not
            retryable, since the same request is declined again.
    """
    if response.stop_reason != "refusal":
        return
    category = response.stop_details.category if response.stop_details else None
    raise LLMError(
        message=f"Model {model_id} declined the request (refusal category: {category!r}).",
        agent=agent,
        retryable=False,
        llm_model_id=model_id,
    )
