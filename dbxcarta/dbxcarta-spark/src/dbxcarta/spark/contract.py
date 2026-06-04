"""Graph contract: node/relationship/edge-source enums and identifier generation.

All identifier production goes through generate_id or generate_value_id.
No call site builds an ID inline. All label and relationship references
go through NodeLabel / RelType / EdgeSource enums — no magic strings.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

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
# the optional DBXCARTA_PLATFORM config, null when unset), and `description`
# (null; UC exposes no catalog comment in the extract today); both `platform`
# and `service` are stored upper-cased to match the core convention. Column
# gains two additive booleans, `is_primary_key` and `is_foreign_key`, derived
# at extract time from the catalog's DECLARED constraints
# (information_schema.table_constraints + key_column_usage), matching core's
# declared-only semantics. Inferred REFERENCES edges never set these flags: an
# inferred edge is a relationship, not a declared constraint. Readers of an
# older graph treat the missing properties as null/false.
CONTRACT_VERSION = "1.7"

DEFAULT_EMBEDDING_ENDPOINT = "databricks-gte-large-en"

# The Database node `service` value. Constant for this connector: every
# catalog dbxcarta ingests lives in Databricks Unity Catalog. Upper-cased to
# match the neocarta core convention (Database.service examples=["BIGQUERY"]).
DATABASE_SERVICE = "DATABRICKS"


class NodeLabel(StrEnum):
    """Neo4j node labels. `.value` yields the literal label string used in
    Cypher (e.g., 'Column'); StrEnum members are str subclasses so they
    interpolate cleanly into f-strings.
    """

    DATABASE = "Database"
    SCHEMA = "Schema"
    TABLE = "Table"
    COLUMN = "Column"
    VALUE = "Value"


class RelType(StrEnum):
    """Neo4j relationship types."""

    HAS_SCHEMA = "HAS_SCHEMA"
    HAS_TABLE = "HAS_TABLE"
    HAS_COLUMN = "HAS_COLUMN"
    HAS_VALUE = "HAS_VALUE"
    REFERENCES = "REFERENCES"


class EdgeSource(StrEnum):
    """Provenance tag on REFERENCES edges. DECLARED is the Unity Catalog
    declared-FK source; INFERRED_METADATA is name/PK heuristic inference.
    """

    DECLARED = "declared"
    INFERRED_METADATA = "inferred_metadata"


# REFERENCES edge properties (additive in contract v1.0). All three are
# nullable; readers treat absence as (1.0, "declared", null) via COALESCE.
REFERENCES_PROPERTIES: tuple[str, ...] = ("confidence", "source", "criteria")


# Per-label declared node properties: the exact, complete set of columns
# that may be written to a Neo4j node. This is the single source of truth
# for the graph contract. The write boundary (run.py:_load) projects each
# node DataFrame to this tuple before the connector write, so a column is a
# graph property if and only if it is listed here. `embedding` is the only
# member that may be legitimately absent (present only when the label was
# embedded this run); it is kept last and the projection selects the
# intersection with the DataFrame columns. Everything not listed —
# information_schema helper columns, the transient `embedding_text`, and the
# embedding bookkeeping `embedding_text_hash` / `embedding_model` /
# `embedded_at` / `embedding_error` — is staging/ledger-only and never a
# graph property. Structural membership is ALSO edge-based (the HAS_* rels),
# but as of contract 1.2 the catalog/schema/table identity of Table and
# Column nodes is additionally carried as authoritative scalar properties:
# the `id` is an opaque hash, so re-deriving structure from edges or the
# cached information_schema frames on every consumer (batching, FK locality)
# was the actual smell. The edges and these scalars agree by construction
# (both derive from the same information_schema row).
NODE_PROPERTIES: dict[NodeLabel, tuple[str, ...]] = {
    NodeLabel.DATABASE: (
        "id",
        "name",
        "platform",
        "service",
        "description",
        "contract_version",
        "embedding",
    ),
    NodeLabel.SCHEMA: ("id", "name", "description", "contract_version", "embedding"),
    NodeLabel.TABLE: (
        "id",
        "name",
        "catalog",
        "schema",
        "layer",
        "description",
        "table_type",
        "created",
        "last_altered",
        "contract_version",
        "embedding",
    ),
    NodeLabel.COLUMN: (
        "id",
        "name",
        "catalog",
        "schema",
        "table",
        "type",
        "nullable",
        "is_primary_key",
        "is_foreign_key",
        "ordinal_position",
        "description",
        "contract_version",
        "embedding",
    ),
    NodeLabel.VALUE: (
        "id",
        "value",
        "count",
        "catalog",
        "schema",
        "last_run",
        "contract_version",
        "embedding",
    ),
}


# Per-label embedding-text SQL expressions. Evaluated inside the node
# builder (schema_graph.py / sample_values.py) while the raw
# information_schema helper columns are still in scope, producing one
# `embedding_text` column per node. The embed stage hashes and embeds that
# column; it no longer holds these expressions. Kept here so the builder,
# the embed stage, and the tests share one definition. Catalog leads every
# qualified name so `bronze.sales.orders` and `gold.sales.orders` never
# embed identically in a multi-catalog graph; in a single-catalog graph it
# is a constant prefix. Expression content is byte-identical to the
# pre-refactor in-place expressions, so embedding_text_hash is unchanged.
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
    NodeLabel.VALUE: "value",
}


def generate_id(*parts: str) -> str:
    """Return a normalized dot-separated identifier.

    Lowercases each part and replaces spaces and hyphens with underscores,
    then joins with dots. Must produce byte-identical output to the Spark
    expression in `dbxcarta.spark.ingest.contract_expr.id_expr`.
    """
    return ".".join(p.lower().replace(" ", "_").replace("-", "_") for p in parts)


def generate_value_id(column_id: str, value: object) -> str:
    """Return the Value node id for a sampled distinct value.

    The value portion is md5-hashed so long strings, booleans, and repeated
    literal samples produce compact stable ids under their owning Column id.
    """
    digest = hashlib.md5(str(value).encode(), usedforsecurity=False).hexdigest()
    return f"{column_id}.{digest}"
