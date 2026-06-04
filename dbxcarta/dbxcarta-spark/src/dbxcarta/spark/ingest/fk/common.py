"""Shared FK-discovery primitives.

Nominal types and helpers used by the declared and metadata strategies.
Spark Row → dataclass conversion happens exactly once at the pipeline edge
via the *.from_row classmethods. Dataclass → Spark tuple happens exactly
once in schema_graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from dbxcarta.spark.contract import EdgeSource, generate_id

if TYPE_CHECKING:
    from collections.abc import Mapping

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


@dataclass(frozen=True, slots=True)
class ColumnMeta:
    """Driver-side column metadata. Built once at the Spark boundary."""

    catalog: str
    schema: str
    table: str
    column: str
    data_type: str
    comment: str | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> ColumnMeta:
        """Spark-Row → ColumnMeta conversion; the only place that renames
        `table_catalog` → `catalog`, `column_name` → `column`, etc.
        """
        return cls(
            catalog=row["table_catalog"],
            schema=row["table_schema"],
            table=row["table_name"],
            column=row["column_name"],
            data_type=row["data_type"],
            comment=row["comment"],
        )

    @property
    def table_key(self) -> str:
        return generate_id(self.catalog, self.schema, self.table)

    @property
    def col_id(self) -> str:
        return generate_id(self.catalog, self.schema, self.table, self.column)


@dataclass(frozen=True, slots=True)
class ConstraintRow:
    """Raw information_schema.key_column_usage row, post-boundary conversion."""

    table_catalog: str
    table_schema: str
    table_name: str
    column_name: str
    constraint_type: str
    ordinal_position: int
    constraint_name: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> ConstraintRow:
        return cls(
            table_catalog=row["table_catalog"],
            table_schema=row["table_schema"],
            table_name=row["table_name"],
            column_name=row["column_name"],
            constraint_type=row["constraint_type"],
            ordinal_position=row["ordinal_position"],
            constraint_name=row["constraint_name"],
        )

    @property
    def table_key(self) -> str:
        return generate_id(self.table_catalog, self.table_schema, self.table_name)


@dataclass(frozen=True, slots=True)
class DeclaredPair:
    """A declared-FK endpoint pair; frozen so accidental swaps can't mutate
    the suppression set.
    """

    source_id: str
    target_id: str


@dataclass(frozen=True, slots=True)
class FKEdge:
    """Emitted REFERENCES edge. Built in any of the three discovery
    strategies, tuple-converted once in schema_graph.build_references_rel.

    `source` is an EdgeSource enum (not a magic string); the DataFrame builder
    serializes `.value` at the tuple boundary.
    """

    source_id: str
    target_id: str
    confidence: float
    source: EdgeSource
    criteria: str | None


@dataclass(frozen=True, slots=True)
class PKIndex:
    """What the DBA declared: single-column primary keys and leftmost UNIQUE
    columns, keyed by table. Composite PKs are counted but not indexed.

    Deliberately does *not* include heuristic `id` / `{table}_id` fallbacks;
    those are inferred from column names inside pk_kind via
    build_id_cols_index. Keeping this type pure to its declared source.
    """

    pk_cols: dict[str, frozenset[str]]
    unique_leftmost: dict[str, frozenset[str]]
    composite_pk_count: int

    @classmethod
    def from_constraints(cls, rows: list[ConstraintRow]) -> PKIndex:
        pk_by_constraint: dict[tuple[str, str, str], list[str]] = {}
        pk_table_by_constraint: dict[tuple[str, str, str], str] = {}
        unique_leftmost_build: dict[str, set[str]] = {}

        for r in rows:
            constraint_key = (r.table_catalog, r.table_schema, r.constraint_name)
            if r.constraint_type == "PRIMARY KEY":
                pk_by_constraint.setdefault(constraint_key, []).append(r.column_name)
                pk_table_by_constraint[constraint_key] = r.table_key
            elif r.constraint_type == "UNIQUE" and r.ordinal_position == 1:
                unique_leftmost_build.setdefault(r.table_key, set()).add(r.column_name)

        pk_cols_build: dict[str, set[str]] = {}
        composite_count = 0
        for ckey, cols in pk_by_constraint.items():
            table_key = pk_table_by_constraint[ckey]
            if len(cols) == 1:
                pk_cols_build.setdefault(table_key, set()).add(cols[0])
            else:
                composite_count += 1

        return cls(
            pk_cols={k: frozenset(v) for k, v in pk_cols_build.items()},
            unique_leftmost={k: frozenset(v) for k, v in unique_leftmost_build.items()},
            composite_pk_count=composite_count,
        )


# --- Shared primitives ------------------------------------------------------


def canonicalize(data_type: str) -> tuple[str, str | None]:
    """Reduce a declared type to (family, detail) for equality comparison.

    detail holds scale for DECIMAL; None otherwise. Precision is discarded so
    DECIMAL(10,2) ↔ DECIMAL(18,2).
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
    return canonicalize(a) == canonicalize(b)


def build_id_cols_index(columns: list[ColumnMeta]) -> dict[str, list[str]]:
    """Inferred from the column list, not from declared constraint metadata.
    Used by pk_kind's name-heuristic fallback branch.
    """
    index: dict[str, list[str]] = {}
    for c in columns:
        if c.column.lower().endswith("_id"):
            index.setdefault(c.table_key, []).append(c.column)
    return index


class PKEvidence(Enum):
    DECLARED_PK = "declared_pk"
    UNIQUE_OR_HEUR = "unique_or_heur"


def pk_kind(
    tgt: ColumnMeta,
    pk_index: PKIndex,
    id_cols_by_table: dict[str, list[str]],
) -> PKEvidence | None:
    """Classify target's PK-likeness.

    Falls back to name heuristics (column == "id", or == "{table}_id" and sole
    _id-suffixed column) so inference still works on catalogs with no declared
    PKs. The fallback collapses into UNIQUE_OR_HEUR rather than a third
    bucket because metadata scoring only distinguishes declared PKs from
    weaker uniqueness evidence.
    """
    if tgt.column in pk_index.pk_cols.get(tgt.table_key, frozenset()):
        return PKEvidence.DECLARED_PK
    if tgt.column in pk_index.unique_leftmost.get(tgt.table_key, frozenset()):
        return PKEvidence.UNIQUE_OR_HEUR
    col_lower = tgt.column.lower()
    if col_lower == "id":
        return PKEvidence.UNIQUE_OR_HEUR
    if col_lower == f"{tgt.table.lower()}_id":
        id_cols = id_cols_by_table.get(tgt.table_key, [])
        if len(id_cols) == 1 and id_cols[0].lower() == col_lower:
            return PKEvidence.UNIQUE_OR_HEUR
    return None
