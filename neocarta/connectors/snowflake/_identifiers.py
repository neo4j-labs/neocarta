"""Snowflake SQL identifier handling (quoting + case resolution).

Identifiers (database / schema / table / column names) cannot be passed as bound
parameters, so they are interpolated into the query text. These helpers make that
safe and match Snowflake's own identifier-resolution rules so that natural,
lower-case invocations (``--database analytics``) resolve to the stored object.
"""

from __future__ import annotations

from ...errors import ConfigError


def normalize_identifier(name: str) -> str:
    """Resolve an identifier to the case Snowflake stores it in.

    Mirrors Snowflake's identifier resolution: an *unquoted* identifier is folded
    to UPPER-case (unquoted DDL names are stored upper-cased, so ``analytics``
    resolves to the stored ``ANALYTICS``); a *double-quoted* identifier is a
    case-sensitive literal — the wrapping quotes are stripped and any doubled
    ``""`` inside is collapsed to a single ``"``, preserving case exactly.

    Parameters
    ----------
    name : str
        The raw identifier as supplied by the caller.

    Returns:
    -------
    str
        The identifier in Snowflake's stored (resolved) form, unquoted.

    Raises:
    ------
    ConfigError
        If ``name`` is empty, or is an unquoted name containing a double-quote,
        or is a malformed quoted identifier (an unbalanced/undoubled ``"``).
    """
    if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        inner = name[1:-1]
        # Every literal " inside a quoted identifier must be doubled ("").
        if '"' in inner.replace('""', ""):
            raise ConfigError(
                f"Malformed quoted Snowflake identifier {name!r}: "
                'embedded double-quotes must be doubled ("").',
                suggestion='Escape literal quotes by doubling them, e.g. \'"a""b"\'.',
            )
        resolved = inner.replace('""', '"')
    elif '"' in name:
        raise ConfigError(
            f"Invalid Snowflake identifier {name!r}: double-quotes are not allowed in an "
            "unquoted name.",
            suggestion="Wrap a case-sensitive name in double-quotes, e.g. '\"MixedCase\"'.",
        )
    else:
        resolved = name.upper()
    if not resolved:
        raise ConfigError(
            "Identifier must be a non-empty string.",
            suggestion="Pass a database/schema name.",
        )
    return resolved


def quote_identifier(identifier: str) -> str:
    """Double-quote a resolved identifier for safe interpolation into SQL.

    Wraps ``identifier`` in double-quotes (Snowflake's identifier quoting) and
    doubles any embedded ``"`` so the name cannot break out of the quoting. The
    input is expected to already be in resolved form (see
    :func:`normalize_identifier`); value literals use bound parameters instead.

    Parameters
    ----------
    identifier : str
        The resolved identifier to quote.

    Returns:
    -------
    str
        The double-quoted, quote-escaped identifier.
    """
    return '"' + identifier.replace('"', '""') + '"'
