"""Translate :mod:`snowflake.connector` (DB-API) exceptions into Neocarta errors.

Each public ``extract_*`` method on the Snowflake extractors is wrapped with
:func:`wrap_snowflake_errors` so callers (including the CLI adapter) only ever
see :class:`~neocarta.errors.NeocartaError` subtypes, never raw
``snowflake.connector`` exceptions.

The optional ``snowflake`` extra (``snowflake-connector-python``) may be absent
at import time (the package must import without it — see the Databricks
connectors, which apply the same discipline). So this module never imports
``snowflake.connector`` at module load: the exception base is imported lazily.

Classification is by the **exception class only** — the stable PEP-249 /
``snowflake.connector`` class hierarchy — never by matching error *message* text,
which is not part of any API contract and can change between releases. A
``ProgrammingError`` (invalid SQL / request) maps to :class:`ConfigError`; every
other genuine ``snowflake.connector`` error maps to :class:`ExtractionError`.
Only the exception *type* is recorded in ``details`` — never the message or SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any, TypeVar, cast

from ...errors import ConfigError, ExtractionError, NeocartaError

F = TypeVar("F", bound=Callable[..., Any])

# PEP-249 / snowflake.connector class names treated as transient (worth retrying as-is).
_RETRYABLE_NAMES = frozenset({"OperationalError", "InternalError", "ServiceUnavailableError"})


@lru_cache(maxsize=1)
def _snowflake_error_base() -> type[BaseException] | None:
    """Return ``snowflake.connector.errors.Error`` if importable, else ``None``.

    Imported lazily and cached so importing this module never requires the
    optional ``snowflake`` extra. ``None`` means the extra is not installed — in
    which case no genuine ``snowflake.connector`` exception can have been raised,
    so the wrapper does not attempt to reclassify.
    """
    try:
        from snowflake.connector.errors import Error  # noqa: PLC0415
    except Exception:
        return None
    return Error


def _classify(exc: Exception, op: str) -> NeocartaError:
    """Map a ``snowflake.connector`` exception to a typed Neocarta error by its class.

    Uses only the exception's class hierarchy — never the message text. A
    ``ProgrammingError`` (invalid SQL / request) becomes a :class:`ConfigError`;
    every other genuine ``snowflake.connector`` error becomes an
    :class:`ExtractionError` (``retryable=True`` for the transient operational /
    internal / service-unavailable classes). Only the exception *type* is
    preserved in ``details`` (contract §16) — never the message or SQL.

    Parameters
    ----------
    exc : Exception
        The raised ``snowflake.connector`` exception.
    op : str
        The wrapped method name, recorded in ``details["op"]``.

    Returns:
    -------
    NeocartaError
        The mapped error, to be raised ``from`` the original.
    """
    names = {klass.__name__ for klass in type(exc).__mro__}
    details: dict[str, Any] = {
        "connector": "snowflake",
        "op": op,
        "error_type": type(exc).__name__,
    }
    if "ProgrammingError" in names:
        return ConfigError(
            f"Snowflake rejected the request during {op} (invalid SQL or request).",
            details=details,
        )
    return ExtractionError(
        f"Snowflake query failed during {op}.",
        retryable=bool(names & _RETRYABLE_NAMES),
        details=details,
    )


def wrap_snowflake_errors(func: F) -> F:
    """Map ``snowflake.connector`` exceptions raised inside ``func`` to Neocarta errors.

    A :class:`~neocarta.errors.NeocartaError` already raised inside ``func`` (e.g.
    a :class:`~neocarta.errors.ConfigError` from identifier validation) is
    re-raised unchanged. Any other exception is reclassified **only** when it is a
    genuine ``snowflake.connector`` error (an instance of the lazily-imported
    ``snowflake.connector.errors.Error`` base); unrelated exceptions propagate
    untouched so real bugs are never masked as extraction failures.

    Mapping (by exception class, never by message text)
    ---------------------------------------------------
    * ``ProgrammingError`` (invalid SQL / request) → :class:`ConfigError`
    * any other genuine ``snowflake.connector`` error → :class:`ExtractionError`
      (``retryable=True`` for transient operational / internal / service errors)
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except NeocartaError:
            raise
        except Exception as exc:
            base = _snowflake_error_base()
            # Reclassify ONLY genuine snowflake.connector errors. If the extra is not installed
            # (base is None), no such exception can have been raised, so anything here is a
            # local bug — re-raise it untouched rather than mask it as a NeocartaError.
            if base is None or not isinstance(exc, base):
                raise
            raise _classify(exc, func.__name__) from exc

    return cast("F", wrapper)
