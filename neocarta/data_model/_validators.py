"""Reusable Pydantic field validators shared across data model modules.

These functions are wired into models with :func:`pydantic.field_validator`,
e.g. ``_normalize = field_validator("description", mode="before")(coerce_str_or_none)``.
Centralising them keeps the NaN/None and casing normalisation behaviour
consistent across every node and relationship model.
"""

from typing import Any

from pandas import isna


def coerce_str_or_none(value: Any) -> Any:
    """Coerce NaN-like values to ``None`` while passing strings through.

    Parameters
    ----------
    value : Any
        The raw field value.

    Returns:
    -------
    Any
        ``None`` if ``value`` is ``None`` or NaN, otherwise the value unchanged.
    """
    if isinstance(value, str):
        return value
    if value is None or isna(value):
        return None

    return value


def coerce_upper(value: str | None) -> str | None:
    """Uppercase a string value, preserving ``None``.

    Parameters
    ----------
    value : str | None
        The string to uppercase.

    Returns:
    -------
    str | None
        The uppercased string, or ``None`` if ``value`` is ``None``.
    """
    return value.upper() if value is not None else None


_NULLABLE_TRUE_TOKENS = frozenset({"NULLABLE", "YES", "Y", "TRUE", "T", "1"})
_NULLABLE_FALSE_TOKENS = frozenset({"REQUIRED", "NO", "N", "FALSE", "F", "0"})


def coerce_nullable(value: Any) -> Any:
    """Coerce a source nullability value to a ``bool``.

    Normalises the standardised nullability vocabulary schema connectors emit —
    the ``INFORMATION_SCHEMA`` ``"YES"``/``"NO"`` strings and the
    BigQuery/Dataplex ``"NULLABLE"``/``"REQUIRED"`` mode strings (case
    insensitive) — plus native bools. ``None``/NaN map to ``True`` (the
    permissive default matching the normalized ``nullable`` field). Unrecognised
    values are returned unchanged for Pydantic to coerce or reject.

    Source-specific fallbacks (e.g. Dataplex ``"REPEATED"`` → not nullable, or a
    driver's missing-value default) stay in the connector; this normalises only
    the shared token vocabulary.

    Parameters
    ----------
    value : Any
        The raw nullability value.

    Returns:
    -------
    Any
        ``True``/``False`` for a recognised token or bool, ``True`` for
        ``None``/NaN, otherwise ``value`` unchanged.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    if isinstance(value, str):
        token = value.strip().upper()
        if token in _NULLABLE_TRUE_TOKENS:
            return True
        if token in _NULLABLE_FALSE_TOKENS:
            return False
        return value
    if isna(value):
        return True

    return value


def coerce_str(value: Any) -> str:
    """Cast a value to ``str``, mapping NaN-like values to an empty string.

    Parameters
    ----------
    value : Any
        The raw field value.

    Returns:
    -------
    str
        ``""`` if ``value`` is ``None`` or NaN, otherwise ``str(value)``.
    """
    if value is None or isna(value):
        return ""

    return str(value)


def coerce_key_segment_or_none(value: Any) -> Any:
    """Coerce a blank *optional key segment* to ``None``.

    For a trailing natural-key segment whose absence carries meaning — "the path
    ends here", i.e. the row's grain — a blank string is the same statement as a
    missing one, but it does not read that way: ``bool("")`` is falsy while
    ``"" is not None`` is true, so truthiness and identity checks would disagree
    about the grain of the very same row. Folding blank to ``None`` makes the two
    agree by construction, so a downstream consumer cannot silently misclassify.

    Unlike :func:`coerce_str_or_none`, which leaves ``""`` intact because an empty
    *description* is not the same as a missing one, this is for key segments only.
    A value that survives is returned **unchanged**, never stripped, so a legitimate
    name keeps its exact spelling.

    Parameters
    ----------
    value : Any
        The raw key-segment value.

    Returns:
    -------
    Any
        ``None`` if ``value`` is ``None``, NaN, or a blank/whitespace-only string;
        otherwise the value unchanged.
    """
    if isinstance(value, str):
        return value if value.strip() else None
    if value is None or isna(value):
        return None

    return value


def coerce_str_required(value: Any) -> Any:
    """Cast a value to ``str``, leaving NaN-like values for Pydantic to reject.

    The counterpart to :func:`coerce_str` for fields whose *content is their
    identity* — a sampled column value, whose node id content-hashes it. There,
    fabricating ``""`` for a missing cell would mint a real graph node for absent
    data, and the id would disagree with the property (it hashes the raw
    ``"None"``/``"nan"``). That is the same divergence the governance instance
    layer avoids by declining to coerce at all.

    Numeric and boolean cells are still cast, because a dtype-inferred pandas
    frame can hand a required value field an ``int`` and every current sampling
    producer already stringifies upstream. ``None`` and NaN are returned
    **unchanged** so a required ``str`` field raises ``ValidationError`` naming
    the offending value.

    Parameters
    ----------
    value : Any
        The raw field value.

    Returns:
    -------
    Any
        ``value`` unchanged if it is already a ``str`` or is ``None``/NaN,
        otherwise ``str(value)``.
    """
    if isinstance(value, str):
        return value
    if value is None or isna(value):
        return value

    return str(value)
