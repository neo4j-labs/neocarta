"""DBxCarta configuration (env-var boundary).

Pydantic is used here — this is one of the two places the Python Focus skill
explicitly calls out (the other being external-data parsing): cross-field
validation at a trust boundary, with a generated schema.

Internal DTOs elsewhere are `@dataclass`, per the skill's decision table.
"""

from __future__ import annotations

from dbxcarta.core.catalogs import resolve_catalogs
from dbxcarta.core.config import derive_ops_config
from dbxcarta.core.identifiers import (
    parse_volume_path,
    split_qualified_name,
    validate_identifier,
    validate_serving_endpoint_name,
    validate_uc_volume_subpath,
)
from dbxcarta.spark.contract import DEFAULT_EMBEDDING_ENDPOINT
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class SparkIngestSettings(BaseSettings):
    """Environment-backed configuration for the ingest job.

    Required fields describe the Databricks catalog, summary sinks, and Neo4j
    secret scope. Validators reject unsafe identifiers and incoherent feature
    flag combinations before Spark or Neo4j work starts.
    """

    # Required, per-integration: set in each examples/<name>/dbxcarta-overlay.env
    # (dbxcarta-neo4j-<example>). No default, so a run without a selected overlay
    # fails at config load instead of silently reading an unprovisioned scope.
    databricks_secret_scope: str
    # Used by verify's catalog-vs-graph checks (information_schema queries).
    # When unset, those checks self-skip with a `catalog.no_warehouse` violation.
    databricks_warehouse_id: str = ""
    dbxcarta_catalog: str
    # Comma-separated list of catalogs to ingest into one graph. Blank means
    # "ingest only dbxcarta_catalog" — the historical single-catalog behavior,
    # so every existing preset is unaffected. When set, every listed catalog is
    # extracted into the same Neo4j graph with one Database node each.
    #
    # KNOWN LIMITATION (tracked): the ops/summary/verify path still keys off
    # the single dbxcarta_catalog. RunSummary.catalog records only that catalog,
    # and verify's catalog-vs-graph checks (id normalization, complex-type
    # round-trip) sample-validate only that catalog. The other ingested catalogs
    # are extracted and written to Neo4j but are NOT post-write verified, so
    # verification coverage shrinks as catalogs are added. Widening verify to
    # every resolved catalog is deferred to a follow-up (each extra catalog
    # multiplies the warehouse information_schema queries).
    # Each entry is `catalog` or `catalog:layer` (e.g.
    # "cat-silver:silver,cat-gold:gold"). The optional `:layer` suffix drives
    # the Table node `layer` property; an entry with no suffix yields
    # layer=null. The layer rides on the catalog entry rather than a separate
    # map, so the layer cannot name a catalog the run never ingests.
    dbxcarta_catalogs: str = ""
    # Comma-separated list of bare schema names under each ingested catalog.
    # Blank string means "every schema in the catalog". Whitespace around each
    # name is stripped. Metadata FK inference is restricted to column pairs
    # within the same (catalog, schema), so listing many schemas produces
    # disjoint subgraphs by design.
    dbxcarta_schemas: str = ""
    # Optional cloud platform tag for the Database node `platform` property
    # (e.g. AWS, AZURE, GCP). Unity Catalog does not expose the underlying
    # cloud in information_schema, so it is supplied here when known. Blank
    # (default) yields a null `platform`. The companion `service` property is
    # always the constant "DATABRICKS" and is not configurable.
    dbxcarta_platform: str = ""
    # The ops volume root (/Volumes/<ops_catalog>/<ops_schema>/<volume>) the
    # summary sinks derive from. Optional today because the overlays still set
    # the summary fields explicitly; required only once Phase 6 removes them so
    # derivation must fire. Kept blank in the historical tests that set the
    # summary fields directly.
    databricks_volume_path: str = ""
    # Derivable from databricks_volume_path when blank (see _resolve_summary_sinks).
    dbxcarta_summary_volume: str = ""
    dbxcarta_summary_table: str = ""
    # Sample values
    dbxcarta_include_values: bool = True
    dbxcarta_sample_limit: int = 10
    dbxcarta_sample_cardinality_threshold: int = 50
    dbxcarta_stack_chunk_size: int = 50
    # Embedding feature flags — all off by default; turn on one label at a time.
    dbxcarta_include_embeddings_tables: bool = False
    dbxcarta_include_embeddings_columns: bool = False
    dbxcarta_include_embeddings_values: bool = False
    dbxcarta_include_embeddings_schemas: bool = False
    dbxcarta_include_embeddings_databases: bool = False
    dbxcarta_embedding_endpoint: str = DEFAULT_EMBEDDING_ENDPOINT
    dbxcarta_embedding_dimension: int = 1024
    # Node embedding + Neo4j node write are batched by table range so no
    # whole-catalog staging table is ever materialized. Tables per batch;
    # small catalogs stay a single batch at the default. >= 1.
    dbxcarta_embedding_batch_tables: int = 200
    # Per-batch embedding-failure count gate (replaces the old failure-rate
    # gate). If a batch produces more than this many rows with a non-null
    # embedding_error the run fails before that batch is written. 0 = unlimited
    # (gate disabled), mirroring the dbxcarta_fk_max_columns convention.
    dbxcarta_embedding_failure_max: int = 0
    # Neo4j Spark Connector batch.size.
    dbxcarta_neo4j_batch_size: int = 20000
    # Relationship write parallelism. 1 (default) coalesces to a single
    # partition, byte-for-byte identical to historical writes and the safe
    # default for Neo4j lock contention. A value > 1 repartitions (a full
    # shuffle) to that many partitions for tuned parallel relationship
    # writes. Raise the default only with production evidence that Neo4j
    # handles parallel relationship writes safely.
    dbxcarta_rel_write_partitions: int = 1
    # Re-embedding ledger: skip ai_query for unchanged nodes.
    dbxcarta_ledger_enabled: bool = False
    dbxcarta_ledger_path: str = ""
    # FK discovery guardrail backstop. 0 (default) means unlimited: the
    # guardrail is disabled and default small-catalog behavior is unchanged.
    # When > 0 and the extracted column count exceeds it, FK discovery is
    # skipped entirely (extract and load still run) and the skip is recorded
    # in the run summary. This is a backstop, not a substitute for the
    # Spark-native FK rewrite.
    dbxcarta_fk_max_columns: int = 0
    # When False (default), verify violations are logged as warnings and the run
    # completes with status='success'. When True, any violation raises and the
    # task fails. Flip after two consecutive zero-violation warn-only runs.
    dbxcarta_verify_gate: bool = False

    @field_validator("dbxcarta_rel_write_partitions")
    @classmethod
    def _validate_rel_write_partitions(cls, v: int) -> int:
        """Reject < 1: 0 or negative is not a valid partition count."""
        if v < 1:
            raise ValueError(
                "DBXCARTA_REL_WRITE_PARTITIONS must be >= 1"
                f" (got {v}); 1 keeps the safe single-partition default"
            )
        return v

    @field_validator("dbxcarta_fk_max_columns")
    @classmethod
    def _validate_fk_max_columns(cls, v: int) -> int:
        """Reject negative: 0 means unlimited (disabled), > 0 is the cap."""
        if v < 0:
            raise ValueError(
                f"DBXCARTA_FK_MAX_COLUMNS must be >= 0 (got {v}); 0 disables the guardrail"
            )
        return v

    @field_validator("dbxcarta_catalog")
    @classmethod
    def _validate_catalog(cls, v: str) -> str:
        """Require a single safe Databricks catalog identifier."""
        return validate_identifier(v)

    @field_validator("dbxcarta_platform")
    @classmethod
    def _normalize_platform(cls, v: str) -> str:
        """Normalize the optional Database platform tag.

        Blank (default) is preserved as blank and resolves to a null
        `platform` graph property at build time. Any supplied value is
        stripped and upper-cased to match the neocarta core convention
        (Database.platform/service are stored uppercase).
        """
        return v.strip().upper()

    @field_validator("dbxcarta_catalogs")
    @classmethod
    def _validate_catalogs(cls, v: str) -> str:
        """Validate each entry in the multi-catalog ingest list, if set.

        Each entry is ``catalog`` or ``catalog:layer``. The catalog must be a
        safe identifier; when a ``:layer`` suffix is present it must be a single
        non-empty alphanumeric/underscore token. A malformed entry like ``cat:``
        or ``cat:a:b`` fails at startup rather than surfacing as a confusing
        graph attribute.
        """
        for part in v.split(","):
            entry = part.strip()
            if not entry:
                continue
            if entry.count(":") > 1:
                raise ValueError(
                    f"Invalid DBXCARTA_CATALOGS entry {entry!r};"
                    " expected 'catalog' or a single 'catalog:layer' pair"
                )
            name, sep, layer = entry.partition(":")
            validate_identifier(name.strip(), label="catalog")
            if sep:
                layer = layer.strip()
                if not layer or not layer.replace("_", "").isalnum():
                    raise ValueError(
                        f"Invalid DBXCARTA_CATALOGS layer {layer!r};"
                        " expected a non-empty alphanumeric/underscore token"
                    )
        return v

    def resolved_catalogs(self) -> list[str]:
        """Catalogs to ingest, resolved through the shared parser.

        Delegates to the module-level :func:`resolve_catalogs` so readiness and
        the pipeline resolve the identical catalog set from the same input.
        """
        return resolve_catalogs(self.dbxcarta_catalog, self.dbxcarta_catalogs)

    def layer_map(self) -> dict[str, str]:
        """Parsed catalog -> layer mapping, read from dbxcarta_catalogs.

        Each entry is ``catalog`` or ``catalog:layer``; an entry with no layer
        suffix contributes no mapping, so its Table nodes carry a null layer.
        """
        out: dict[str, str] = {}
        for part in self.dbxcarta_catalogs.split(","):
            entry = part.strip()
            if not entry or ":" not in entry:
                continue
            catalog, layer = (s.strip() for s in entry.split(":", 1))
            out[catalog] = layer
        return out

    @field_validator("databricks_volume_path")
    @classmethod
    def _validate_volume_root(cls, v: str) -> str:
        """Validate the ops volume root, allowing blank (not always supplied)."""
        if not v.strip():
            return ""
        # Validate through the shared core rule (exactly /Volumes/<cat>/<schema>/
        # <volume>, each part a safe identifier) rather than re-deriving it here.
        parse_volume_path(v)
        return v.rstrip("/")

    @field_validator("dbxcarta_summary_table")
    @classmethod
    def _validate_summary_table(cls, v: str) -> str:
        """Require summary history to target catalog.schema.table explicitly."""
        # Blank is derived from databricks_volume_path in _resolve_summary_sinks;
        # the derived value is well-formed by construction, so only validate
        # input. Persisted run history is a UC artifact, so a supplied target
        # must be an explicit catalog.schema.table rather than a workspace default.
        if not v.strip():
            return ""
        split_qualified_name(v, expected_parts=3, label="summary table")
        return v

    @field_validator("dbxcarta_summary_volume")
    @classmethod
    def _validate_summary_volume(cls, v: str) -> str:
        """Require a UC Volume subpath for JSON summary output."""
        if not v.strip():
            return ""
        return validate_uc_volume_subpath(v, label="DBXCARTA_SUMMARY_VOLUME")

    @field_validator("dbxcarta_embedding_batch_tables")
    @classmethod
    def _validate_embedding_batch_tables(cls, v: int) -> int:
        """Reject < 1: a batch must contain at least one table."""
        if v < 1:
            raise ValueError(
                "DBXCARTA_EMBEDDING_BATCH_TABLES must be >= 1"
                f" (got {v}); use a large value for a single batch"
            )
        return v

    @field_validator("dbxcarta_embedding_failure_max")
    @classmethod
    def _validate_embedding_failure_max(cls, v: int) -> int:
        """Reject negative: 0 means unlimited (gate disabled), > 0 is the cap."""
        if v < 0:
            raise ValueError(
                "DBXCARTA_EMBEDDING_FAILURE_MAX must be >= 0"
                f" (got {v}); 0 disables the per-batch failure gate"
            )
        return v

    @field_validator("dbxcarta_ledger_path")
    @classmethod
    def _validate_optional_volume_subpath(cls, v: str) -> str:
        """Normalize optional UC Volume paths while allowing unset values."""
        if not v.strip():
            return ""
        return validate_uc_volume_subpath(v.strip())

    @field_validator("dbxcarta_embedding_endpoint")
    @classmethod
    def _validate_embedding_endpoint(cls, v: str) -> str:
        """Reject endpoint names that cannot be safely interpolated into SQL."""
        return validate_serving_endpoint_name(v)

    @model_validator(mode="after")
    def _resolve_summary_sinks(self) -> SparkIngestSettings:
        """Derive the summary volume and table from the ops volume root when unset.

        The shared core resolver is the single owner of the base-plus-tail rule.
        When both summary fields are supplied (every overlay today, and the
        historical tests), derivation is skipped and databricks_volume_path is
        never touched, so the change is behavior-neutral until Phase 6 removes
        the explicit values. Mirrors ``ClientSettings._resolve_defaults``;
        unlike the client, databricks_volume_path is optional here, so a missing
        base when the sinks are also unset fails loudly rather than deriving
        from nothing.
        """
        if not (self.dbxcarta_summary_volume and self.dbxcarta_summary_table):
            if not self.databricks_volume_path:
                raise ValueError(
                    "DBXCARTA_SUMMARY_VOLUME/DBXCARTA_SUMMARY_TABLE are unset and "
                    "cannot be derived: DATABRICKS_VOLUME_PATH is also unset."
                )
            derived = derive_ops_config(self.databricks_volume_path)
            self.dbxcarta_summary_volume = self.dbxcarta_summary_volume or derived.summary_volume
            self.dbxcarta_summary_table = self.dbxcarta_summary_table or derived.summary_table
        return self

    @model_validator(mode="after")
    def _validate_feature_coherence(self) -> SparkIngestSettings:
        """Cross-field sanity checks.

        Fail at Settings construction (job startup) rather than halfway through
        a run. Value embeddings require sample-values to be enabled: there are
        no Value nodes to embed otherwise.
        """
        if self.dbxcarta_include_embeddings_values and not self.dbxcarta_include_values:
            raise ValueError(
                "DBXCARTA_INCLUDE_EMBEDDINGS_VALUES=true requires"
                " DBXCARTA_INCLUDE_VALUES=true (nothing to embed otherwise)"
            )
        return self
