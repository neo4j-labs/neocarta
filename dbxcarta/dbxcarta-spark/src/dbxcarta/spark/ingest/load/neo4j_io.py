"""Neo4j-side I/O: bootstrap, purge, per-label count queries, graph load.

Everything that holds a neo4j `Driver` or issues Cypher lives here. The
orchestrator deals in typed labels and relationship enums; this module owns
the connector-facing Cypher and graph maintenance details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from dbxcarta.spark.contract import (
    NEOCARTA_GRAPH_LABEL,
    REFERENCES_PROPERTIES,
    NodeLabel,
    RelType,
)
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
    """Create the Neo4j indexes the neocarta MCP server expects.

    Beyond the id-uniqueness constraints and the dbxcarta-internal Column
    `type` / Value `last_run` indexes, this creates the three index families
    the MCP queries by hardcoded name (see ``neocarta/ingest/indexes.py``):

    - per-label vector indexes named ``{label}_vector_index`` (when the
      matching embedding flag is enabled; Value is excluded — neocarta defines
      no Value vector index),
    - full-text indexes ``table_full_text_index`` / ``column_full_text_index``
      over ``name`` + ``description``,
    - range indexes ``{label}_name_index`` on ``name`` for Database, Schema,
      Table, and Column so the catalog tools' exact-name lookups seek.
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

        # Per-label vector indexes named to match neocarta's
        # `{label}_vector_index` so the MCP server's hardcoded names resolve.
        # Value is excluded: neocarta defines no Value vector index and the MCP
        # never vector-searches Value nodes (they are reached via HAS_VALUE
        # traversal on the `value` property).
        for enabled, label in embedding_label_flags:
            if enabled and label is not NodeLabel.VALUE:
                session.run(
                    f"CREATE VECTOR INDEX {label.value.lower()}_vector_index IF NOT EXISTS "
                    f"FOR (n:{label.value}) ON n.embedding "
                    f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dim},"
                    f" `vector.similarity_function`: 'cosine'}}}}"
                )

        # Full-text indexes over name + description, named to match neocarta's
        # `{label}_full_text_index` so the MCP full-text/hybrid tools register
        # and resolve. Independent of embeddings: Table and Column always carry
        # both properties.
        for label in (NodeLabel.TABLE, NodeLabel.COLUMN):
            session.run(
                f"CREATE FULLTEXT INDEX {label.value.lower()}_full_text_index "
                f"IF NOT EXISTS FOR (n:{label.value}) "
                "ON EACH [n.name, n.description]"
            )

        # Range indexes on `name` named to match neocarta's `{label}_name_index`
        # so the MCP catalog tools' exact-name lookups (MATCH (n:Label {name:
        # $value})) seek instead of scanning the label.
        for label in (
            NodeLabel.DATABASE,
            NodeLabel.SCHEMA,
            NodeLabel.TABLE,
            NodeLabel.COLUMN,
        ):
            session.run(
                f"CREATE INDEX {label.value.lower()}_name_index IF NOT EXISTS "
                f"FOR (n:{label.value}) ON (n.name)"
            )

    logger.info("[dbxcarta] neo4j constraints and indexes bootstrapped")


def upsert_neocarta_graph_node(driver: Driver, version: str) -> None:
    """Upsert the singleton ``__neocarta_graph__`` metadata node.

    Mirrors ``neocarta/ingest/metadata.py:upsert_neocarta_graph_node``: on
    create it stamps ``initial_version`` + ``create_date``; on every run it
    refreshes ``latest_version`` + ``last_updated``. The neocarta MCP server
    reads this node to compare the writer's neocarta version against its own;
    when the node is absent it only logs a warning, so this exists to make a
    cleanly-aligned graph report a version match.

    Parameters
    ----------
    driver : Driver
        The Neo4j driver to issue the upsert through.
    version : str
        The neocarta version to record (see
        ``SparkIngestSettings.dbxcarta_neocarta_graph_version``).
    """
    with driver.session() as session:
        session.run(
            f"MERGE (n:`{NEOCARTA_GRAPH_LABEL}`) "
            "ON CREATE SET n.initial_version = $version, "
            "n.latest_version = $version, "
            "n.create_date = datetime(), n.last_updated = datetime() "
            "ON MATCH SET n.latest_version = $version, "
            "n.last_updated = datetime()",
            version=version,
        )
    logger.info(
        "[dbxcarta] upserted __neocarta_graph__ metadata node (version %s)",
        version,
    )


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
    source_col: str = "source_id",
    target_col: str = "target_id",
    properties: tuple[str, ...] = (),
) -> None:
    write_relationship(
        df,
        neo4j,
        rel_type.value,
        source_label.value,
        target_label.value,
        source_col=source_col,
        target_col=target_col,
        properties=properties,
    )


__all__ = [
    "REFERENCES_PROPERTIES",
    "bootstrap_constraints",
    "delete_stale_values",
    "query_counts",
    "upsert_neocarta_graph_node",
    "write_node",
    "write_rel",
]
