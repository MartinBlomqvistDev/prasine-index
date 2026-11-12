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

from core.logger import get_logger
from core.retry import LLMError

__all__ = [
    "CACHE_1H",
    "TOOL_CALL_ATTEMPTS",
    "fallback_body",
    "fallback_headers",
    "log_usage",
    "raise_if_refused",
    "usage_summary",
    "usage_totals",
]

logger = get_logger(__name__)

CACHE_1H: anthropic.types.CacheControlEphemeralParam = {"type": "ephemeral", "ttl": "1h"}
"""Cache marker for a prompt prefix that every company's run sends unchanged.

Companies are assessed one after another, about ten minutes each, so an entry
with the default five-minute lifetime has expired before the next company's
first call. A read refreshes the entry, so one hour carries it through a run.
"""

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


def log_usage(response: anthropic.types.Message, *, agent: str) -> None:
    """Log what one call billed, so that a run shows how much was read from cache.

    The prompt's full size is the sum of the three input fields: ``input_tokens``
    counts only what came after the last cache read or write.

    Args:
        response: The API response.
        agent: Name of the agent or ingest step that made the call.
    """
    usage = response.usage
    written = usage.cache_creation_input_tokens or 0
    read = usage.cache_read_input_tokens or 0
    prompt = usage.input_tokens + written + read
    fields = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": written,
        "cache_read_input_tokens": read,
    }
    totals = usage_totals.setdefault(agent, dict.fromkeys(("calls", *fields), 0))
    totals["calls"] += 1
    for key, value in fields.items():
        totals[key] += value
    logger.info(
        f"{agent} call: {read} of {prompt} prompt tokens read from cache, {written} written",
        extra={"operation": "llm_usage", "agent": agent, "llm_model_id": response.model, **fields},
    )


usage_totals: dict[str, dict[str, int]] = {}
"""Calls and token counts per agent since the process started, for a run's summary."""


def usage_summary() -> str:
    """Describe what every call so far read from and wrote to the cache, one line per agent.

    Returns:
        One indented line per agent, or "" before the first call.
    """
    lines = []
    for agent, totals in sorted(usage_totals.items()):
        read = totals["cache_read_input_tokens"]
        written = totals["cache_creation_input_tokens"]
        prompt = totals["input_tokens"] + written + read
        share = read / prompt if prompt else 0.0
        lines.append(
            f"  {agent}: {totals['calls']} calls, {read:,} of {prompt:,} prompt tokens "
            f"read from cache ({share:.0%}), {written:,} written"
        )
    return "\n".join(lines)


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
