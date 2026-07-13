"""Translate :mod:`databricks.sql` (DB-API) exceptions into Neocarta errors.

Each public ``extract_*`` method on the Databricks schema extractor is wrapped with
:func:`wrap_databricks_errors` so callers (including the CLI adapter) only ever see
:class:`~neocarta.errors.NeocartaError` subtypes, never raw ``databricks.sql``
exceptions. The shared classification discipline (by exception **class** only, never
message text) lives in :mod:`neocarta.connectors.utils.dbapi_errors`; this module
only supplies the Databricks-specific bindings.

The optional ``databricks-sql-connector`` extra may be absent at import time (the
package must import without it), so ``databricks.sql`` is never imported at module
load — the exception base is imported lazily.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from ..utils.dbapi_errors import classify_dbapi_error, make_dbapi_error_wrapper

if TYPE_CHECKING:
    from ...errors import NeocartaError

# PEP-249 / databricks.sql class names treated as transient (worth retrying as-is).
_RETRYABLE_NAMES = frozenset({"OperationalError", "RequestError", "ServerOperationError"})


@lru_cache(maxsize=1)
def _databricks_error_base() -> type[BaseException] | None:
    """Return ``databricks.sql.exc.Error`` if importable, else ``None``.

    Imported lazily and cached so importing this module never requires the optional
    ``databricks-sql-connector`` extra. ``None`` means the extra is not installed — in
    which case no genuine ``databricks.sql`` exception can have been raised, so the
    wrapper does not attempt to reclassify.
    """
    try:
        from databricks.sql.exc import Error  # noqa: PLC0415
    except Exception:
        return None
    return Error


def _classify(exc: Exception, op: str) -> NeocartaError:
    """Map a ``databricks.sql`` exception to a typed Neocarta error by its class.

    A ``ProgrammingError`` (invalid SQL / request) becomes a :class:`ConfigError`;
    every other genuine ``databricks.sql`` error becomes an :class:`ExtractionError`
    (``retryable=True`` for the transient operational / request / server-operation
    classes). See
    :func:`neocarta.connectors.utils.dbapi_errors.classify_dbapi_error`.
    """
    return classify_dbapi_error(
        exc, op, connector="databricks", display="Databricks", retryable_names=_RETRYABLE_NAMES
    )


# Resolve _databricks_error_base via the module global on each failure (not captured once) so
# the lazy import — and test monkeypatching of the base — is respected. The lambda is required
# for that late binding, so PLW0108 (unnecessary-lambda) does not apply.
wrap_databricks_errors = make_dbapi_error_wrapper(
    lambda: _databricks_error_base(),  # noqa: PLW0108
    _classify,
)
