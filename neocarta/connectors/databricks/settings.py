"""Databricks connector configuration (env-var boundary).

Pydantic is used here — cross-field validation at a trust boundary, with a
generated schema. Internal DTOs elsewhere are ``@dataclass``.

Config is read from ``NEOCARTA_DATABRICKS_*`` environment variables. Databricks
auth/connection (host, token, profile, cluster id) is handled by the Databricks
SDK's own official ``DATABRICKS_*`` variables and is not redefined here.
"""

from __future__ import annotations

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neocarta.connectors.databricks._platform.catalogs import resolve_catalogs
from neocarta.connectors.databricks._platform.identifiers import (
    validate_identifier,
    validate_serving_endpoint_name,
    validate_uc_volume_subpath,
)
from neocarta.connectors.databricks.contract import DEFAULT_EMBEDDING_ENDPOINT


class SparkIngestSettings(BaseSettings):
    """Environment-backed configuration for the Databricks schema ingest.

    Validators reject unsafe identifiers before any Spark or Neo4j work starts.
    """

    model_config = SettingsConfigDict(env_prefix="NEOCARTA_DATABRICKS_")

    # Databricks secret scope holding the Neo4j credentials read on-cluster.
    # Required and has no default, so an unconfigured run fails at config load
    # rather than silently reading an unprovisioned scope. (Local/Spark Connect
    # runs can instead pass credentials directly; see DatabricksSparkSchemaConnector.)
    secret_scope: str = ""
    # The primary catalog to ingest.
    catalog: str
    # Comma-separated list of catalogs to ingest into one graph. Blank means
    # "ingest only `catalog`" (single-catalog behavior). When set, every listed
    # catalog is extracted into the same Neo4j graph with one Database node each.
    # Each entry is `catalog` or `catalog:layer` (e.g. "cat_silver:silver").
    # The optional `:layer` suffix drives the Table node `layer` property; an
    # entry with no suffix yields layer=null.
    catalogs: str = ""
    # Comma-separated bare schema names under each ingested catalog. Blank means
    # "every schema in the catalog". Metadata FK inference (in the enrichment
    # layer) is scoped within each (catalog, schema).
    schemas: str = ""
    # Optional cloud platform tag for the Database node `platform` property
    # (AWS/AZURE/GCP). Unity Catalog does not expose the cloud in
    # information_schema, so it is supplied here when known. Blank yields a null
    # `platform`; the companion `service` is always the constant "DATABRICKS".
    platform: str = ""
    # Sample-value extraction.
    include_values: bool = True
    sample_limit: int = 10
    sample_cardinality_threshold: int = 50
    stack_chunk_size: int = 50
    # Neo4j Spark Connector batch.size.
    neo4j_batch_size: int = 20000
    # Relationship write parallelism. 1 (default) coalesces to a single
    # partition, the safe default for Neo4j lock contention. A value > 1
    # repartitions (a full shuffle) for tuned parallel relationship writes.
    rel_write_partitions: int = 1
    # FK discovery guardrail. 0 (default) disables it. When > 0 and the extracted
    # column count exceeds it, declared-FK discovery is skipped (extract and load
    # still run) and the skip is recorded in the run summary.
    fk_max_columns: int = 0
    # Inline embedding feature flags — all off by default; turn on one label at a
    # time. When all are off the connector runs in external mode (no vectors;
    # `neocarta.enrichment` adds them later). When any is on, the node-write loop
    # embeds in-cluster via ai_query against `embedding_endpoint`.
    include_embeddings_tables: bool = False
    include_embeddings_columns: bool = False
    include_embeddings_schemas: bool = False
    include_embeddings_databases: bool = False
    # Databricks model-serving endpoint used by inline ai_query embedding.
    embedding_endpoint: str = DEFAULT_EMBEDDING_ENDPOINT
    # Expected embedding vector length; checked against the endpoint at preflight.
    # 1024 matches the default databricks-gte-large-en endpoint. Set to match the
    # rest of neocarta when the graph spans multiple datasources.
    embedding_dimension: int = 1024
    # Node embedding + Neo4j node write are batched by table range so no
    # whole-catalog staging table is materialized. Tables per batch; >= 1.
    embedding_batch_tables: int = 200
    # Per-batch embedding-failure count gate. If a batch produces more than this
    # many rows with a non-null embedding_error, the run fails before that batch
    # is written. 0 = unlimited (gate disabled), mirroring `fk_max_columns`.
    embedding_failure_max: int = 0
    # Writable UC Volume *subpath* (/Volumes/<cat>/<schema>/<vol>/<subdir>) where
    # inline mode freezes each batch's ai_query result to a transient Delta path
    # (read back by both the failure gate and the Neo4j write, then deleted) so
    # the endpoint is called exactly once per item. Required only when inline
    # embeddings are on; unused and unvalidated in external mode.
    embedding_staging_volume: str = ""
    # Cross-run embedding ledger. When on (inline mode only), each batch reuses
    # the stored vector for any node whose `embedding_text_hash` and model are
    # unchanged since the last run, calling ai_query only for misses. Off by
    # default. `ledger_path` is the durable Delta ledger root; blank derives a
    # sibling "ledger" directory under the same UC volume as
    # `embedding_staging_volume` (see resolve_ledger_path).
    ledger_enabled: bool = False
    ledger_path: str = ""

    @field_validator("rel_write_partitions")
    @classmethod
    def _validate_rel_write_partitions(cls, v: int) -> int:
        """Reject < 1: 0 or negative is not a valid partition count."""
        if v < 1:
            raise ValueError(
                "NEOCARTA_DATABRICKS_REL_WRITE_PARTITIONS must be >= 1"
                f" (got {v}); 1 keeps the safe single-partition default"
            )
        return v

    @field_validator("fk_max_columns")
    @classmethod
    def _validate_fk_max_columns(cls, v: int) -> int:
        """Reject negative: 0 means unlimited (disabled), > 0 is the cap."""
        if v < 0:
            raise ValueError(
                "NEOCARTA_DATABRICKS_FK_MAX_COLUMNS must be >= 0"
                f" (got {v}); 0 disables the guardrail"
            )
        return v

    @field_validator("catalog")
    @classmethod
    def _validate_catalog(cls, v: str) -> str:
        """Require a single safe Databricks catalog identifier."""
        return validate_identifier(v)

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, v: str) -> str:
        """Strip and upper-case the optional platform tag (blank stays blank)."""
        return v.strip().upper()

    @field_validator("catalogs")
    @classmethod
    def _validate_catalogs(cls, v: str) -> str:
        """Validate each entry in the multi-catalog ingest list, if set.

        Each entry is ``catalog`` or ``catalog:layer``. The catalog must be a
        safe identifier; a ``:layer`` suffix must be a single non-empty
        alphanumeric/underscore token. A malformed entry fails at startup.
        """
        for part in v.split(","):
            entry = part.strip()
            if not entry:
                continue
            if entry.count(":") > 1:
                raise ValueError(
                    f"Invalid NEOCARTA_DATABRICKS_CATALOGS entry {entry!r};"
                    " expected 'catalog' or a single 'catalog:layer' pair"
                )
            name, sep, layer = entry.partition(":")
            validate_identifier(name.strip(), label="catalog")
            if sep:
                layer = layer.strip()
                if not layer or not layer.replace("_", "").isalnum():
                    raise ValueError(
                        f"Invalid NEOCARTA_DATABRICKS_CATALOGS layer {layer!r};"
                        " expected a non-empty alphanumeric/underscore token"
                    )
        return v

    def resolved_catalogs(self) -> list[str]:
        """Catalogs to ingest, resolved through the shared parser.

        Delegates to the module-level :func:`resolve_catalogs` so every consumer
        resolves the identical catalog set from the same input.
        """
        return resolve_catalogs(self.catalog, self.catalogs)

    def layer_map(self) -> dict[str, str]:
        """Parsed catalog -> layer mapping, read from `catalogs`.

        Each entry is ``catalog`` or ``catalog:layer``; an entry with no layer
        suffix contributes no mapping, so its Table nodes carry a null layer.
        """
        out: dict[str, str] = {}
        for part in self.catalogs.split(","):
            entry = part.strip()
            if not entry or ":" not in entry:
                continue
            catalog, layer = (s.strip() for s in entry.split(":", 1))
            out[catalog] = layer
        return out

    @field_validator("embedding_batch_tables")
    @classmethod
    def _validate_embedding_batch_tables(cls, v: int) -> int:
        """Reject < 1: a batch must contain at least one table."""
        if v < 1:
            raise ValueError(
                "NEOCARTA_DATABRICKS_EMBEDDING_BATCH_TABLES must be >= 1"
                f" (got {v}); use a large value for a single batch"
            )
        return v

    @field_validator("embedding_failure_max")
    @classmethod
    def _validate_embedding_failure_max(cls, v: int) -> int:
        """Reject negative: 0 means unlimited (gate disabled), > 0 is the cap."""
        if v < 0:
            raise ValueError(
                "NEOCARTA_DATABRICKS_EMBEDDING_FAILURE_MAX must be >= 0"
                f" (got {v}); 0 disables the per-batch failure gate"
            )
        return v

    @field_validator("embedding_endpoint")
    @classmethod
    def _validate_embedding_endpoint(cls, v: str) -> str:
        """Reject endpoint names that cannot be safely interpolated into SQL."""
        return validate_serving_endpoint_name(v)

    @field_validator("ledger_path")
    @classmethod
    def _validate_ledger_path(cls, v: str) -> str:
        """Normalize the optional ledger volume path; blank stays blank.

        Blank means "derive a sibling of the staging volume" at runtime (see
        resolve_ledger_path), so an unset path is valid. When set it must be a
        /Volumes/<catalog>/<schema>/<volume>/<subdir> subpath, validated the
        same way as the staging volume, with the trailing slash trimmed.
        """
        if not v.strip():
            return ""
        return validate_uc_volume_subpath(v.strip(), label="NEOCARTA_DATABRICKS_LEDGER_PATH")

    def any_embeddings_enabled(self) -> bool:
        """True when at least one per-label inline embedding flag is on.

        This is the single switch between external mode (all off; vectors added
        later by enrichment) and inline mode (embed in-cluster during ingest).
        """
        return any(
            (
                self.include_embeddings_tables,
                self.include_embeddings_columns,
                self.include_embeddings_schemas,
                self.include_embeddings_databases,
            )
        )

    @model_validator(mode="after")
    def _validate_feature_coherence(self) -> SparkIngestSettings:
        """Cross-field sanity check, enforced at config load (job startup).

        Inline mode requires a transient staging volume: there is nowhere to
        freeze each batch's ai_query pass otherwise.
        """
        if self.any_embeddings_enabled():
            if not self.embedding_staging_volume.strip():
                raise ValueError(
                    "inline embeddings require NEOCARTA_DATABRICKS_EMBEDDING_STAGING_VOLUME"
                    " (a /Volumes/<catalog>/<schema>/<volume>/<subdir> path for the"
                    " transient per-batch ai_query materialization)"
                )
            validate_uc_volume_subpath(
                self.embedding_staging_volume, label="NEOCARTA_DATABRICKS_EMBEDDING_STAGING_VOLUME"
            )
        return self
