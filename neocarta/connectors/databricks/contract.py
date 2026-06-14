"""Graph contract: node-label / relationship-type subsets and node properties.

Node labels and relationship types are the canonical neocarta enums
(`neocarta.enums.NodeLabel` / `RelationshipType`); this connector manages only
the subset listed in `MANAGED_NODE_LABELS` / `MANAGED_REL_TYPES`. Identifier
production lives in `ingest.contract_expr`, which holds the byte-identical Python
(`node_id` / `qualified_name`) and Spark (`node_id_expr` / `qualified_name_expr`)
builders — no id is built here. The connector deliberately does NOT use the
shared `neocarta.connectors.utils.generate_id` helpers: their normalization is
lossy (it folds hyphens and spaces to underscores) and so is not collision-safe
as a Unity Catalog identity key; see `ingest.contract_expr` for the full
rationale. `EdgeSource` is connector-specific provenance with no neocarta-wide
equivalent.
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

# Graph contract emitted by this connector. Every run is a clean rebuild, so
# the version is a marker stamped on each node, not a migration target. The
# shape extends the neocarta core RDBMS model (neocarta/data_model/rdbms) with
# a few additive properties; the Pydantic subclasses in expanded.py are the
# source of truth and NODE_PROPERTIES is derived from them.
#
# Every node's `id` (the Neo4j MERGE key) is an md5 hash of its lowercased
# dotted path, and `qualified_name` carries that readable path as a property.
# The hash is the collision-safe identity key; the readable path is for humans.
# See ingest.contract_expr for why the id is hashed rather than the dotted string.
#
# Node properties beyond core:
#   Database: qualified_name, contract_version. service is the constant
#     "DATABRICKS"; platform is the cloud tag (AWS/AZURE/GCP) from
#     NEOCARTA_DATABRICKS_PLATFORM, null when unset. Both are stored upper-cased
#     to match the core convention.
#   Schema: qualified_name, contract_version.
#   Table: qualified_name, catalog, schema, layer (bronze/silver/gold, from a
#     configurable catalog->layer map, null when unmapped), table_type, created,
#     last_altered, contract_version.
#   Column: qualified_name, catalog, schema, table, ordinal_position,
#     contract_version. is_primary_key / is_foreign_key come from the catalog's
#     DECLARED constraints, matching core's declared-only semantics.
#   Value: count, catalog, schema, last_run (run-start stamp; a scoped
#     server-side delete purges Values older than the run start),
#     contract_version. Values are never embedded.
#
# REFERENCES edges carry confidence, source, and criteria. source is an
# EdgeSource value (declared or inferred from metadata); inferred edges never
# set the Column key flags.
CONTRACT_VERSION = "1.0"

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
