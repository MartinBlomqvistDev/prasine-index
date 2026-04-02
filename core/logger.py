"""Structured JSON logging for the Prasine Index pipeline.

Every log record is emitted as a single-line JSON object compatible with Google
Cloud Logging, Datadog, and any log aggregation tool that ingests NDJSON. The
claim-level trace_id is propagated via a ContextVar so every log line produced
by any agent step is automatically correlated without threading the ID through
every function signature.
"""

from __future__ import annotations

import contextvars
import json
import logging
import uuid
from typing import Any

__all__ = [
    "agent_name_var",
    "claim_id_var",
    "get_logger",
    "setup_logging",
    "trace_id_var",
]


# ---------------------------------------------------------------------------
# Pipeline context variables — set by each agent at entry, read by formatter
# ---------------------------------------------------------------------------

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default="-"
)
"""Claim-level trace identifier.

Set once when a Claim enters the pipeline and inherited by every agent step
that processes it. Links all log lines, AgentTrace rows, and Evidence records
for a single claim across the full 7-agent run.

Usage::

    from core.logger import trace_id_var
    trace_id_var.set(str(claim.trace_id))
"""

claim_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "claim_id", default="-"
)
"""Claim identifier for the active execution context.

Set alongside trace_id_var at pipeline entry. Included in every log record
to enable filtering all logs for a specific claim without a full trace scan.
"""

agent_name_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_name", default="-"
)
"""Name of the currently executing agent.

Set by each agent at the start of its run method. Allows per-agent log
filtering and latency analysis without parsing the logger name field.

Usage::

    from core.logger import agent_name_var
    agent_name_var.set(AgentName.EXTRACTION.value)
"""


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class _JSONFormatter(logging.Formatter):
    """Serialises every LogRecord to a single-line JSON object.

    The ``trace_id``, ``claim_id``, and ``agent`` fields are injected
    automatically from the pipeline ContextVars, so caller code never
    needs to pass them explicitly.

    Callers may attach structured fields via the ``extra`` keyword argument
    to :py:func:`logging.Logger.info` et al. Any key listed in
    ``_EXTRA_FIELDS`` that is present in the record's ``__dict__`` will
    be included in the output JSON.
    """

    # Structured fields that agents pass via extra={...}
    _EXTRA_FIELDS: tuple[str, ...] = (
        "operation",          # logical operation name, e.g. "claim_extracted"
        "duration_ms",        # integer milliseconds for the logged step
        "agent",              # overrides agent_name_var when set explicitly
        "outcome",            # AgentOutcome value
        "tokens_used",        # LLM token count for the step
        "llm_model_id",       # model identifier, e.g. "claude-opus-4-6"
        "retry_count",        # number of retries attempted
        "source",             # EvidenceSource value for Verification Agent logs
        "claim_category",     # ClaimCategory value
        "score",              # GreenwashingScore.score
        "verdict",            # ScoreVerdict value
        "http_status",        # upstream HTTP status code on external API calls
        "error_type",         # exception class name on failures
        "data_year",          # reference year for evidence data
        "company_id",         # company UUID for company-level log correlation
    )

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a log record to a single-line JSON string.

        Args:
            record: The log record to format.

        Returns:
            A single-line JSON string with all standard and extra fields.
        """
        obj: dict[str, Any] = {
            "time":     self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%SZ"),
            "level":    record.levelname,
            "logger":   record.name,
            "trace_id": trace_id_var.get(),
            "claim_id": claim_id_var.get(),
            "agent":    record.__dict__.get("agent") or agent_name_var.get(),
            "message":  record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            if field == "agent":
                continue  # already handled above
            value = record.__dict__.get(field)
            if value is not None:
                obj[field] = value
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging for all Prasine Index loggers.

    Must be called exactly once at application startup, before any logger
    is used. Configures all first-party namespaces (``agents``, ``core``,
    ``ingest``, ``api``, ``eval``) to emit single-line JSON. The root logger
    also receives the JSON handler so that third-party library warnings
    (``httpx``, ``sqlalchemy``, ``langgraph``) are captured in structured form.

    Uvicorn's own access-log handler is not touched, preserving readable
    startup messages in development.

    Args:
        level: Logging level name (case-insensitive). Defaults to ``"INFO"``.
            Set to ``"DEBUG"`` in development to capture agent prompt/response
            payloads.

    Example::

        # api/main.py or pipeline entry point
        from core.logger import setup_logging
        setup_logging(level="INFO")
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())

    # First-party namespaces: JSON handler only, no propagation
    for namespace in ("agents", "core", "ingest", "api", "eval"):
        log = logging.getLogger(namespace)
        log.setLevel(numeric_level)
        log.handlers = [handler]
        log.propagate = False

    # Root logger: add JSON handler alongside any existing handlers so that
    # third-party library messages (httpx, sqlalchemy, langgraph) are also
    # emitted as structured records
    root = logging.getLogger()
    root.setLevel(numeric_level)
    if not any(isinstance(h.formatter, _JSONFormatter) for h in root.handlers):
        root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under the Prasine Index hierarchy.

    Wraps :py:func:`logging.getLogger` with a convention: if ``name`` is a
    bare module ``__name__`` such as ``"extraction_agent"`` it is returned
    as-is; if it is already a dotted path it is returned unchanged. The intent
    is that callers use ``get_logger(__name__)`` at the top of every module,
    which gives per-module granularity in log filtering without requiring
    callers to know the package structure.

    Args:
        name: Logger name, typically the module ``__name__``.

    Returns:
        A :py:class:`logging.Logger` instance.

    Example::

        from core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Claim extracted", extra={"operation": "claim_extracted", "duration_ms": 142})
    """
    return logging.getLogger(name)


def bind_trace_context(
    trace_id: uuid.UUID,
    claim_id: uuid.UUID | None = None,
    agent_name: str | None = None,
) -> None:
    """Set pipeline context variables for the current async task.

    Call this at the entry point of each agent run, after which all log
    records emitted in the same async context will automatically carry the
    correct ``trace_id``, ``claim_id``, and ``agent`` fields.

    Because these are :py:class:`contextvars.ContextVar` values, they are
    scoped to the current :py:class:`asyncio.Task` and do not bleed across
    concurrent pipeline runs.

    Args:
        trace_id: The claim-level trace identifier.
        claim_id: The claim being processed. Pass ``None`` only for the
            Discovery Agent, which produces claims rather than consuming them.
        agent_name: The :py:class:`~models.trace.AgentName` value for the
            executing agent, e.g. ``AgentName.EXTRACTION.value``.

    Example::

        from core.logger import bind_trace_context
        from models.trace import AgentName

        async def run(self, claim: Claim) -> ...:
            bind_trace_context(claim.trace_id, claim.id, AgentName.EXTRACTION.value)
            ...
    """
    trace_id_var.set(str(trace_id))
    if claim_id is not None:
        claim_id_var.set(str(claim_id))
    if agent_name is not None:
        agent_name_var.set(agent_name)
