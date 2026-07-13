"""Translate :mod:`snowflake.connector` (DB-API) exceptions into Neocarta errors.

Each public ``extract_*`` method on the Snowflake extractors is wrapped with
:func:`wrap_snowflake_errors` so callers (including the CLI adapter) only ever see
:class:`~neocarta.errors.NeocartaError` subtypes, never raw ``snowflake.connector``
exceptions. The shared classification discipline (by exception **class** only,
never message text) lives in :mod:`neocarta.connectors.utils.dbapi_errors`; this
module only supplies the Snowflake-specific bindings.

The optional ``snowflake`` extra may be absent at import time (the package must
import without it), so ``snowflake.connector`` is never imported at module load —
the exception base is imported lazily.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from ..utils.dbapi_errors import classify_dbapi_error, make_dbapi_error_wrapper

if TYPE_CHECKING:
    from ...errors import NeocartaError

# snowflake.connector class names treated as transient (retryable): the PEP-249 operational/
# internal classes plus Snowflake's 5xx and 429 HTTP-status classes. Client errors (400/403) are
# deliberately excluded — not retryable.
_RETRYABLE_NAMES = frozenset(
    {
        "OperationalError",
        "InternalError",
        "ServiceUnavailableError",
        "InternalServerError",
        "BadGatewayError",
        "GatewayTimeoutError",
        "TooManyRequests",
    }
)


@lru_cache(maxsize=1)
def _snowflake_error_base() -> type[BaseException] | None:
    """Return ``snowflake.connector.errors.Error`` if importable, else ``None``.

    Imported lazily and cached so importing this module never requires the optional
    ``snowflake`` extra. ``None`` means the extra is not installed — in which case no
    genuine ``snowflake.connector`` exception can have been raised, so the wrapper
    does not attempt to reclassify.
    """
    try:
        from snowflake.connector.errors import Error  # noqa: PLC0415
    except Exception:
        return None
    return Error


def _classify(exc: Exception, op: str) -> NeocartaError:
    """Map a ``snowflake.connector`` exception to a typed Neocarta error by its class.

    A ``ProgrammingError`` (invalid SQL / request) becomes a :class:`ConfigError`;
    every other genuine ``snowflake.connector`` error becomes an
    :class:`ExtractionError` (``retryable=True`` for the transient operational /
    internal / service-unavailable classes). See
    :func:`neocarta.connectors.utils.dbapi_errors.classify_dbapi_error`.
    """
    return classify_dbapi_error(
        exc, op, connector="snowflake", display="Snowflake", retryable_names=_RETRYABLE_NAMES
    )


# Wrapped in a lambda (not passed as _snowflake_error_base) so the module global is resolved on
# each call — respecting the lazy import and test monkeypatching; hence PLW0108 does not apply.
wrap_snowflake_errors = make_dbapi_error_wrapper(
    lambda: _snowflake_error_base(),  # noqa: PLW0108
    _classify,
)
