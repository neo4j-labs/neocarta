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
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Shared with server
    dbxcarta_catalog: str
    # Comma-separated multi-catalog list, mirroring the server's
    # DBXCARTA_CATALOGS. Blank falls back to the single dbxcarta_catalog so
    # single-catalog examples are unaffected. Used to make the schema_dump
    # baseline cover every ingested catalog (bronze/silver/gold), not just the
    # primary anchor; the graph_rag arm is already catalog-qualified per node.
    dbxcarta_catalogs: str = ""
    dbxcarta_schemas: str = ""
    databricks_warehouse_id: str
    # Required, per-integration: set in each examples/<name>/dbxcarta-overlay.env
    # (dbxcarta-neo4j-<example>). No default, so a run without a selected overlay
    # fails at config load instead of silently reading an unprovisioned scope.
    databricks_secret_scope: str
    # Derivable from databricks_volume_path when blank (see _resolve_defaults).
    # The overlays still set them today; derivation only fires once Phase 6
    # removes them, so leaving them blank stays behavior-neutral until then.
    dbxcarta_summary_volume: str = ""
    dbxcarta_summary_table: str = ""
    databricks_volume_path: str

    # Client-specific — generation
    dbxcarta_chat_endpoint: str = ""
    dbxcarta_embedding_endpoint: str = "databricks-gte-large-en"
    dbxcarta_embed_endpoint: str = ""  # defaults to dbxcarta_embedding_endpoint

    # Client-specific — runtime
    dbxcarta_client_questions: str = ""  # derived: {volume_path}/dbxcarta/questions.json
    # 0 = run the full question set; set to a small N (e.g. 5) to evaluate only
    # the first N questions as a quick post-ingest smoke check.
    dbxcarta_client_max_questions: int = 0
    dbxcarta_client_arms: str = "no_context,schema_dump,graph_rag"
    dbxcarta_client_top_k: int = 5
    # Force re-inference even when a matching cached staging table exists.
    # The cache keys on (endpoint, arm, ordered question prompts); set this
    # when the endpoint's underlying model changed but the prompts did not.
    dbxcarta_client_refresh: bool = False
    dbxcarta_client_timeout_sec: int = 30
    # Tail-truncate the schema_dump prompt. 0 = no limit. Default 7500 chars
    # (~2k tokens at ~3.7 chars/token for dense schema text) makes schema_dump
    # a token-matched fairness baseline against graph_rag's retrieved context
    # rather than a full multi-catalog dump.
    dbxcarta_schema_dump_max_chars: int = 7500
    # 0 = no cap; set to 10-20 for dense single-schema fixtures to prevent
    # REFERENCES expansion from returning dozens of neighbor tables
    dbxcarta_client_max_expansion_tables: int = 0
    # Blend ratio for combined FK-confidence + cosine-similarity re-ranking.
    # 0.0 = pure cosine, 1.0 = pure FK confidence, 0.5 = equal weight.
    dbxcarta_client_expansion_alpha: float = 0.5

    # REFERENCES-edge confidence filter. Inclusive `>=` comparison; edges with
    # no confidence property are treated as 1.0 via COALESCE so they are never
    # silently dropped.
    dbxcarta_confidence_threshold: float = 0.8
    dbxcarta_inject_criteria: bool = True

    @field_validator("dbxcarta_catalog")
    @classmethod
    def _validate_catalog(cls, v: str) -> str:
        return validate_identifier(v)

    @field_validator("dbxcarta_catalogs")
    @classmethod
    def _validate_catalogs(cls, v: str) -> str:
        """Validate the multi-catalog list through the shared catalog rule.

        Routes through :func:`resolve_catalogs` so the client accepts the same
        ``catalog`` / ``catalog:layer`` list the pipeline does, stripping the
        ``:layer`` suffix identically. A blank or separator-only list is the
        single-catalog fallback and is left untouched, exactly as before.
        """
        names = [part.split(":", 1)[0].strip() for part in v.split(",")]
        if any(names):
            resolve_catalogs("", v)
        return v

    @field_validator("dbxcarta_summary_table")
    @classmethod
    def _validate_summary_table(cls, v: str) -> str:
        # Blank is derived from databricks_volume_path in _resolve_defaults; the
        # derived value is well-formed by construction, so only validate input.
        if not v.strip():
            return ""
        split_qualified_name(v, expected_parts=3, label="summary table")
        return v

    @field_validator("dbxcarta_summary_volume")
    @classmethod
    def _validate_summary_volume(cls, v: str) -> str:
        if not v.strip():
            return ""
        return validate_uc_volume_subpath(v, label="DBXCARTA_SUMMARY_VOLUME")

    @field_validator("databricks_volume_path")
    @classmethod
    def _validate_volume_root(cls, v: str) -> str:
        # Validate through the shared core rule (exactly /Volumes/<cat>/<schema>/
        # <volume>, each part a safe identifier) rather than re-deriving it here.
        parse_volume_path(v)
        return v.rstrip("/")

    @field_validator(
        "dbxcarta_chat_endpoint",
        "dbxcarta_embedding_endpoint",
        "dbxcarta_embed_endpoint",
    )
    @classmethod
    def _validate_serving_endpoints(cls, v: str) -> str:
        if not v.strip():
            return ""
        return validate_serving_endpoint_name(v.strip())

    @model_validator(mode="after")
    def _resolve_defaults(self) -> ClientSettings:
        if not self.dbxcarta_embed_endpoint:
            self.dbxcarta_embed_endpoint = self.dbxcarta_embedding_endpoint
        # The ops-side values are one base path with a tail; the shared core
        # resolver is the single owner of that rule. Mirrors
        # ``SparkIngestSettings._resolve_summary_sinks``, except that
        # databricks_volume_path is required (and already validated non-blank)
        # here, so deriving is always safe and needs no missing-base guard.
        if not (
            self.dbxcarta_summary_volume
            and self.dbxcarta_summary_table
            and self.dbxcarta_client_questions
        ):
            derived = derive_ops_config(self.databricks_volume_path)
            self.dbxcarta_summary_volume = self.dbxcarta_summary_volume or derived.summary_volume
            self.dbxcarta_summary_table = self.dbxcarta_summary_table or derived.summary_table
            self.dbxcarta_client_questions = (
                self.dbxcarta_client_questions or derived.client_questions
            )
        return self

    @property
    def resolved_catalogs(self) -> list[str]:
        """Catalogs the graph spans, order-preserving and de-duplicated.

        Delegates to the shared :func:`resolve_catalogs` so the client strips
        the ``:layer`` suffix and falls back to the single ``dbxcarta_catalog``
        the same way the pipeline does. This is the fix that unblocks a
        ``catalog:layer`` client run.
        """
        return resolve_catalogs(self.dbxcarta_catalog, self.dbxcarta_catalogs)

    @property
    def schemas_list(self) -> list[str]:
        return [s.strip() for s in self.dbxcarta_schemas.split(",") if s.strip()]

    @property
    def arms(self) -> list[str]:
        return [a.strip() for a in self.dbxcarta_client_arms.split(",") if a.strip()]
