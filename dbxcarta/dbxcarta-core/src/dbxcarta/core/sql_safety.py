"""Read-only / single-catalog safety guard for generated SQL.

Both example question generators emit reference SQL from an LLM and must reject
anything that is not a plain ``SELECT`` confined to the example's own catalog,
so a hallucinated ``DROP`` or a cross-catalog read never reaches the warehouse.
The check is identical in every example and example-agnostic (the catalog is a
parameter), so it lives here once rather than being copied per example.
"""

from __future__ import annotations

import re

# Statement keywords that make a query something other than a read. Matched as
# whole words so a column named e.g. ``created_at`` does not trip ``create``.
_FORBIDDEN_SQL_RE = re.compile(
    r"\b("
    r"alter|call|copy|create|delete|drop|execute|grant|insert|merge|msck|"
    r"optimize|refresh|repair|replace|revoke|truncate|update|use|vacuum"
    r")\b",
    re.IGNORECASE,
)
# The table reference following FROM/JOIN, used to confirm every referenced
# table is qualified into the allowed catalog.
_TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([`A-Za-z0-9_.-]+)", re.IGNORECASE)


def sql_targets_only_catalog(sql: str, catalog: str) -> bool:
    """Return True only for a single-statement SELECT confined to ``catalog``.

    Rejects non-SELECT statements, multiple statements, any forbidden
    (write/DDL) keyword, references to ``information_schema`` or the ``system``
    catalog, and any FROM/JOIN table that is not qualified into ``catalog``.
    """
    normalized = sql.strip()
    lowered = normalized.lower()
    if not lowered.startswith("select"):
        return False
    if ";" in normalized.rstrip(";"):
        return False
    if _FORBIDDEN_SQL_RE.search(normalized):
        return False
    if "information_schema" in lowered or re.search(r"\bsystem\s*\.", lowered):
        return False
    target = f"`{catalog.lower()}`"
    for match in _TABLE_REF_RE.finditer(sql):
        ref = match.group(1).strip()
        if ref.startswith("`"):
            if not ref.lower().startswith(target):
                return False
        elif "." in ref:
            if not ref.lower().startswith(f"{catalog.lower()}."):
                return False
        else:
            return False
    return True
