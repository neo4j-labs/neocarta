"""Neo4j-side I/O: bootstrap, purge, per-label count queries, graph load.

Everything that holds a neo4j `Driver` or issues Cypher lives here. The
orchestrator deals in typed labels and relationship enums; this module owns
the connector-facing Cypher and graph maintenance details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from dbxcarta.spark.contract import REFERENCES_PROPERTIES, NodeLabel, RelType
from dbxcarta.spark.ingest.load.writer import (
    write_nodes,
    write_relationship,
)

if TYPE_CHECKING:
    from dbxcarta.spark.ingest.load.writer import Neo4jConfig
    from dbxcarta.spark.settings import SparkIngestSettings
    from neo4j import Driver
    from pyspark.sql import DataFrame

logger = logging.getLogger(__name__)


def _single_count(result: Any) -> int:
    record = result.single()
    if record is None:
        raise RuntimeError("Neo4j count query returned no rows")
    return int(record["cnt"])


def bootstrap_constraints(driver: Driver, settings: SparkIngestSettings) -> None:
    """Create id-uniqueness constraints, Column `type` index, and per-label
    vector indexes when the matching embedding flag is enabled.
    """
    from neo4j.exceptions import ClientError

    embedding_label_flags = [
        (settings.dbxcarta_include_embeddings_tables, NodeLabel.TABLE),
        (settings.dbxcarta_include_embeddings_columns, NodeLabel.COLUMN),
        (settings.dbxcarta_include_embeddings_values, NodeLabel.VALUE),
        (settings.dbxcarta_include_embeddings_schemas, NodeLabel.SCHEMA),
        (settings.dbxcarta_include_embeddings_databases, NodeLabel.DATABASE),
    ]
    dim = settings.dbxcarta_embedding_dimension

    with driver.session() as session:
        for label in NodeLabel:
            try:
                session.run(
                    f"CREATE CONSTRAINT {label.value.lower()}_id IF NOT EXISTS "
                    f"FOR (n:{label.value}) REQUIRE n.id IS UNIQUE"
                )
            except ClientError as exc:
                if "ConstraintAlreadyExists" not in (exc.code or ""):
                    raise
                logger.info(
                    "[dbxcarta] constraint for %s already satisfied, skipping",
                    label.value,
                )

        session.run(
            f"CREATE INDEX {NodeLabel.COLUMN.value.lower()}_type IF NOT EXISTS "
            f"FOR (n:{NodeLabel.COLUMN.value}) ON (n.type)"
        )

        # RANGE index over the contract-1.3 Value run-stamp. The scoped
        # stale-Value delete keys on `last_run < datetime($run_start)`; this
        # index turns that predicate into a bounded range scan instead of a
        # full :Value label sweep at the dense-catalog target.
        session.run(
            f"CREATE INDEX {NodeLabel.VALUE.value.lower()}_last_run "
            f"IF NOT EXISTS FOR (n:{NodeLabel.VALUE.value}) ON (n.last_run)"
        )

        for enabled, label in embedding_label_flags:
            if enabled:
                session.run(
                    f"CREATE VECTOR INDEX {label.value.lower()}_embedding IF NOT EXISTS "
                    f"FOR (n:{label.value}) ON n.embedding "
                    f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dim},"
                    f" `vector.similarity_function`: 'cosine'}}}}"
                )

    logger.info("[dbxcarta] neo4j constraints and indexes bootstrapped")


def delete_stale_values(
    driver: Driver,
    run_start_iso: str,
    catalogs: list[str],
    schemas: list[str],
) -> None:
    """Delete Value nodes left over from a prior run, scoped to this run.

    A single server-side Cypher delete: any :Value within the run's
    catalogs (and schemas, when schema-scoped) whose `last_run` predates
    this run's start was not refreshed by the per-chunk Value writes and is
    therefore stale. Replaces the old driver-collected `IN $col_ids` purge,
    which paged catalog-scale column ids back to the driver
    (best-practices §5). Keyed on the contract-1.3 `last_run`/`catalog`/
    `schema` Value properties; the `:Value(last_run)` RANGE index makes the
    predicate a bounded index scan rather than a label sweep.
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
        "[dbxcarta] deleted stale Values older than run start %s",
        run_start_iso,
    )


def query_counts(driver: Driver) -> dict[str, int]:
    """Post-load Cypher count probes. Keyed by enum .value for JSON serializability."""
    counts: dict[str, int] = {}
    with driver.session() as session:
        for label in NodeLabel:
            result = session.run(f"MATCH (n:{label.value}) RETURN count(n) AS cnt")
            counts[label.value] = _single_count(result)
        for rel_type in RelType:
            result = session.run(f"MATCH ()-[r:{rel_type.value}]->() RETURN count(r) AS cnt")
            counts[rel_type.value] = _single_count(result)
    return counts


def write_node(df: DataFrame, neo4j: Neo4jConfig, label: NodeLabel) -> None:
    """Thin enum-typed wrapper — all pipeline node writes go through here."""
    write_nodes(df, neo4j, label.value)


def write_rel(
    df: DataFrame,
    neo4j: Neo4jConfig,
    rel_type: RelType,
    source_label: NodeLabel,
    target_label: NodeLabel,
    *,
    properties: tuple[str, ...] = (),
) -> None:
    write_relationship(
        df,
        neo4j,
        rel_type.value,
        source_label.value,
        target_label.value,
        properties=properties,
    )


__all__ = [
    "REFERENCES_PROPERTIES",
    "bootstrap_constraints",
    "delete_stale_values",
    "query_counts",
    "write_node",
    "write_rel",
]
