"""Shared translation of DB-API (PEP-249) driver exceptions into Neocarta errors.

The Snowflake and Databricks schema/log connectors both read over a DB-API 2.0
driver whose optional extra may be absent at import time, and both must surface
only :class:`~neocarta.errors.NeocartaError` subtypes to callers — classified by
the **exception class only** (the stable PEP-249 class hierarchy), never by
message text (which is not an API contract and can change between releases).

This module factors out that shared discipline so each connector's ``_errors``
module is a thin binding: a lazily-imported driver error base, a retryable-class
set, and a connector display name. The mapping rules live on :func:`classify_dbapi_error`.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ...errors import ConfigError, ExtractionError, NeocartaError

if TYPE_CHECKING:
    from collections.abc import Collection

F = TypeVar("F", bound=Callable[..., Any])


def classify_dbapi_error(
    exc: Exception,
    op: str,
    *,
    connector: str,
    display: str,
    retryable_names: Collection[str],
) -> NeocartaError:
    """Map a DB-API driver exception to a typed Neocarta error by its class.

    Uses only the exception's class hierarchy — never the message text. A
    ``ProgrammingError`` (invalid SQL / request) becomes a :class:`ConfigError`;
    every other error becomes an :class:`ExtractionError` (``retryable=True`` when
    any class in ``retryable_names`` is in its MRO). Only the exception *type* is
    preserved in ``details`` (contract §16) — never the message or SQL.

    Parameters
    ----------
    exc : Exception
        The raised driver exception.
    op : str
        The wrapped method name, recorded in ``details["op"]``.
    connector : str
        Connector slug recorded in ``details["connector"]`` (e.g. ``"snowflake"``).
    display : str
        Human-readable connector name used in the error message (e.g. ``"Snowflake"``).
    retryable_names : Collection[str]
        Driver exception class names treated as transient (retryable).

    Returns:
    -------
    NeocartaError
        The mapped error, to be raised ``from`` the original.
    """
    names = {klass.__name__ for klass in type(exc).__mro__}
    details: dict[str, Any] = {
        "connector": connector,
        "op": op,
        "error_type": type(exc).__name__,
    }
    if "ProgrammingError" in names:
        return ConfigError(
            f"{display} rejected the request during {op} (invalid SQL or request).",
            details=details,
        )
    return ExtractionError(
        f"{display} query failed during {op}.",
        retryable=bool(names & set(retryable_names)),
        details=details,
    )


def make_dbapi_error_wrapper(
    get_error_base: Callable[[], type[BaseException] | None],
    classify: Callable[[Exception, str], NeocartaError],
) -> Callable[[F], F]:
    """Build a decorator that maps a driver's exceptions to Neocarta errors.

    A :class:`~neocarta.errors.NeocartaError` already raised inside the wrapped
    function (e.g. a :class:`~neocarta.errors.ConfigError` from identifier
    validation) is re-raised unchanged. Any other exception is reclassified **only**
    when it is a genuine driver error (an instance of the base returned by
    ``get_error_base()``); unrelated exceptions propagate untouched so real bugs are
    never masked as extraction failures.

    ``get_error_base`` is resolved on each failure (not captured once), so a
    connector can lazily import its driver error base — and tests can monkeypatch it.

    Parameters
    ----------
    get_error_base : callable
        Returns the driver's base exception class, or ``None`` when the optional
        extra is not installed (in which case nothing is reclassified).
    classify : callable
        Maps ``(exc, op)`` to a :class:`NeocartaError` (see :func:`classify_dbapi_error`).

    Returns:
    -------
    callable
        A decorator applying the mapping to the exceptions raised inside a function.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except NeocartaError:
                raise
            except Exception as exc:
                base = get_error_base()
                # base is None => extra not installed, so nothing to reclassify.
                if base is None or not isinstance(exc, base):
                    raise
                raise classify(exc, func.__name__) from exc

        return cast("F", wrapper)

    return decorator
