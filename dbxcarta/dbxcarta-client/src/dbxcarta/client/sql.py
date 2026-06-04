"""SQL response parsing for the dbxcarta client."""

from __future__ import annotations

import re

_FENCE_RE = re.compile(r"^```(?:sql)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)
_SQL_START_RE = re.compile(
    r"^\s*(SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|EXPLAIN)\b", re.IGNORECASE
)


def parse_sql(text: str | None) -> tuple[str | None, bool]:
    """Strip markdown fences and check for a SQL keyword.

    Returns (cleaned_sql, is_valid).
    """
    if not text:
        return None, False
    cleaned = text.strip()
    m = _FENCE_RE.match(cleaned)
    if m:
        cleaned = m.group(1).strip()
    if not _SQL_START_RE.match(cleaned):
        return cleaned or None, False
    return cleaned, True
