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
