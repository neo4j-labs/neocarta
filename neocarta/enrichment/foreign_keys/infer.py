"""Spark-agnostic inferred foreign-key discovery over a loaded Neo4j graph.

Reads Column facts the Databricks connector (or any RDBMS connector) wrote,
proposes heuristic ``REFERENCES`` edges using the rule layer in
:mod:`neocarta.enrichment.foreign_keys.rules`, and writes the surviving edges
back tagged ``source="inferred_metadata"`` with a confidence score. Declared
edges always win: an inferred edge that duplicates an existing ``REFERENCES``
is suppressed, and inferred edges never set the Column ``is_foreign_key``
boolean (that remains declared-only).

Candidate generation is scoped per (catalog, schema): foreign keys do not span
schemas here, which also bounds the in-process pairwise work. Very wide schemas
are the case the Spark connector exists for; the scan size is logged so a large
schema is visible rather than silently truncated.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from neocarta.enrichment.foreign_keys.rules import (
    ColumnMeta,
    NameMatchKind,
    build_id_cols_index,
    comment_tokens,
    pk_evidence,
    score,
    source_match_keys,
    target_match_keys,
    types_compatible,
)

if TYPE_CHECKING:
    from neo4j import Driver

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.8
INFERRED_SOURCE = "inferred_metadata"


@dataclass
class InferredFKResult:
    """Counts from one inference pass."""

    columns_scanned: int
    candidate_pairs: int
    edges_written: int


def infer_foreign_keys(
    neo4j_driver: Driver,
    database_name: str = "neo4j",
    *,
    threshold: float = DEFAULT_THRESHOLD,
    catalogs: list[str] | None = None,
    schemas: list[str] | None = None,
) -> InferredFKResult:
    """Infer and write heuristic foreign-key ``REFERENCES`` edges.

    Parameters
    ----------
    neo4j_driver : neo4j.Driver
        Open driver for the target database.
    database_name : str, optional
        Database to read and write, by default ``"neo4j"``.
    threshold : float, optional
        Minimum (attenuated) confidence for an inferred edge, by default 0.8.
    catalogs, schemas : list[str], optional
        Restrict inference to these catalogs / schemas. ``None`` means all.

    Returns:
    -------
    InferredFKResult
        Columns scanned, candidate pairs considered, and edges written.
    """
    columns = _read_columns(neo4j_driver, database_name, catalogs, schemas)
    declared = _read_existing_reference_pairs(neo4j_driver, database_name, catalogs, schemas)
    logger.info("[neocarta] FK inference: scanning %d columns", len(columns))

    edges = _infer_edges(columns, declared, threshold)
    candidate_pairs = _count_candidate_pairs(columns)
    written = _write_edges(neo4j_driver, database_name, edges)
    logger.info(
        "[neocarta] FK inference: %d candidate pairs -> %d inferred edges written",
        candidate_pairs,
        written,
    )
    return InferredFKResult(
        columns_scanned=len(columns),
        candidate_pairs=candidate_pairs,
        edges_written=written,
    )


def _group_by_schema(
    columns: list[ColumnMeta],
) -> dict[tuple[str, str], list[ColumnMeta]]:
    groups: dict[tuple[str, str], list[ColumnMeta]] = defaultdict(list)
    for c in columns:
        groups[(c.catalog, c.schema)].append(c)
    return groups


def _count_candidate_pairs(columns: list[ColumnMeta]) -> int:
    """Number of (source, target) name matches before gating — diagnostic."""
    total = 0
    for group in _group_by_schema(columns).values():
        target_index = _build_target_index(group)
        for src in group:
            total += len(_matches_for_source(src, target_index))
    return total


def _build_target_index(
    group: list[ColumnMeta],
) -> dict[tuple[NameMatchKind, str], list[ColumnMeta]]:
    index: dict[tuple[NameMatchKind, str], list[ColumnMeta]] = defaultdict(list)
    for col in group:
        for key in target_match_keys(col.column, col.table):
            index[key].append(col)
    return index


def _matches_for_source(
    src: ColumnMeta,
    target_index: dict[tuple[NameMatchKind, str], list[ColumnMeta]],
) -> dict[str, tuple[ColumnMeta, NameMatchKind]]:
    """Best (kind) match per target column id for one source column.

    EXACT outranks SUFFIX when a pair matches on several keys. Self-matches and
    the generic ``id`` <-> ``id`` pair are excluded.
    """
    best: dict[str, tuple[ColumnMeta, NameMatchKind]] = {}
    src_is_id = src.column.lower() == "id"
    for kind, key in source_match_keys(src.column):
        for tgt in target_index.get((kind, key), ()):
            if tgt.col_id == src.col_id:
                continue
            if src_is_id and tgt.column.lower() == "id":
                continue
            existing = best.get(tgt.col_id)
            if existing is None or (
                existing[1] is NameMatchKind.SUFFIX and kind is NameMatchKind.EXACT
            ):
                best[tgt.col_id] = (tgt, kind)
    return best


def _infer_edges(
    columns: list[ColumnMeta],
    declared: set[tuple[str, str]],
    threshold: float,
) -> list[tuple[str, str, float]]:
    """Return (source_column_id, target_column_id, confidence) inferred edges."""
    id_cols_by_table = build_id_cols_index(columns)
    edges: list[tuple[str, str, float]] = []

    for group in _group_by_schema(columns).values():
        target_index = _build_target_index(group)
        # Pass 1: base score per surviving candidate, grouped by source.
        per_source: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for src in group:
            for tgt, kind in _matches_for_source(src, target_index).values():
                evidence = pk_evidence(tgt, id_cols_by_table)
                if evidence is None:
                    continue
                if not types_compatible(src.data_type, tgt.data_type):
                    continue
                comment_present = bool(
                    comment_tokens(src.description) & comment_tokens(tgt.description)
                )
                base = score(kind, evidence, comment_present)
                if base is None or base < threshold:
                    continue
                per_source[src.col_id].append((tgt.col_id, base))

        # Pass 2: attenuate by fan-out, re-threshold, suppress declared.
        for source_id, candidates in per_source.items():
            fanout = len(candidates)
            divisor = max(1.0, math.sqrt(fanout - 1))
            for target_id, base in candidates:
                attenuated = base / divisor
                if attenuated < threshold:
                    continue
                if (source_id, target_id) in declared:
                    continue
                edges.append((source_id, target_id, round(attenuated, 4)))
    return edges


def _read_columns(
    driver: Driver,
    database_name: str,
    catalogs: list[str] | None,
    schemas: list[str] | None,
) -> list[ColumnMeta]:
    query = (
        "MATCH (c:Column) "
        "WHERE ($catalogs IS NULL OR c.catalog IN $catalogs) "
        "AND ($schemas IS NULL OR c.schema IN $schemas) "
        "AND c.catalog IS NOT NULL AND c.schema IS NOT NULL "
        "AND c.table IS NOT NULL AND c.type IS NOT NULL "
        "RETURN c.id AS id, c.name AS name, c.catalog AS catalog, c.schema AS schema, "
        "c.table AS table, c.type AS type, c.description AS description, "
        "coalesce(c.is_primary_key, false) AS is_primary_key"
    )
    with driver.session(database=database_name) as session:
        records = session.run(query, catalogs=catalogs, schemas=schemas).data()
    return [
        ColumnMeta(
            col_id=r["id"],
            catalog=r["catalog"],
            schema=r["schema"],
            table=r["table"],
            column=r["name"],
            data_type=r["type"],
            description=r["description"],
            is_primary_key=bool(r["is_primary_key"]),
        )
        for r in records
    ]


def _read_existing_reference_pairs(
    driver: Driver,
    database_name: str,
    catalogs: list[str] | None,
    schemas: list[str] | None,
) -> set[tuple[str, str]]:
    # Scope to the source column so the read matches the inference scope: an
    # inferred edge can only be suppressed by a declared pair whose source is an
    # in-scope column, so a declared pair anchored outside the scope is never
    # consulted and need not be materialized on the driver.
    query = (
        "MATCH (a:Column)-[:REFERENCES]->(b:Column) "
        "WHERE ($catalogs IS NULL OR a.catalog IN $catalogs) "
        "AND ($schemas IS NULL OR a.schema IN $schemas) "
        "RETURN a.id AS source_id, b.id AS target_id"
    )
    with driver.session(database=database_name) as session:
        records = session.run(query, catalogs=catalogs, schemas=schemas).data()
    return {(r["source_id"], r["target_id"]) for r in records}


def _write_edges(
    driver: Driver,
    database_name: str,
    edges: list[tuple[str, str, float]],
) -> int:
    if not edges:
        return 0
    rows = [{"source_id": s, "target_id": t, "confidence": c} for s, t, c in edges]
    query = (
        "UNWIND $rows AS row "
        "MATCH (a:Column {id: row.source_id}) "
        "MATCH (b:Column {id: row.target_id}) "
        "MERGE (a)-[r:REFERENCES]->(b) "
        "SET r.confidence = row.confidence, r.source = $source"
    )
    with driver.session(database=database_name) as session:
        session.run(query, rows=rows, source=INFERRED_SOURCE)
    return len(edges)
