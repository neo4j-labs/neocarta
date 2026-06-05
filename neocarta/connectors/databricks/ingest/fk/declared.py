"""Declared-FK discovery: reads information_schema catalog FKs.

Queries `information_schema.referential_constraints` + `key_column_usage`,
emits one FKEdge per resolved column pair tagged with EdgeSource.DECLARED
and confidence=1.0, and records the four declared counters.

This is the only FK discovery the connector performs. Heuristic (inferred)
foreign keys are produced separately, in-process over the loaded graph, by
`neocarta.enrichment.foreign_keys`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from neocarta.connectors.databricks.contract import EdgeSource
from neocarta.connectors.databricks.ingest.fk.common import FKEdge
from neocarta.connectors.utils.generate_id import compose_id

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from neocarta.connectors.databricks.settings import SparkIngestSettings

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
) -> tuple[list[FKEdge], DeclaredCounters]:
    """Read declared FKs and emit one FKEdge per resolved column pair."""
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
        source_column_id = compose_id(
            r["src_catalog"],
            r["src_schema"],
            r["src_table"],
            r["src_column"],
        )
        target_column_id = compose_id(
            r["tgt_catalog"],
            r["tgt_schema"],
            r["tgt_table"],
            r["tgt_column"],
        )
        edges.append(
            FKEdge(
                source_column_id=source_column_id,
                target_column_id=target_column_id,
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
        "[databricks] declared FKs: fk_declared=%d fk_resolved=%d fk_skipped=%d fk_edges=%d",
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
            "[databricks] FK unresolved or out-of-scope (no target column pair in result, skipping): %s.%s",
            row["constraint_schema"],
            row["constraint_name"],
        )
