"""Graph contract: node-label / relationship-type subsets and node properties.

Node labels and relationship types are the canonical neocarta enums
(`neocarta.enums.NodeLabel` / `RelationshipType`); this connector manages only
the subset listed in `MANAGED_NODE_LABELS` / `MANAGED_REL_TYPES`. Identifier
production lives in `neocarta.connectors.utils.generate_id` (`compose_id` for
the Python side; `ingest.contract_expr` for the byte-identical Spark side) — no
id is built here. `EdgeSource` is connector-specific provenance with no
neocarta-wide equivalent.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from neocarta.data_model.rdbms.expanded import (
    DatabricksColumn,
    DatabricksDatabase,
    DatabricksReferences,
    DatabricksSchema,
    DatabricksTable,
    DatabricksValue,
)
from neocarta.enums import NodeLabel
from neocarta.enums import RelationshipType as RelType

if TYPE_CHECKING:
    from pydantic import BaseModel

# 1.1 adds the additive Table node `layer` property (bronze/silver/gold),
# derived at ingest from a configurable catalog->layer map. Readers treat a
# missing `layer` as null.
# 1.2 makes structural identity first-class: Table nodes gain `catalog`,
# `schema`; Column nodes gain `catalog`, `schema`, `table`. Previously the
# only structural signal was the HAS_* edges plus an opaque hashed `id`, so
# every consumer needing "which catalog/schema/table does this node belong
# to" (batch-by-table-range, FK locality) had to re-join the cached
# information_schema frames. Additive and readers treat the new properties
# as authoritative scalar identity.
# 1.3 stamps every Value node with `last_run` (the run-start timestamp),
# `catalog`, and `schema`. This replaces the driver-collected stale-Value
# purge (which paged catalog-scale column ids back to the driver) with a
# single scoped server-side Cypher delete keyed on `last_run` < run-start
# within the run's catalogs/schemas. Additive; readers treat the new
# properties as authoritative.
# 1.4 made Column key-likeness a first-class boolean `is_key_like` property
# with a per-run `:KeyColumn` label projection. Both existed only to serve
# the semantic-FK same-schema pre-filter and were removed in 1.5.
# 1.5 removes semantic-similarity FK inference and everything that existed
# only to support it: the `EdgeSource.SEMANTIC` provenance value, the
# Column `is_key_like` property, the `:KeyColumn` label, and the
# `keycolumn_embedding` vector index. Declared and metadata FK inference are
# unchanged. Column embeddings and the per-label vector indexes used by
# graph-RAG retrieval are unaffected. Readers of an older graph treat a
# lingering `is_key_like`/`:KeyColumn`/`semantic` edge as inert.
# 1.6 renames node properties to match the neocarta core RDBMS model
# (neocarta/data_model/rdbms/core.py): the human-readable text on Schema,
# Table, and Column nodes is `description` (was `comment`); the Column data
# type is `type` (was `data_type`) and the Column nullability boolean is
# `nullable` (was `is_nullable`). The rename happens only at the node-builder
# `.select()` boundary; the Unity Catalog `information_schema` column names
# (`comment`/`data_type`/`is_nullable`) are unchanged in the extract and FK
# internals. This is a breaking rename; there is no legacy graph to migrate
# (every run is a clean rebuild).
# 1.7 aligns the Database and Column nodes with neocarta core. Database gains
# three additive properties: `service` (always the constant "DATABRICKS" for
# this connector), `platform` (the cloud tag — AWS/AZURE/GCP — sourced from
# the optional NEOCARTA_DATABRICKS_PLATFORM config, null when unset), and `description`
# (null; UC exposes no catalog comment in the extract today); both `platform`
# and `service` are stored upper-cased to match the core convention. Column
# gains two additive booleans, `is_primary_key` and `is_foreign_key`, derived
# at extract time from the catalog's DECLARED constraints
# (information_schema.table_constraints + key_column_usage), matching core's
# declared-only semantics. Inferred REFERENCES edges never set these flags: an
# inferred edge is a relationship, not a declared constraint. Readers of an
# older graph treat the missing properties as null/false.
CONTRACT_VERSION = "1.7"

# The Database node `service` value. Constant for this connector: every
# catalog this connector ingests lives in Databricks Unity Catalog. Upper-cased to
# match the neocarta core convention (Database.service examples=["BIGQUERY"]).
DATABASE_SERVICE = "DATABRICKS"

# Default Databricks model-serving endpoint for inline embeddings. The
# foundation-model GTE endpoint produces 1024-dim vectors (the inline default
# dimension). Overridable via NEOCARTA_DATABRICKS_EMBEDDING_ENDPOINT, e.g. to
# point at an External Models endpoint that proxies OpenAI text-embedding-3-small.
DEFAULT_EMBEDDING_ENDPOINT = "databricks-gte-large-en"


# The node labels and relationship types this connector produces and manages.
# Iterate these (not the full neocarta enums) when creating constraints or
# counting, so the connector never touches labels it does not own.
MANAGED_NODE_LABELS: tuple[NodeLabel, ...] = (
    NodeLabel.DATABASE,
    NodeLabel.SCHEMA,
    NodeLabel.TABLE,
    NodeLabel.COLUMN,
    NodeLabel.VALUE,
)

MANAGED_REL_TYPES: tuple[RelType, ...] = (
    RelType.HAS_SCHEMA,
    RelType.HAS_TABLE,
    RelType.HAS_COLUMN,
    RelType.HAS_VALUE,
    RelType.REFERENCES,
)


class EdgeSource(str, Enum):
    """Provenance tag on REFERENCES edges. DECLARED is the Unity Catalog
    declared-FK source; INFERRED_METADATA is name/PK heuristic inference.

    Connector-specific: neocarta has no repo-wide edge-provenance enum.
    """

    DECLARED = "declared"
    INFERRED_METADATA = "inferred_metadata"


# Map each managed label to the Pydantic model that defines its shape. The
# models (neocarta.data_model.rdbms.expanded) subclass the canonical core
# models and add this connector's additive properties, so they are the single
# source of truth for the graph contract — the per-label property lists below
# are derived from their fields rather than hand-maintained.
_LABEL_MODEL: dict[NodeLabel, type[BaseModel]] = {
    NodeLabel.DATABASE: DatabricksDatabase,
    NodeLabel.SCHEMA: DatabricksSchema,
    NodeLabel.TABLE: DatabricksTable,
    NodeLabel.COLUMN: DatabricksColumn,
    NodeLabel.VALUE: DatabricksValue,
}

# REFERENCES endpoint fields are transient join keys (they match start/end
# nodes by id), never stored as edge properties — excluded from the derived
# REFERENCES property set.
_REFERENCES_ENDPOINTS = frozenset({"source_column_id", "target_column_id"})


def _graph_properties(
    model: type[BaseModel], *, exclude: frozenset[str] = frozenset()
) -> tuple[str, ...]:
    """Graph property names declared by a model.

    Uses each field's alias (the wire/graph name) when set, else the field
    name — so `schema_` (aliased to avoid shadowing BaseModel) surfaces as the
    graph property `schema`. Names in `exclude` are dropped.
    """
    return tuple(
        (field.alias or name)
        for name, field in model.model_fields.items()
        if (field.alias or name) not in exclude
    )


# Per-label declared node properties, derived from the models. A column reaches
# Neo4j iff it is listed here — run.py:_project is the fail-closed write
# boundary. `embedding` is the one member that may be absent: this connector
# ingests facts and does not embed, so enrichment populates `embedding` later;
# the projection selects the intersection with the DataFrame columns.
NODE_PROPERTIES: dict[NodeLabel, tuple[str, ...]] = {
    label: _graph_properties(model) for label, model in _LABEL_MODEL.items()
}

# Stored REFERENCES edge properties (provenance + criteria); endpoints excluded.
REFERENCES_PROPERTIES: tuple[str, ...] = _graph_properties(
    DatabricksReferences, exclude=_REFERENCES_ENDPOINTS
)


# Per-label embedding-text SQL expressions. Evaluated inside the node builder
# (schema_graph.py) while the raw information_schema helper columns are still in
# scope, producing one transient `embedding_text` column per node. The inline
# embed stage hashes and embeds that column; the fail-closed write boundary
# (run.py:_project) strips it, so it is never a graph property. Kept here so the
# builders, the embed stage, and the tests share one definition. Value nodes are
# never embedded (no neocarta path embeds them; they are reached by HAS_VALUE
# traversal, not vector search), so they have no entry here. Catalog leads every
# qualified name so `bronze.sales.orders` and `gold.sales.orders` never embed
# identically in a multi-catalog graph; in a single-catalog graph it is a
# constant prefix.
EMBEDDING_TEXT_EXPR: dict[NodeLabel, str] = {
    NodeLabel.TABLE: (
        "concat_ws(' | ', concat_ws('.', table_catalog, table_schema, name),"
        " nullif(trim(comment), ''))"
    ),
    NodeLabel.COLUMN: (
        "concat_ws(' | ', concat_ws('.', table_catalog, table_schema, table_name, name),"
        " data_type, nullif(trim(comment), ''))"
    ),
    NodeLabel.SCHEMA: (
        "concat_ws(' | ', concat_ws('.', catalog_name, name), nullif(trim(comment), ''))"
    ),
    NodeLabel.DATABASE: "name",
}
