"""Translate :mod:`databricks.sql` (DB-API) exceptions into Neocarta errors.

Each public ``extract_*`` method on the Databricks schema extractor is wrapped
with :func:`wrap_databricks_errors` so callers (including the CLI adapter) only
ever see :class:`~neocarta.errors.NeocartaError` subtypes, never raw
``databricks.sql`` exceptions.

The optional ``databricks-sql-connector`` extra may be absent at import time
(the package must import without it — see the Databricks tags connector, which
applies the same discipline to the Databricks SDK). So this module never imports
``databricks.sql`` at module load: the exception base is imported lazily.

Classification is by the **exception class only** — the stable PEP-249 /
``databricks.sql`` class hierarchy — never by matching error *message* text,
which is not part of any API contract and can change between releases. A
``ProgrammingError`` (invalid SQL / request) maps to :class:`ConfigError`; every
other genuine ``databricks.sql`` error maps to :class:`ExtractionError`. Only the
exception *type* is recorded in ``details`` — never the message or SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any, TypeVar, cast

from ...errors import ConfigError, ExtractionError, NeocartaError

F = TypeVar("F", bound=Callable[..., Any])

# PEP-249 / databricks.sql class names treated as transient (worth retrying as-is).
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
    """Map a ``databricks.sql`` exception to a typed Neocarta error by its class.

    Uses only the exception's class hierarchy — never the message text. A
    ``ProgrammingError`` (invalid SQL / request) becomes a :class:`ConfigError`;
    every other genuine ``databricks.sql`` error becomes an
    :class:`ExtractionError` (``retryable=True`` for the transient operational /
    request / server-operation classes). Only the exception *type* is preserved
    in ``details`` (contract §16) — never the message or SQL.

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
    details: dict[str, Any] = {
        "connector": "databricks",
        "op": op,
        "error_type": type(exc).__name__,
    }
    if "ProgrammingError" in names:
        return ConfigError(
            f"Databricks rejected the request during {op} (invalid SQL or request).",
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

    Mapping (by exception class, never by message text)
    ---------------------------------------------------
    * ``ProgrammingError`` (invalid SQL / request) → :class:`ConfigError`
    * any other genuine ``databricks.sql`` error → :class:`ExtractionError`
      (``retryable=True`` for transient operational / request / server errors)
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except NeocartaError:
            raise
        except Exception as exc:
            base = _databricks_error_base()
            # Reclassify ONLY genuine databricks.sql errors. If the extra is not installed
            # (base is None), no such exception can have been raised, so anything here is a
            # local bug — re-raise it untouched rather than mask it as a NeocartaError.
            if base is None or not isinstance(exc, base):
                raise
            raise _classify(exc, func.__name__) from exc

    return cast("F", wrapper)
