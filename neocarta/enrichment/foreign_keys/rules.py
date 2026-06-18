"""Pure-Python foreign-key inference rule layer (Spark-free).

These heuristics are ported verbatim from the dbxcarta Spark connector's rule
layer (``fk/common.py`` + ``fk/metadata.py``).

The rules: a column is a *target* candidate when it looks like a key (declared
primary key, or a name heuristic — ``id`` / sole ``{table}_id``). A source
column matches a target by exact name or by stem suffix (``customer_id`` ->
``customer`` -> table ``customers``). A match must be type-compatible and is
scored by ``_SCORE_TABLE`` keyed on (match kind, PK evidence, comment overlap).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_TYPE_EQUIV: dict[str, str] = {
    "BIGINT": "INTEGER",
    "INT": "INTEGER",
    "INTEGER": "INTEGER",
    "LONG": "INTEGER",
    "SMALLINT": "INTEGER",
    "TINYINT": "INTEGER",
}

_DECIMAL_RE = re.compile(r"^(?:DECIMAL|NUMERIC)\((\d+)(?:,(\d+))?\)$")
_STRING_PARAM_RE = re.compile(r"^(?:STRING|VARCHAR|CHAR)(?:\(\d+\))?$")


class NameMatchKind(Enum):
    """How a source column name matched a target: exact or stem-suffix."""

    EXACT = "exact"
    SUFFIX = "suffix"


class PKEvidence(Enum):
    """Why a target column is treated as a key: declared PK or heuristic."""

    DECLARED_PK = "declared_pk"
    UNIQUE_OR_HEUR = "unique_or_heur"


# Score keyed by (name match kind, PK evidence, comment-token overlap present).
_SCORE_TABLE: dict[tuple[NameMatchKind, PKEvidence, bool], float] = {
    (NameMatchKind.EXACT, PKEvidence.DECLARED_PK, True): 0.95,
    (NameMatchKind.EXACT, PKEvidence.DECLARED_PK, False): 0.90,
    (NameMatchKind.EXACT, PKEvidence.UNIQUE_OR_HEUR, True): 0.88,
    (NameMatchKind.EXACT, PKEvidence.UNIQUE_OR_HEUR, False): 0.83,
    (NameMatchKind.SUFFIX, PKEvidence.DECLARED_PK, True): 0.88,
    (NameMatchKind.SUFFIX, PKEvidence.DECLARED_PK, False): 0.83,
    (NameMatchKind.SUFFIX, PKEvidence.UNIQUE_OR_HEUR, True): 0.82,
    (NameMatchKind.SUFFIX, PKEvidence.UNIQUE_OR_HEUR, False): 0.78,
}

# Suffixes stripped to a stem for the source side of the suffix branch.
_STEM_SUFFIXES = ("_id", "_fk", "_ref")

# Dropped from comment-token sets before the overlap check. The len>=4 token
# filter makes the short entries redundant; kept for spec parity.
_STOPWORDS = frozenset({"the", "of", "and", "a", "an", "to", "for", "id", "column", "table"})

_TOKEN_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")
_MIN_TOKEN_LEN = 4


@dataclass(frozen=True, slots=True)
class ColumnMeta:
    """A column read from the graph, normalized for matching."""

    col_id: str
    catalog: str
    schema: str
    table: str
    column: str
    data_type: str
    description: str | None
    is_primary_key: bool

    @property
    def table_key(self) -> tuple[str, str, str]:
        """Return the ``(catalog, schema, table)`` triple identifying the table."""
        return (self.catalog, self.schema, self.table)


def canonicalize(data_type: str) -> tuple[str, str | None]:
    """Reduce a declared type to (family, detail) for equality comparison.

    detail holds scale for DECIMAL; None otherwise. Precision is discarded so
    DECIMAL(10,2) matches DECIMAL(18,2).
    """
    t = data_type.strip().upper()
    if _STRING_PARAM_RE.match(t):
        return ("STRING", None)
    m = _DECIMAL_RE.match(t)
    if m:
        scale = m.group(2) if m.group(2) is not None else "0"
        return ("DECIMAL", scale)
    return (_TYPE_EQUIV.get(t, t), None)


def types_compatible(a: str, b: str) -> bool:
    """True when two declared types canonicalize equal."""
    return canonicalize(a) == canonicalize(b)


def comment_tokens(comment: str | None) -> frozenset[str]:
    """Tokenize a column comment to the set used for the overlap check."""
    if not comment:
        return frozenset()
    return frozenset(
        tok
        for tok in _TOKEN_SPLIT_RE.split(comment.lower())
        if len(tok) >= _MIN_TOKEN_LEN and tok not in _STOPWORDS
    )


def build_id_cols_index(columns: list[ColumnMeta]) -> dict[tuple[str, str, str], list[str]]:
    """Map each table to its `_id`-suffixed column names (for the heuristic)."""
    index: dict[tuple[str, str, str], list[str]] = {}
    for c in columns:
        if c.column.lower().endswith("_id"):
            index.setdefault(c.table_key, []).append(c.column)
    return index


def pk_evidence(
    target: ColumnMeta,
    id_cols_by_table: dict[tuple[str, str, str], list[str]],
) -> PKEvidence | None:
    """Classify a target column's PK-likeness from graph facts.

    Declared primary keys (the `is_primary_key` boolean the connector sets from
    Unity Catalog declared constraints) are `DECLARED_PK`. Name heuristics
    (`id`, or sole `{table}_id`) are `UNIQUE_OR_HEUR`. Unlike the Spark
    connector, UNIQUE-constraint evidence is unavailable post-ingest (the graph
    carries no UNIQUE metadata), so it is not consulted here.
    """
    if target.is_primary_key:
        return PKEvidence.DECLARED_PK
    col_lower = target.column.lower()
    if col_lower == "id":
        return PKEvidence.UNIQUE_OR_HEUR
    if col_lower == f"{target.table.lower()}_id":
        id_cols = id_cols_by_table.get(target.table_key, [])
        if len(id_cols) == 1 and id_cols[0].lower() == col_lower:
            return PKEvidence.UNIQUE_OR_HEUR
    return None


def source_match_keys(column: str) -> list[tuple[NameMatchKind, str]]:
    """Match keys for a source column: exact name plus any stem suffix."""
    col_l = column.lower()
    keys: list[tuple[NameMatchKind, str]] = [(NameMatchKind.EXACT, col_l)]
    for suf in _STEM_SUFFIXES:
        if col_l.endswith(suf) and len(col_l) > len(suf):
            keys.append((NameMatchKind.SUFFIX, col_l[: -len(suf)]))
    return keys


def target_match_keys(column: str, table: str) -> list[tuple[NameMatchKind, str]]:
    """Match keys for a target column.

    Exact name for any column; for a column literally named ``id``, the table
    name and its singular/de-pluralized forms (``customers`` -> ``customer``).
    """
    col_l = column.lower()
    keys: list[tuple[NameMatchKind, str]] = [(NameMatchKind.EXACT, col_l)]
    if col_l == "id":
        tbl_l = table.lower()
        keys.append((NameMatchKind.SUFFIX, tbl_l))
        if tbl_l.endswith("es"):
            keys.append((NameMatchKind.SUFFIX, tbl_l[:-2]))
        if tbl_l.endswith("s"):
            keys.append((NameMatchKind.SUFFIX, tbl_l[:-1]))
    return keys


def score(kind: NameMatchKind, evidence: PKEvidence, comment_present: bool) -> float | None:
    """Look up the base score for a candidate; None when not in the table."""
    return _SCORE_TABLE.get((kind, evidence, comment_present))
