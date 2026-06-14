"""Neo4j I/O for the Databricks connector.

The single home for the connector's Neo4j output: the connection config, the
constraint/index bootstrap (reusing neocarta's shared `ingest` helpers), node
and relationship writes via the Neo4j Spark Connector, the scoped stale-Value
cleanup, and the post-load count probes.

Writes go through the Neo4j Spark Connector (distributed, from executors), not
the in-process driver — that is why this connector does not use
`neocarta.ingest.rdbms.Neo4jRDBMSLoader`. The constraint/index bootstrap, stale
cleanup, and counts are small driver-side Cypher operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from neocarta.connectors.databricks.contract import (
    MANAGED_NODE_LABELS,
    MANAGED_REL_TYPES,
    REFERENCES_PROPERTIES,
    NodeLabel,
    RelType,
)

if TYPE_CHECKING:
    from neo4j import Driver
    from pyspark.sql import DataFrame

    from neocarta.connectors.databricks.settings import SparkIngestSettings

logger = logging.getLogger(__name__)

# Labels eligible for a `{label}_vector_index`. Value is excluded: neocarta
# defines no Value vector index (Values are reached via HAS_VALUE traversal,
# never vector search), matching the shared `create_vector_index` helper.
_VECTOR_INDEX_LABELS = (
    NodeLabel.DATABASE,
    NodeLabel.SCHEMA,
    NodeLabel.TABLE,
    NodeLabel.COLUMN,
)

_FORMAT = "org.neo4j.spark.DataSource"


@dataclass(frozen=True)
class Neo4jConfig:
    """Connection details for the Neo4j Spark Connector and driver sessions."""

    uri: str
    username: str
    password: str
    batch_size: int = 20000

    def _base_opts(self) -> dict[str, str]:
        return {
            "url": self.uri,
            "authentication.type": "basic",
            "authentication.basic.username": self.username,
            "authentication.basic.password": self.password,
            "batch.size": str(self.batch_size),
        }


def _single_count(result: Any) -> int:
    record = result.single()
    if record is None:
        raise RuntimeError("Neo4j count query returned no rows")
    return int(record["cnt"])


def bootstrap_constraints(driver: Driver) -> None:
    """Create id constraints and the connector's lookup indexes.

    Id-uniqueness constraints reuse neocarta's shared
    :func:`neocarta.ingest.utils.write_neo4j_constraints`, which picks NODE KEY
    (enterprise) or UNIQUE (community) constraints per the server edition. Two
    connector-specific range indexes back hot lookups: Column ``type`` and the
    Value ``last_run`` run-stamp (the scoped stale-Value delete keys on it).
    Vector indexes are not created here — embeddings are produced after ingest
    by neocarta's enrichment layer, which owns its own indexes.
    """
    from neocarta.ingest.indexes import create_range_index
    from neocarta.ingest.rdbms.constraints import (
        KEY_CONSTRAINTS_LOOKUP,
        UNIQUE_CONSTRAINTS_LOOKUP,
    )
    from neocarta.ingest.utils import write_neo4j_constraints

    write_neo4j_constraints(
        driver,
        list(MANAGED_NODE_LABELS),
        KEY_CONSTRAINTS_LOOKUP,
        UNIQUE_CONSTRAINTS_LOOKUP,
    )
    create_range_index(driver, NodeLabel.COLUMN.value, "type")
    create_range_index(driver, NodeLabel.VALUE.value, "last_run")
    logger.info("[databricks] neo4j constraints and indexes bootstrapped")


def create_vector_indexes(driver: Driver, settings: SparkIngestSettings) -> None:
    """Create per-label `{label}_vector_index` cosine indexes for inline mode.

    Called only when inline embeddings are enabled. One cosine vector index per
    label whose embedding flag is on, at `embedding_dimension`, reusing
    neocarta's shared :func:`neocarta.ingest.indexes.create_vector_index` so the
    index name matches what the MCP server queries by. Value is never indexed
    (see ``_VECTOR_INDEX_LABELS``); its flag embeds Value nodes but creates no
    index.

    Each mode owns its index config: inline creates these at its configured
    dimension; external mode leaves vector indexes to the enrichment layer.
    Mixing modes on one graph requires rebuilding the index, since it is fixed
    at one dimension.
    """
    from neocarta.ingest.indexes import create_vector_index

    flags = {
        NodeLabel.DATABASE: settings.include_embeddings_databases,
        NodeLabel.SCHEMA: settings.include_embeddings_schemas,
        NodeLabel.TABLE: settings.include_embeddings_tables,
        NodeLabel.COLUMN: settings.include_embeddings_columns,
    }
    for label in _VECTOR_INDEX_LABELS:
        if flags[label]:
            create_vector_index(driver, label.value, settings.embedding_dimension)
            logger.info(
                "[databricks] created %s_vector_index (dim=%d, cosine)",
                label.value.lower(),
                settings.embedding_dimension,
            )


def delete_stale_values(
    driver: Driver,
    run_start_iso: str,
    catalogs: list[str],
    schemas: list[str],
) -> None:
    """Delete Value nodes left over from a prior run, scoped to this run.

    A single server-side Cypher delete: any :Value within the run's catalogs
    (and schemas, when schema-scoped) whose `last_run` predates this run's start
    was not refreshed by the Value writes and is therefore stale. Keyed on the
    `last_run`/`catalog`/`schema` Value properties; the `:Value(last_run)` range
    index makes the predicate a bounded index scan rather than a label sweep.
    """
    with driver.session() as session:
        session.run(
            f"MATCH (v:{NodeLabel.VALUE.value}) "
            "WHERE v.catalog IN $catalogs "
            "AND (size($schemas) = 0 OR v.schema IN $schemas) "
            "AND v.last_run < datetime($run_start) "
            "DETACH DELETE v",
            catalogs=catalogs,
            schemas=schemas,
            run_start=run_start_iso,
        )
    logger.info(
        "[databricks] deleted stale Values older than run start %s",
        run_start_iso,
    )


def query_counts(driver: Driver) -> dict[str, int]:
    """Post-load Cypher count probes. Keyed by enum .value for JSON serializability."""
    counts: dict[str, int] = {}
    with driver.session() as session:
        for label in MANAGED_NODE_LABELS:
            result = session.run(f"MATCH (n:{label.value}) RETURN count(n) AS cnt")
            counts[label.value] = _single_count(result)
        for rel_type in MANAGED_REL_TYPES:
            result = session.run(f"MATCH ()-[r:{rel_type.value}]->() RETURN count(r) AS cnt")
            counts[rel_type.value] = _single_count(result)
    return counts


def write_node(df: DataFrame, neo4j: Neo4jConfig, label: NodeLabel) -> None:
    """MERGE nodes on id via the Neo4j Spark Connector, updating properties on match."""
    (
        df.write.format(_FORMAT)
        .mode("Overwrite")
        .options(**neo4j._base_opts())
        .option("labels", f":{label.value}")
        .option("node.keys", "id")
        .save()
    )


def write_rel(
    df: DataFrame,
    neo4j: Neo4jConfig,
    rel_type: RelType,
    source_label: NodeLabel,
    target_label: NodeLabel,
    *,
    source_col: str = "source_id",
    target_col: str = "target_id",
    properties: tuple[str, ...] = (),
) -> None:
    """MERGE a relationship between existing nodes matched by id.

    When `properties` is non-empty, those DataFrame columns are written as edge
    properties (the connector's `keys` strategy ignores extra columns otherwise),
    letting REFERENCES persist provenance/confidence/criteria while structural
    edges write only source/target ids.
    """
    writer = (
        df.write.format(_FORMAT)
        .mode("Overwrite")
        .options(**neo4j._base_opts())
        .option("relationship", rel_type.value)
        .option("relationship.save.strategy", "keys")
        .option("relationship.source.labels", f":{source_label.value}")
        .option("relationship.source.save.mode", "Match")
        .option("relationship.source.node.keys", f"{source_col}:id")
        .option("relationship.target.labels", f":{target_label.value}")
        .option("relationship.target.save.mode", "Match")
        .option("relationship.target.node.keys", f"{target_col}:id")
    )
    if properties:
        writer = writer.option("relationship.properties", ",".join(properties))
    writer.save()


__all__ = [
    "REFERENCES_PROPERTIES",
    "Neo4jConfig",
    "bootstrap_constraints",
    "create_vector_indexes",
    "delete_stale_values",
    "query_counts",
    "write_node",
    "write_rel",
]
