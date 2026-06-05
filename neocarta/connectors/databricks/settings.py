"""Databricks connector configuration (env-var boundary).

Pydantic is used here — cross-field validation at a trust boundary, with a
generated schema. Internal DTOs elsewhere are ``@dataclass``.

Config is read from ``NEOCARTA_DATABRICKS_*`` environment variables. Databricks
auth/connection (host, token, profile, cluster id) is handled by the Databricks
SDK's own official ``DATABRICKS_*`` variables and is not redefined here.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neocarta.connectors.databricks._platform.catalogs import resolve_catalogs
from neocarta.connectors.databricks._platform.identifiers import validate_identifier


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
