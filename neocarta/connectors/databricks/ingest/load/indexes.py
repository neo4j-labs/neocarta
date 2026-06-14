"""Neo4j constraint and index creation for the Databricks connector.

The single home for the connector's schema-object DDL: id-uniqueness
constraints, the connector's range lookup indexes, and the per-label vector
indexes. Kept separate from `neo4j_io` (which owns the data writes) so the DDL
bootstrap is one cohesive unit.

The actual Cypher reuses neocarta's shared :mod:`neocarta.ingest.indexes`
helpers so index names match what the MCP server queries by.

Both embedding modes create the same `{label}_vector_index` cosine indexes at
``settings.embedding_dimension``. Inline creates an index only for labels whose
embedding flag is on; external creates all four eligible labels, matching what
the `neocarta databricks embed` CLI embeds. The dimension is therefore the
single source of truth across modes: the operator must align
``embedding_dimension`` with whatever the external enrichment model produces, or
cross-mode vector search is inconsistent.
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


def bootstrap_constraints(driver: Driver) -> None:
    """Create id constraints and the connector's lookup indexes.

    Id-uniqueness constraints reuse neocarta's shared
    :func:`neocarta.ingest.utils.write_neo4j_constraints`, which picks NODE KEY
    (enterprise) or UNIQUE (community) constraints per the server edition. Two
    connector-specific range indexes back hot lookups: Column ``type`` and the
    Value ``last_run`` run-stamp (the scoped stale-Value delete keys on it).
    Vector indexes are created separately by :func:`create_vector_indexes`.
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


def _vector_index_labels(settings: SparkIngestSettings, *, inline: bool) -> tuple[NodeLabel, ...]:
    """Labels to create a vector index for in the given mode.

    Inline restricts to labels whose `include_embeddings_*` flag is on (only
    those carry an `embedding` property after the run). External embeds all four
    eligible labels via the enrichment CLI, so it indexes all of them.
    """
    if not inline:
        return _VECTOR_INDEX_LABELS
    flags = {
        NodeLabel.DATABASE: settings.include_embeddings_databases,
        NodeLabel.SCHEMA: settings.include_embeddings_schemas,
        NodeLabel.TABLE: settings.include_embeddings_tables,
        NodeLabel.COLUMN: settings.include_embeddings_columns,
    }
    return tuple(label for label in _VECTOR_INDEX_LABELS if flags[label])


def create_vector_indexes(driver: Driver, settings: SparkIngestSettings, *, inline: bool) -> None:
    """Create per-label `{label}_vector_index` cosine indexes.

    One cosine vector index per selected label, at ``embedding_dimension``,
    reusing neocarta's shared :func:`neocarta.ingest.indexes.create_vector_index`
    so the index name matches what the MCP server queries by. Inline creates
    indexes only for labels whose embedding flag is on; external creates all
    four eligible labels (Value is never embedded or indexed; see
    ``_VECTOR_INDEX_LABELS``).

    Both modes index at ``embedding_dimension``. The index is created with
    `IF NOT EXISTS` and is fixed at one dimension, so the external enrichment
    model must embed at this same dimension or vector search is inconsistent.
    """
    from neocarta.ingest.indexes import create_vector_index

    for label in _vector_index_labels(settings, inline=inline):
        create_vector_index(driver, label.value, settings.embedding_dimension)
        logger.info(
            "[databricks] created %s_vector_index (dim=%d, cosine)",
            label.value.lower(),
            settings.embedding_dimension,
        )


__all__ = [
    "bootstrap_constraints",
    "create_vector_indexes",
]
