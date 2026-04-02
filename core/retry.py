"""Retry logic and error boundaries for the Prasine Index agent pipeline.

Provides a configurable async retry decorator with full-jitter exponential
backoff, a typed exception hierarchy that distinguishes retryable from
non-retryable failures, and an agent_error_boundary context manager that ensures
every failure is logged with full structured context before propagating. No
failure in the pipeline is silent.
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import anthropic
import httpx

from core.logger import get_logger

__all__ = [
    "DataSourceError",
    "ExtractionError",
    "LLMError",
    "NonRetryableError",
    "PrasineError",
    "RetryConfig",
    "RetryExhaustedError",
    "agent_error_boundary",
    "classify_anthropic_error",
    "classify_http_error",
    "retry_async",
]

logger = get_logger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class PrasineError(Exception):
    """Base exception for all Prasine Index pipeline failures.

    Every exception raised within the pipeline inherits from this class,
    making it straightforward to distinguish pipeline failures from unexpected
    third-party exceptions in calling code.

    Attributes:
        message: Human-readable description of the failure.
        agent: Name of the agent in which the failure occurred, if known.
        retryable: Whether the operation that raised this exception may
            succeed on a subsequent attempt.
    """

    def __init__(
        self,
        message: str,
        agent: str | None = None,
        retryable: bool = True,
    ) -> None:
        """Initialise the base pipeline exception.

        Args:
            message: Human-readable description of the failure.
            agent: Name of the agent in which the failure occurred.
            retryable: Whether retrying the operation may succeed.
        """
        super().__init__(message)
        self.message = message
        self.agent = agent
        self.retryable = retryable

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"message={self.message!r}, "
            f"agent={self.agent!r}, "
            f"retryable={self.retryable})"
        )


class NonRetryableError(PrasineError):
    """A pipeline failure that must not be retried.

    Raised when retrying would be futile or harmful — for example, when the
    LLM returns a response that is structurally valid but semantically
    unacceptable (prompt-level failure rather than transient network error),
    or when a data source returns HTTP 400/401/403/404.
    """

    def __init__(self, message: str, agent: str | None = None) -> None:
        """Initialise a non-retryable pipeline exception.

        Args:
            message: Human-readable description of the failure.
            agent: Name of the agent in which the failure occurred.
        """
        super().__init__(message, agent=agent, retryable=False)


class LLMError(PrasineError):
    """Failure during an LLM API call.

    Wraps Anthropic SDK errors with pipeline context. Rate-limit errors
    (HTTP 429) and server errors (HTTP 5xx) are retryable; authentication
    errors (HTTP 401) and invalid-request errors (HTTP 400) are not.

    Attributes:
        status_code: HTTP status code returned by the Anthropic API, if
            the failure was an HTTP-level error.
        llm_model_id: Model identifier that was called when the error occurred.
    """

    def __init__(
        self,
        message: str,
        agent: str | None = None,
        retryable: bool = True,
        status_code: int | None = None,
        llm_model_id: str | None = None,
    ) -> None:
        """Initialise an LLM API failure.

        Args:
            message: Human-readable description of the failure.
            agent: Name of the agent in which the failure occurred.
            retryable: Whether retrying may succeed.
            status_code: HTTP status code from the Anthropic API response.
            llm_model_id: Model identifier that was called.
        """
        super().__init__(message, agent=agent, retryable=retryable)
        self.status_code = status_code
        self.llm_model_id = llm_model_id


class DataSourceError(PrasineError):
    """Failure when querying an external EU open data source.

    Raised by ingest modules when an upstream API call fails. HTTP 5xx and
    network timeouts are retryable; HTTP 4xx responses are not, as they
    indicate a structural problem with the request (bad identifier, resource
    not found, rate-limited with no retry-after).

    Attributes:
        source: The EvidenceSource identifier (e.g. ``"EU_ETS"``).
        status_code: HTTP status code returned by the upstream source.
    """

    def __init__(
        self,
        message: str,
        source: str | None = None,
        agent: str | None = None,
        retryable: bool = True,
        status_code: int | None = None,
    ) -> None:
        """Initialise a data source failure.

        Args:
            message: Human-readable description of the failure.
            source: The EvidenceSource identifier.
            agent: Name of the agent in which the failure occurred.
            retryable: Whether retrying may succeed.
            status_code: HTTP status code from the upstream response.
        """
        super().__init__(message, agent=agent, retryable=retryable)
        self.source = source
        self.status_code = status_code


class ExtractionError(PrasineError):
    """Failure during LLM-based structured output extraction.

    Raised when the LLM response cannot be parsed into the expected Pydantic
    model. This is distinct from LLMError (which covers API-level failures)
    and is always non-retryable without prompt modification — the same prompt
    will produce the same malformed output.
    """

    def __init__(self, message: str, agent: str | None = None) -> None:
        """Initialise a structured extraction failure.

        Args:
            message: Human-readable description of the extraction failure.
            agent: Name of the agent in which the failure occurred.
        """
        super().__init__(message, agent=agent, retryable=False)


class RetryExhaustedError(PrasineError):
    """All retry attempts for an operation have been exhausted.

    Wraps the final exception that caused the last attempt to fail. The
    original exception is available as ``__cause__`` via standard Python
    exception chaining.

    Attributes:
        attempts: Total number of attempts made before giving up.
        operation: Descriptive name of the operation that was retried.
    """

    def __init__(
        self,
        message: str,
        attempts: int,
        operation: str,
        agent: str | None = None,
    ) -> None:
        """Initialise a retry-exhausted failure.

        Args:
            message: Human-readable description of the failure.
            attempts: Total number of attempts made.
            operation: Descriptive name of the operation that was retried.
            agent: Name of the agent in which the failure occurred.
        """
        super().__init__(message, agent=agent, retryable=False)
        self.attempts = attempts
        self.operation = operation


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

class RetryConfig:
    """Immutable configuration for a retry policy.

    Uses full-jitter exponential backoff (AWS-recommended strategy) to spread
    retried requests across time and avoid thundering-herd effects when multiple
    pipeline runs hit the same upstream simultaneously.

    The delay for attempt ``n`` (1-indexed) is sampled uniformly from::

        [0, min(max_delay_seconds, base_delay_seconds * 2 ** (n - 1))]

    Attributes:
        max_attempts: Maximum total number of attempts including the initial
            one. A value of 1 means no retries.
        base_delay_seconds: Starting delay ceiling for the first retry, in
            seconds. Doubles with each subsequent attempt.
        max_delay_seconds: Upper bound on the delay ceiling regardless of
            attempt number, in seconds.
        retryable_exceptions: Tuple of exception types that should trigger a
            retry. Exceptions not in this tuple propagate immediately.
    """

    # Sensible defaults for LLM and external API calls
    DEFAULT_LLM = None        # set as class var after definition
    DEFAULT_HTTP = None       # set as class var after definition
    DEFAULT_DB = None         # set as class var after definition

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        """Initialise a retry configuration.

        Args:
            max_attempts: Maximum total attempts including the first. Must be
                at least 1.
            base_delay_seconds: Starting delay ceiling for the first retry.
            max_delay_seconds: Hard upper bound on the delay ceiling.
            retryable_exceptions: Exception types that trigger a retry attempt.

        Raises:
            ValueError: If ``max_attempts`` is less than 1.
        """
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1; received {max_attempts}.")
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.retryable_exceptions = retryable_exceptions

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate the full-jitter backoff delay for the given attempt number.

        Args:
            attempt: The 1-indexed attempt number for which to calculate the
                delay. Attempt 1 is the first retry (after the initial failure).

        Returns:
            A delay in seconds, sampled uniformly from
            ``[0, min(max_delay_seconds, base_delay_seconds * 2 ** (attempt - 1))]``.
        """
        ceiling = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (attempt - 1)),
        )
        return random.uniform(0, ceiling)


# Pre-built configurations for the three call categories in the pipeline.

RetryConfig.DEFAULT_LLM = RetryConfig(
    max_attempts=3,
    base_delay_seconds=2.0,
    max_delay_seconds=30.0,
    retryable_exceptions=(
        anthropic.RateLimitError,
        anthropic.InternalServerError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    ),
)
"""Retry policy for Anthropic SDK calls.

Retries on rate-limit (429), server errors (5xx), connection failures, and
timeouts. Authentication errors (401) and bad-request errors (400) propagate
immediately as they will not resolve without intervention.
"""

RetryConfig.DEFAULT_HTTP = RetryConfig(
    max_attempts=3,
    base_delay_seconds=1.0,
    max_delay_seconds=20.0,
    retryable_exceptions=(
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.RemoteProtocolError,
    ),
)
"""Retry policy for external HTTP data source calls (EU ETS, CDP, EUR-Lex).

Retries on network-level failures and timeouts. HTTP 4xx and 5xx responses
are handled by the ingest modules themselves — a 500 from an upstream API
is wrapped in DataSourceError(retryable=True) before reaching this layer.
"""

RetryConfig.DEFAULT_DB = RetryConfig(
    max_attempts=2,
    base_delay_seconds=0.5,
    max_delay_seconds=5.0,
    retryable_exceptions=(
        Exception,  # narrowed at call site to sqlalchemy.exc.OperationalError
    ),
)
"""Retry policy for database operations.

Only one retry with a short delay — database connection failures are usually
transient pool exhaustion or a brief network hiccup. Longer retries here
would hold up the pipeline unnecessarily.
"""


# ---------------------------------------------------------------------------
# Core retry primitive
# ---------------------------------------------------------------------------

def retry_async(
    config: RetryConfig | None = None,
    operation: str = "operation",
) -> Callable[[Callable[..., Coroutine[Any, Any, T]]], Callable[..., Coroutine[Any, Any, T]]]:
    """Async retry decorator with full-jitter exponential backoff.

    Wraps an async function so that transient failures are automatically
    retried according to the supplied :py:class:`RetryConfig`. Non-retryable
    exceptions (those not listed in ``config.retryable_exceptions``, and any
    :py:class:`NonRetryableError`) propagate immediately without retrying.

    Each retry attempt is logged at WARNING level with structured fields. The
    final failure after all attempts are exhausted is raised as a
    :py:class:`RetryExhaustedError` with the original exception chained.

    Args:
        config: Retry policy to apply. Defaults to
            :py:attr:`RetryConfig.DEFAULT_LLM` if not provided.
        operation: Human-readable name of the operation being retried, used
            in log messages and the :py:class:`RetryExhaustedError` message.

    Returns:
        A decorator that wraps the target async function with retry logic.

    Example::

        from core.retry import retry_async, RetryConfig

        @retry_async(config=RetryConfig.DEFAULT_HTTP, operation="eu_ets_fetch")
        async def fetch_emissions(installation_id: str) -> dict[str, Any]:
            ...
    """
    effective_config = config or RetryConfig.DEFAULT_LLM

    def decorator(
        func: Callable[..., Coroutine[Any, Any, T]],
    ) -> Callable[..., Coroutine[Any, Any, T]]:
        """Wrap the target coroutine function with retry logic.

        Args:
            func: The async function to wrap.

        Returns:
            A wrapped async function that retries on transient failures.
        """
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(1, effective_config.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)

                except NonRetryableError:
                    raise

                except effective_config.retryable_exceptions as exc:
                    last_exception = exc
                    is_final = attempt == effective_config.max_attempts

                    if is_final:
                        break

                    delay = effective_config.delay_for_attempt(attempt)
                    logger.warning(
                        f"Retrying {operation} after transient failure "
                        f"(attempt {attempt}/{effective_config.max_attempts - 1}, "
                        f"sleeping {delay:.2f}s)",
                        extra={
                            "operation": operation,
                            "retry_count": attempt,
                            "error_type": type(exc).__name__,
                        },
                    )
                    await asyncio.sleep(delay)

                except Exception:
                    # Exception type not listed as retryable — propagate immediately
                    raise

            raise RetryExhaustedError(
                message=(
                    f"{operation} failed after {effective_config.max_attempts} attempt(s): "
                    f"{last_exception}"
                ),
                attempts=effective_config.max_attempts,
                operation=operation,
            ) from last_exception

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Agent error boundary
# ---------------------------------------------------------------------------

class agent_error_boundary:
    """Async context manager that provides a structured error boundary for agent steps.

    Wraps a block of agent code so that any unhandled exception is:

    1. Logged at ERROR level with full structured context (agent name, operation,
       trace and claim IDs from the logging ContextVars, error type and message).
    2. Re-raised so the pipeline orchestrator can decide how to handle it.

    This ensures the invariant that no failure in the pipeline is silent,
    without requiring every agent to write its own try/except logging boilerplate.

    Usage::

        async with agent_error_boundary(agent="EXTRACTION", operation="parse_claims"):
            claims = await self._parse_claims(document)

    Attributes:
        agent: The agent name, used in log records.
        operation: The logical operation being attempted, used in log records.
        reraise: If True (default), re-raises the exception after logging.
            Set to False only in contexts where a partial result is acceptable
            and the caller handles the None return explicitly.
    """

    def __init__(
        self,
        agent: str,
        operation: str,
        reraise: bool = True,
    ) -> None:
        """Initialise the error boundary.

        Args:
            agent: The agent name for log records.
            operation: The logical operation name for log records.
            reraise: Whether to re-raise the exception after logging.
        """
        self.agent = agent
        self.operation = operation
        self.reraise = reraise
        self._start_time: float = 0.0

    async def __aenter__(self) -> agent_error_boundary:
        """Record the operation start time.

        Returns:
            This context manager instance.
        """
        self._start_time = time.monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        """Log any exception and optionally suppress it.

        Args:
            exc_type: The exception class, or None if no exception was raised.
            exc_val: The exception instance, or None.
            exc_tb: The traceback object, or None.

        Returns:
            False to re-raise the exception (default), or True to suppress it
            when ``reraise`` is False.
        """
        if exc_val is None:
            return False

        duration_ms = int((time.monotonic() - self._start_time) * 1000)

        logger.error(
            f"Agent error in {self.agent}/{self.operation}: {exc_val}",
            exc_info=True,
            extra={
                "operation": self.operation,
                "agent": self.agent,
                "error_type": type(exc_val).__name__,
                "duration_ms": duration_ms,
                "outcome": "FAILURE",
            },
        )

        return not self.reraise


def classify_http_error(
    exc: httpx.HTTPStatusError,
    source: str,
    agent: str | None = None,
) -> DataSourceError:
    """Convert an httpx HTTP status error into a typed DataSourceError.

    Determines retryability from the HTTP status code: 5xx responses are
    treated as transient and retryable; 4xx responses are structural and
    non-retryable. This function is intended to be called inside ingest
    modules when an upstream API returns an error status.

    Args:
        exc: The httpx status error to classify.
        source: The EvidenceSource identifier of the upstream that failed.
        agent: The agent that triggered the request, if known.

    Returns:
        A :py:class:`DataSourceError` with ``retryable`` set according to
        the HTTP status code.
    """
    status_code = exc.response.status_code
    retryable = status_code >= 500
    return DataSourceError(
        message=f"{source} returned HTTP {status_code}: {exc.response.text[:200]}",
        source=source,
        agent=agent,
        retryable=retryable,
        status_code=status_code,
    )


def classify_anthropic_error(
    exc: anthropic.APIStatusError,
    agent: str | None = None,
    llm_model_id: str | None = None,
) -> LLMError:
    """Convert an Anthropic API status error into a typed LLMError.

    Rate-limit errors (429) and server errors (5xx) are retryable.
    Authentication (401), permission (403), and bad-request (400) errors
    are non-retryable. This function is intended to be called inside agent
    LLM call wrappers when the Anthropic SDK raises a status error.

    Args:
        exc: The Anthropic API status error to classify.
        agent: The agent that made the API call, if known.
        llm_model_id: The model identifier that was called.

    Returns:
        A :py:class:`LLMError` with ``retryable`` set according to the
        HTTP status code.
    """
    status_code = exc.status_code
    retryable = status_code in (429,) or status_code >= 500
    return LLMError(
        message=f"Anthropic API returned HTTP {status_code}: {exc.message}",
        agent=agent,
        retryable=retryable,
        status_code=status_code,
        llm_model_id=llm_model_id,
    )
