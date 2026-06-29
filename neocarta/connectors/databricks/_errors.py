"""Translate :mod:`databricks.sql` (DB-API) exceptions into Neocarta errors.

Each public ``extract_*`` method on the Databricks schema extractor is wrapped
with :func:`wrap_databricks_errors` so callers (including the CLI adapter) only
ever see :class:`~neocarta.errors.NeocartaError` subtypes, never raw
``databricks.sql`` exceptions.

The optional ``databricks-sql-connector`` extra may be absent at import time
(the package must import without it — see the Databricks tags connector, which
applies the same discipline to the Databricks SDK). So this module never imports
``databricks.sql`` at module load: the exception base is imported lazily, and
classification falls back to matching the raised exception's MRO class names plus
small, documented message heuristics. ``databricks.sql`` exposes only the coarse
PEP-249 hierarchy (no dedicated auth / timeout / rate-limit classes), so unlike
the typed BigQuery mapping these signals are detected from the class name and
message — the message is read for classification but, per the contract, never
logged: only the exception *type* is recorded in ``details``.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any, TypeVar, cast

from ...errors import (
    AuthError,
    ConfigError,
    ExtractionError,
    NeocartaError,
    OperationTimeoutError,
    RateLimitError,
)

F = TypeVar("F", bound=Callable[..., Any])

# Lowercased substrings used to classify a coarse ``databricks.sql`` error from
# its message when the PEP-249 class name is not specific enough. databricks.sql
# has no dedicated auth/timeout/rate-limit exception classes, so these are the
# pragmatic signals. They are read for classification only — never logged.
_AUTH_TOKENS = (
    "permission_denied",
    "permission denied",
    "unauthorized",
    "unauthenticated",
    "forbidden",
    "invalid access token",
    "authentication",
    " 401",
    " 403",
)
_NOT_FOUND_TOKENS = (
    "not_found",
    "not found",
    "does not exist",
    "no such",
    "cannot be found",
)
_RATE_LIMIT_TOKENS = (
    "too many requests",
    "rate limit",
    "rate-limit",
    "throttl",
    " 429",
)
_TIMEOUT_TOKENS = (
    "timeout",
    "timed out",
    "deadline",
)

# PEP-249 class names treated as transient (worth retrying as-is).
_RETRYABLE_NAMES = frozenset({"OperationalError", "RequestError", "ServerOperationError"})


@lru_cache(maxsize=1)
def _databricks_error_base() -> type[BaseException] | None:
    """Return ``databricks.sql.exc.Error`` if importable, else ``None``.

    Imported lazily and cached so importing this module never requires the
    optional ``databricks-sql-connector`` extra. ``None`` means the extra is not
    installed — in which case no genuine ``databricks.sql`` exception can have
    been raised, so the wrapper does not attempt to reclassify.
    """
    try:
        from databricks.sql.exc import Error  # noqa: PLC0415
    except Exception:
        return None
    return Error


def _classify(exc: Exception, op: str) -> NeocartaError:
    """Map a ``databricks.sql`` exception to a typed Neocarta error.

    Classification order (most actionable first): auth → config (bad SQL /
    missing catalog or schema) → rate limit → timeout → extraction. Only the
    exception *type* is preserved in ``details`` — never the message or SQL
    (contract §16).

    Parameters
    ----------
    exc : Exception
        The raised ``databricks.sql`` exception.
    op : str
        The wrapped method name, recorded in ``details["op"]``.

    Returns:
    -------
    NeocartaError
        The mapped error, to be raised ``from`` the original.
    """
    names = {klass.__name__ for klass in type(exc).__mro__}
    message = str(exc).lower()
    details: dict[str, Any] = {
        "connector": "databricks",
        "op": op,
        "error_type": type(exc).__name__,
    }

    if any(token in message for token in _AUTH_TOKENS):
        return AuthError(
            f"Databricks rejected the credentials during {op}.",
            suggestion=(
                "Verify the access token (PAT) is valid and that it can read "
                "the catalog's information_schema."
            ),
            details=details,
        )
    if "ProgrammingError" in names or any(token in message for token in _NOT_FOUND_TOKENS):
        return ConfigError(
            f"Databricks rejected the request during {op} "
            "(invalid SQL, or the catalog/schema was not found).",
            details=details,
        )
    if any(token in message for token in _RATE_LIMIT_TOKENS):
        return RateLimitError(
            f"Databricks rate-limited the request during {op}.",
            details=details,
        )
    if any(token in message for token in _TIMEOUT_TOKENS):
        return OperationTimeoutError(
            f"Databricks query timed out during {op}.",
            details=details,
        )
    return ExtractionError(
        f"Databricks query failed during {op}.",
        retryable=bool(names & _RETRYABLE_NAMES),
        details=details,
    )


def wrap_databricks_errors(func: F) -> F:
    """Map ``databricks.sql`` exceptions raised inside ``func`` to Neocarta errors.

    A :class:`~neocarta.errors.NeocartaError` already raised inside ``func`` (e.g.
    a :class:`~neocarta.errors.ConfigError` from identifier validation) is
    re-raised unchanged. Any other exception is reclassified **only** when it is a
    genuine ``databricks.sql`` error (an instance of the lazily-imported
    ``databricks.sql.exc.Error`` base); unrelated exceptions propagate untouched
    so real bugs are never masked as extraction failures.

    Mapping
    -------
    * auth / permission / token signals → :class:`AuthError`
    * ``ProgrammingError`` / not-found signals → :class:`ConfigError`
    * rate-limit signals → :class:`RateLimitError`
    * timeout signals → :class:`OperationTimeoutError`
    * anything else → :class:`ExtractionError` (``retryable=True`` for transient
      operational / request / server-operation errors)
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except NeocartaError:
            raise
        except Exception as exc:
            base = _databricks_error_base()
            if base is not None and not isinstance(exc, base):
                raise
            raise _classify(exc, func.__name__) from exc

    return cast("F", wrapper)
