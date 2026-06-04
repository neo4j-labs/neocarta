"""Environment-backed configuration for the materialize Spark job.

Pydantic is used here — the env-var trust boundary — mirroring
``SparkIngestSettings``. The ops-side paths (summary sinks and the staged
blueprint) all derive from the one ``DATABRICKS_VOLUME_PATH`` base through the
shared :func:`derive_ops_config`, so this job reads the same compact base the
host-side submit path stages the blueprint under.
"""

from __future__ import annotations

from dbxcarta.core.config import derive_ops_config
from dbxcarta.core.identifiers import (
    parse_volume_path,
    split_qualified_name,
    validate_identifier,
    validate_uc_volume_subpath,
)
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class MaterializeSettings(BaseSettings):
    """Config for the materialize job: the data catalog, the staged blueprint,
    and the run-summary sinks.

    ``dbxcarta_blueprint_volume`` is where the committed blueprint was staged on
    the ops Volume (the submit path uploads it there); the job reads it from
    there. The summary sinks and the blueprint path are all derived from
    ``databricks_volume_path`` when unset, the same rule the host-side tools use.
    The data catalog itself is created by ``dbxcarta-submit bootstrap`` before
    this job runs, so the job assumes it exists.
    """

    dbxcarta_catalog: str
    databricks_volume_path: str
    # Derivable from databricks_volume_path when blank (see _resolve_ops_paths).
    dbxcarta_summary_volume: str = ""
    dbxcarta_summary_table: str = ""
    dbxcarta_blueprint_volume: str = ""

    @field_validator("dbxcarta_catalog")
    @classmethod
    def _validate_catalog(cls, v: str) -> str:
        """Require a single safe Databricks catalog identifier."""
        return validate_identifier(v)

    @field_validator("databricks_volume_path")
    @classmethod
    def _validate_volume_root(cls, v: str) -> str:
        """Validate the ops volume root through the shared core rule."""
        parse_volume_path(v)
        return v.rstrip("/")

    @field_validator("dbxcarta_summary_table")
    @classmethod
    def _validate_summary_table(cls, v: str) -> str:
        """Require an explicit catalog.schema.table when supplied."""
        if not v.strip():
            return ""
        split_qualified_name(v, expected_parts=3, label="summary table")
        return v

    @field_validator("dbxcarta_summary_volume")
    @classmethod
    def _validate_summary_volume(cls, v: str) -> str:
        """Require a UC Volume subpath for JSON summary output when supplied."""
        if not v.strip():
            return ""
        return validate_uc_volume_subpath(v, label="DBXCARTA_SUMMARY_VOLUME")

    @field_validator("dbxcarta_blueprint_volume")
    @classmethod
    def _validate_blueprint_volume(cls, v: str) -> str:
        """Require a UC Volume subpath for the staged blueprint when supplied."""
        if not v.strip():
            return ""
        return validate_uc_volume_subpath(v, label="DBXCARTA_BLUEPRINT_VOLUME")

    @model_validator(mode="after")
    def _resolve_ops_paths(self) -> MaterializeSettings:
        """Derive the summary sinks and the staged blueprint path from the base.

        The shared core resolver is the single owner of the base-plus-tail rule.
        A supplied value (the overlays set the summary fields explicitly) wins;
        otherwise it is derived from ``databricks_volume_path``. The blueprint
        filename defaults to ``blueprint.json``, the canonical name the submit
        path stages the committed blueprint under.
        """
        derived = derive_ops_config(self.databricks_volume_path)
        self.dbxcarta_summary_volume = self.dbxcarta_summary_volume or derived.summary_volume
        self.dbxcarta_summary_table = self.dbxcarta_summary_table or derived.summary_table
        self.dbxcarta_blueprint_volume = self.dbxcarta_blueprint_volume or derived.blueprint_volume
        return self
