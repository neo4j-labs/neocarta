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


def coerce_yes_no_to_bool(value: Any, default: bool = True) -> bool:
    """Coerce a yes/no-style value to ``bool``.

    Real booleans pass through unchanged. ``None`` and NaN-like values yield
    ``default``. Strings are matched case-insensitively after trimming, as are
    the string forms of other scalars (e.g. ``1``/``0``). Unrecognised strings
    also yield ``default``.

    Parameters
    ----------
    value : Any
        The raw field value.
    default : bool
        The value returned for ``None``/NaN and unrecognised strings.

    Returns:
    -------
    bool
        ``False`` for ``NO``/``FALSE``/``0``; ``True`` for
        ``YES``/``TRUE``/``NULLABLE``/``1``; ``default`` otherwise.
    """
    if isinstance(value, bool):
        return value
    if value is None or isna(value):
        return default

    # Normalise integral floats ("1.0" -> "1", "0.0" -> "0") so numeric flags
    # (e.g. a pandas column promoted to float64 by a NaN) match the token sets.
    text = str(value).strip().upper().removesuffix(".0")
    if text in {"NO", "FALSE", "0"}:
        return False
    if text in {"YES", "TRUE", "NULLABLE", "1"}:
        return True

    return default
