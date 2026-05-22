"""Translate :mod:`google.api_core` exceptions into Neocarta errors.

Each public ``extract_*`` method on the BigQuery extractors is wrapped with
:func:`wrap_bigquery_errors` so callers (including the CLI adapter) only
ever see :class:`~neocarta.errors.NeocartaError` subtypes, never raw vendor
exceptions.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from google.api_core import exceptions as gax

from ...errors import (
    AuthError,
    ConfigError,
    ExtractionError,
    OperationTimeoutError,
    RateLimitError,
)

F = TypeVar("F", bound=Callable[..., Any])


def wrap_bigquery_errors(func: F) -> F:
    """Map ``google.api_core.exceptions.*`` raised inside ``func`` to Neocarta errors.

    The function name is recorded in ``details["op"]`` so error envelopes
    identify which extraction step failed.

    Mapping
    -------
    * ``Unauthenticated`` / ``PermissionDenied`` → :class:`AuthError`
    * ``BadRequest`` / ``NotFound`` → :class:`ConfigError`
    * ``TooManyRequests`` / ``ResourceExhausted`` → :class:`RateLimitError`
    * ``DeadlineExceeded`` → :class:`OperationTimeoutError`
    * any other ``GoogleAPICallError`` → :class:`ExtractionError` (with
      ``retryable=True`` for transient server-side failures)
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        op = func.__name__
        try:
            return func(*args, **kwargs)
        except gax.GoogleAPICallError as e:
            details = _vendor_details(op, e)
            if isinstance(e, (gax.Unauthenticated, gax.PermissionDenied)):
                raise AuthError(
                    f"BigQuery rejected the credentials during {op}: {e.message}",
                    suggestion=(
                        "Re-run `gcloud auth application-default login` or "
                        "verify the service account has BigQuery access."
                    ),
                    details=details,
                ) from e
            if isinstance(e, (gax.BadRequest, gax.NotFound)):
                raise ConfigError(
                    f"BigQuery rejected the request during {op}: {e.message}",
                    details=details,
                ) from e
            if isinstance(e, (gax.TooManyRequests, gax.ResourceExhausted)):
                raise RateLimitError(
                    f"BigQuery rate-limited the request during {op}.",
                    details=details,
                ) from e
            if isinstance(e, gax.DeadlineExceeded):
                raise OperationTimeoutError(
                    f"BigQuery deadline exceeded during {op}.",
                    details=details,
                ) from e
            # Server-side 5xx errors are transient and worth retrying.
            retryable = isinstance(e, (gax.ServiceUnavailable, gax.InternalServerError))
            raise ExtractionError(
                f"BigQuery call failed during {op}: {e.message}",
                retryable=retryable,
                details=details,
            ) from e

    return cast("F", wrapper)


def _vendor_details(op: str, exc: gax.GoogleAPICallError) -> dict[str, Any]:
    """Preserve enough of the vendor exception to debug from the JSON envelope.

    The original exception is still reachable via ``__cause__`` for callers
    using ``--debug``; this puts the bits worth seeing without a traceback
    into the structured envelope so agents and bug reports keep them.
    """
    details: dict[str, Any] = {
        "connector": "bigquery",
        "op": op,
        "vendor_exception": type(exc).__name__,
        "vendor_message": exc.message,
    }
    if getattr(exc, "code", None) is not None:
        details["vendor_http_status"] = exc.code
    return details
