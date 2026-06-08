"""Settings for the Neocarta CLI, loaded from environment variables.

Resolution order, highest priority first:

1. CLI flag (applied at the command handler via :func:`resolve`).
2. Environment variable (a ``.env`` in the current working directory is loaded
   automatically by :func:`load_settings`).
3. Built-in default declared on the settings model.

A YAML config source is intentionally not supported in this first release.
"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import CLIError

# Public env-var contract surfaced through ``neocarta agent-context``.
ENV_VARS: dict[str, str] = {
    "NEO4J_URI": "Neo4j Bolt URI.",
    "NEO4J_USERNAME": "Neo4j username.",
    "NEO4J_PASSWORD": "Neo4j password (secret).",
    "NEO4J_DATABASE": "Neo4j database name (default: neo4j).",
    "OPENAI_API_KEY": "OpenAI API key for embeddings (secret).",
    "GCP_PROJECT_ID": "Google Cloud project ID.",
    "GCP_PROJECT_NUMBER": "Google Cloud project number (for `dataplex *`).",
    "BIGQUERY_DATASET_ID": "Default BigQuery dataset ID.",
    "BIGQUERY_REGION": "BigQuery region for INFORMATION_SCHEMA queries.",
    "DATAPLEX_LOCATION": "Dataplex location, e.g. `us` (for `dataplex *`).",
    "GOOGLE_APPLICATION_CREDENTIALS": "Path to a GCP service-account JSON (secret).",
    "CSV_DIRECTORY": "Directory containing CSV metadata files (for `csv ingest`).",
    "OSI_SPEC_SOURCE": "Path or URL to an OSI YAML spec (for `osi ingest`).",
    "OSI_SEMANTIC_MODEL_NAME": "Name of the OsiSemanticModel to export (for `osi export`).",
}


class CLISettings(BaseSettings):
    """All environment-driven settings consumed by the CLI."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    # Neo4j
    neo4j_uri: str | None = Field(default=None, validation_alias="NEO4J_URI")
    neo4j_username: str | None = Field(default=None, validation_alias="NEO4J_USERNAME")
    # Secrets are wrapped in pydantic.SecretStr so accidental serialization
    # (json.dumps, repr, log statements) emits "**********" instead of the
    # real value. Unwrap inline at the point of use with .get_secret_value().
    neo4j_password: SecretStr | None = Field(default=None, validation_alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", validation_alias="NEO4J_DATABASE")

    # Embeddings / OpenAI
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 100

    # BigQuery
    gcp_project_id: str | None = Field(default=None, validation_alias="GCP_PROJECT_ID")
    bigquery_dataset_id: str | None = Field(default=None, validation_alias="BIGQUERY_DATASET_ID")
    bigquery_region: str = Field(default="region-us", validation_alias="BIGQUERY_REGION")

    # Dataplex
    gcp_project_number: str | None = Field(default=None, validation_alias="GCP_PROJECT_NUMBER")
    dataplex_location: str | None = Field(default=None, validation_alias="DATAPLEX_LOCATION")

    # CSV
    csv_directory: str | None = Field(default=None, validation_alias="CSV_DIRECTORY")

    # OSI
    osi_spec_source: str | None = Field(default=None, validation_alias="OSI_SPEC_SOURCE")
    osi_semantic_model_name: str | None = Field(
        default=None, validation_alias="OSI_SEMANTIC_MODEL_NAME"
    )


def load_settings() -> CLISettings:
    """
    Load CLI settings from the environment.

    A ``.env`` file in the working directory is loaded into ``os.environ``
    before reading.

    Returns:
    -------
    CLISettings
        Populated settings instance.
    """
    load_dotenv()
    return CLISettings()


def resolve(override: Any, fallback: Any) -> Any:
    """
    Apply a CLI flag override on top of an environment-derived value.

    Parameters
    ----------
    override : Any
        Value from a Click option. ``None`` means "flag not supplied".
    fallback : Any
        Value already resolved from env / default.

    Returns:
    -------
    Any
        ``override`` if it is not ``None``, otherwise ``fallback``.
    """
    return override if override is not None else fallback


def require(name: str, value: Any, *, env_var: str | None = None) -> Any:
    """
    Raise :class:`CLIError` if ``value`` is empty, otherwise return it.

    Parameters
    ----------
    name : str
        Setting name for the error message (e.g. ``"--project-id"``).
    value : Any
        The resolved value to validate.
    env_var : str, optional
        Name of the env var that could supply this setting; included in the
        suggestion so the agent learns the fix.
    """
    if value is None or value == "":
        suggestion = (
            f"Pass {name} on the command line or set {env_var}." if env_var else f"Pass {name}."
        )
        raise CLIError("usage_error", f"Missing required setting: {name}.", suggestion=suggestion)
    return value


def require_secret(name: str, value: SecretStr | None, *, env_var: str | None = None) -> SecretStr:
    """
    Raise :class:`CLIError` if a :class:`SecretStr` is unset or empty.

    Returns the :class:`SecretStr` itself, never the unwrapped string — callers
    should call ``.get_secret_value()`` inline at the point of use so the raw
    secret never lives as a named local variable.

    Parameters
    ----------
    name : str
        Setting name for the error message (e.g. ``"NEO4J_PASSWORD"``).
    value : SecretStr or None
        The resolved secret to validate.
    env_var : str, optional
        Name of the env var that could supply this setting; included in the
        suggestion so the agent learns the fix.
    """
    if value is None or value.get_secret_value() == "":
        suggestion = f"Set {env_var}." if env_var else f"Provide {name}."
        raise CLIError("usage_error", f"Missing required setting: {name}.", suggestion=suggestion)
    return value
