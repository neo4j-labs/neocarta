"""Declared-FK discovery: reads information_schema catalog FKs.

Queries `information_schema.referential_constraints` + `key_column_usage`,
emits one FKEdge per resolved column pair tagged with EdgeSource.DECLARED
and confidence=1.0, and records the four declared counters.

Peer of the Spark-native metadata strategy in `fk.inference`; the
orchestrator suppresses metadata against the declared edges emitted here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dbxcarta.spark.contract import EdgeSource, generate_id
from dbxcarta.spark.ingest.fk.common import DeclaredPair, FKEdge

if TYPE_CHECKING:
    from dbxcarta.spark.settings import SparkIngestSettings
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


@dataclass
class DeclaredCounters:
    """Catalog-declared FK bookkeeping.

    - fk_declared: rows in referential_constraints (constraints the catalog
      declares).
    - fk_resolved: distinct (fk_schema, fk_name) successfully joined through
      key_column_usage into column-level pairs.
    - fk_skipped: fk_declared - fk_resolved (cross-schema filtered out or
      missing metadata).
    - fk_edges: column-level edges emitted (one per column pair; composite
      FK of N columns contributes N).
    """

    fk_declared: int = 0
    fk_resolved: int = 0
    fk_skipped: int = 0
    fk_edges: int = 0

    def as_row_counts(self) -> dict[str, int]:
        return {
            "fk_declared": self.fk_declared,
            "fk_resolved": self.fk_resolved,
            "fk_skipped": self.fk_skipped,
            "fk_edges": self.fk_edges,
        }


def discover_declared(
    spark: SparkSession,
    settings: SparkIngestSettings,
    schema_list: list[str],
    prior_pairs: frozenset[DeclaredPair] = frozenset(),
) -> tuple[list[FKEdge], DeclaredCounters]:
    """Read declared FKs and emit one FKEdge per resolved column pair.

    `prior_pairs` is empty by construction when declared runs first, but is
    accepted for signature uniformity with the other two strategies.
    """
    from functools import reduce

    from pyspark.sql.functions import col

    # Declared FKs are read per ingested catalog. Unity Catalog declared FKs
    # cannot span catalogs, so unioning per-catalog reads cannot introduce a
    # cross-catalog edge here; it only widens scope to every ingested catalog.
    catalogs = settings.resolved_catalogs()

    def _union(frames: list[DataFrame]) -> DataFrame:
        return reduce(lambda a, b: a.unionByName(b), frames)

    fk_pairs_df = _union(
        [
            spark.sql(
                f"SELECT rc.constraint_schema AS fk_schema,"
                f"       rc.constraint_name   AS fk_name,"
                f"       src.table_catalog AS src_catalog, src.table_schema AS src_schema,"
                f"       src.table_name    AS src_table,   src.column_name  AS src_column,"
                f"       tgt.table_catalog AS tgt_catalog, tgt.table_schema AS tgt_schema,"
                f"       tgt.table_name    AS tgt_table,   tgt.column_name  AS tgt_column,"
                f"       src.ordinal_position AS ord"
                f" FROM `{catalog}`.information_schema.referential_constraints rc"
                f" JOIN `{catalog}`.information_schema.key_column_usage src"
                f"   ON src.constraint_catalog = rc.constraint_catalog"
                f"  AND src.constraint_schema  = rc.constraint_schema"
                f"  AND src.constraint_name    = rc.constraint_name"
                f" JOIN `{catalog}`.information_schema.key_column_usage tgt"
                f"   ON tgt.constraint_catalog = rc.unique_constraint_catalog"
                f"  AND tgt.constraint_schema  = rc.unique_constraint_schema"
                f"  AND tgt.constraint_name    = rc.unique_constraint_name"
                f"  AND tgt.ordinal_position   = src.position_in_unique_constraint"
            )
            for catalog in catalogs
        ]
    )
    declared_df = _union(
        [
            spark.sql(
                f"SELECT constraint_schema, constraint_name"
                f" FROM `{catalog}`.information_schema.referential_constraints"
            )
            for catalog in catalogs
        ]
    )
    if schema_list:
        fk_pairs_df = fk_pairs_df.filter(
            col("fk_schema").isin(schema_list) & col("tgt_schema").isin(schema_list)
        )
        declared_df = declared_df.filter(col("constraint_schema").isin(schema_list))
    fk_pairs_df = fk_pairs_df.cache()
    declared_df = declared_df.cache()

    fk_declared = declared_df.count()
    fk_edges_total = fk_pairs_df.count()
    fk_resolved = fk_pairs_df.select("fk_schema", "fk_name").distinct().count()
    fk_skipped = fk_declared - fk_resolved
    _log_unresolved_fks(fk_skipped, fk_pairs_df, declared_df)

    edges: list[FKEdge] = []
    for r in fk_pairs_df.collect():
        source_id = generate_id(
            r["src_catalog"],
            r["src_schema"],
            r["src_table"],
            r["src_column"],
        )
        target_id = generate_id(
            r["tgt_catalog"],
            r["tgt_schema"],
            r["tgt_table"],
            r["tgt_column"],
        )
        if DeclaredPair(source_id=source_id, target_id=target_id) in prior_pairs:
            continue
        edges.append(
            FKEdge(
                source_id=source_id,
                target_id=target_id,
                confidence=1.0,
                source=EdgeSource.DECLARED,
                criteria=None,
            )
        )

    fk_pairs_df.unpersist()
    declared_df.unpersist()

    counters = DeclaredCounters(
        fk_declared=fk_declared,
        fk_resolved=fk_resolved,
        fk_skipped=fk_skipped,
        fk_edges=fk_edges_total,
    )
    logger.info(
        "[dbxcarta] declared FKs: fk_declared=%d fk_resolved=%d fk_skipped=%d fk_edges=%d",
        fk_declared,
        fk_resolved,
        fk_skipped,
        fk_edges_total,
    )
    return edges, counters


def _log_unresolved_fks(
    fk_skipped: int,
    fk_pairs_df: DataFrame,
    declared_df: DataFrame,
) -> None:
    if fk_skipped <= 0:
        return
    resolved_names = fk_pairs_df.select("fk_schema", "fk_name").distinct()
    skipped_rows = declared_df.join(
        resolved_names,
        (declared_df.constraint_schema == resolved_names.fk_schema)
        & (declared_df.constraint_name == resolved_names.fk_name),
        "left_anti",
    ).collect()
    for row in skipped_rows:
        logger.warning(
            "[dbxcarta] FK unresolved or out-of-scope (no target column pair in result, skipping): %s.%s",
            row["constraint_schema"],
            row["constraint_name"],
        )
