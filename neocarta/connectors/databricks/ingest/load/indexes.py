"""Neo4j constraint and index creation for the Databricks connector.

The single home for the connector's schema-object DDL: id-uniqueness
constraints, the connector's range lookup indexes, and the per-label vector
indexes. Kept separate from `neo4j_io` (which owns the data writes) so the DDL
bootstrap is one cohesive unit.

The actual Cypher reuses neocarta's shared :mod:`neocarta.ingest.indexes`
helpers so index names match what the MCP server queries by.

Only inline mode creates `{label}_vector_index` cosine indexes here, at
``settings.embedding_dimension`` and only for labels whose embedding flag is on,
because only inline writes embeddings during the Spark job. External mode creates
no vector indexes during ingest; the separate external embedding step creates
each index at the dimension it actually embeds, so the index dimension always
matches the stored vectors.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from neocarta.connectors.databricks.contract import (
    MANAGED_NODE_LABELS,
    NodeLabel,
)

if TYPE_CHECKING:
    from neo4j import Driver

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

# Labels that get a `{label}_full_text_index`, matching the other connectors
# (the shared RDBMS loader full-text-indexes Schema, Table, and Column). Database
# is excluded — no connector full-text-indexes it, and the MCP server only
# queries the table and column indexes. The shared helper names each single-label
# index `{label}_full_text_index`, so these line up with what the MCP server's
# full-text Cypher queries by.
_FULL_TEXT_INDEX_LABELS = (
    NodeLabel.SCHEMA,
    NodeLabel.TABLE,
    NodeLabel.COLUMN,
)

# Properties covered by each full-text index. `qualified_name` (the readable
# `catalog.schema.table` path) is indexed alongside `name` and `description` so
# keyword search can disambiguate by catalog/schema: Lucene tokenizes the dotted
# path into separate words, so the bare name still matches exactly while the
# catalog and schema words become searchable too. This is a lexical-only choice
# — embeddings stay on the bare `name | type | comment` text (see
# EMBEDDING_TEXT_EXPR) to keep every connector embedding identical text and avoid
# diluting vectors with non-semantic catalog/schema words.
_FULL_TEXT_PROPERTIES = ("name", "qualified_name", "description")


def bootstrap_constraints(driver: Driver) -> None:
    """Create id constraints and the connector's lookup indexes.

    Id-uniqueness constraints reuse neocarta's shared
    :func:`neocarta.ingest.utils.write_neo4j_constraints`, which picks NODE KEY
    (enterprise) or UNIQUE (community) constraints per the server edition. Two
    connector-specific range indexes back hot lookups: Column ``type`` and the
    Value ``last_run`` run-stamp (the scoped stale-Value delete keys on it). The
    Schema/Table/Column full-text indexes that back keyword search are created by
    :func:`create_full_text_indexes`. Vector indexes are created separately by
    :func:`create_vector_indexes`.
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
    create_full_text_indexes(driver)
    logger.info("[databricks] neo4j constraints and indexes bootstrapped")


def create_full_text_indexes(driver: Driver) -> None:
    """Create the Schema/Table/Column `{label}_full_text_index` indexes.

    One full-text index per label in :data:`_FULL_TEXT_INDEX_LABELS`, each over
    :data:`_FULL_TEXT_PROPERTIES`, reusing neocarta's shared
    :func:`neocarta.ingest.indexes.create_full_text_index` so the index names
    match what the MCP server's full-text Cypher queries by. These back the
    hybrid retrieval's keyword half; without them, name/description keyword
    search returns nothing on a Databricks graph. The shared helper uses
    ``IF NOT EXISTS``, so this is idempotent across reruns and independent of the
    embedding mode (both inline and external benefit from keyword search).
    """
    from neocarta.ingest.indexes import create_full_text_index

    for label in _FULL_TEXT_INDEX_LABELS:
        create_full_text_index(
            driver,
            node_labels=[label.value],
            property_names=list(_FULL_TEXT_PROPERTIES),
        )
        logger.info(
            "[databricks] created %s_full_text_index (%s)",
            label.value.lower(),
            ", ".join(_FULL_TEXT_PROPERTIES),
        )


def _vector_index_labels(settings: SparkIngestSettings) -> tuple[NodeLabel, ...]:
    """Labels to create a vector index for during the Spark job (inline mode).

    Restricted to labels whose `include_embeddings_*` flag is on, since only
    those carry an `embedding` property after an inline run. External mode
    creates no vector indexes during ingest; the separate external embedding step
    creates each one at the dimension it embeds.
    """
    flags = {
        NodeLabel.DATABASE: settings.include_embeddings_databases,
        NodeLabel.SCHEMA: settings.include_embeddings_schemas,
        NodeLabel.TABLE: settings.include_embeddings_tables,
        NodeLabel.COLUMN: settings.include_embeddings_columns,
    }
    return tuple(label for label in _VECTOR_INDEX_LABELS if flags[label])


def create_vector_indexes(driver: Driver, settings: SparkIngestSettings) -> None:
    """Create per-label `{label}_vector_index` cosine indexes for inline mode.

    One cosine vector index per inline-enabled label, at ``embedding_dimension``,
    reusing neocarta's shared :func:`neocarta.ingest.indexes.create_vector_index`
    so the index name matches what the MCP server queries by. Only called in
    inline mode (the only mode that writes embeddings during the job); external
    mode creates no vector indexes here. The separate external embedding step
    creates each index at the dimension it actually embeds. Value is never
    embedded or indexed (see ``_VECTOR_INDEX_LABELS``).

    The index is created with `IF NOT EXISTS` and is fixed at one dimension, so
    the inline endpoint must embed at ``embedding_dimension``.
    """
    from neocarta.ingest.indexes import create_vector_index

    for label in _vector_index_labels(settings):
        create_vector_index(driver, label.value, settings.embedding_dimension)
        logger.info(
            "[databricks] created %s_vector_index (dim=%d, cosine)",
            label.value.lower(),
            settings.embedding_dimension,
        )


__all__ = [
    "bootstrap_constraints",
    "create_full_text_indexes",
    "create_vector_indexes",
]
