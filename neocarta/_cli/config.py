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
    "OPENAI_API_KEY": (
        "Embedding-provider API key, read by LiteLLM (secret). OpenAI uses "
        "OPENAI_API_KEY; other providers use their own vars (GEMINI_API_KEY, "
        "COHERE_API_KEY, AZURE_*, AWS_*, ...)."
    ),
    "EMBEDDING_MODEL": "LiteLLM embedding model id (default: text-embedding-3-small).",
    "EMBEDDING_DIMENSIONS": (
        "Embedding vector dimension for models that support truncation; ignored "
        "by models that do not. Default: auto-detected from the model."
    ),
    "EMBEDDING_BATCH_SIZE": (
        "Nodes per embedding batch during CLI ingest runs (default: 100). Not "
        "used by the MCP server, which embeds a single query at a time."
    ),
    "GCP_PROJECT_ID": "Google Cloud project ID.",
    "GCP_PROJECT_NUMBER": "Google Cloud project number (for `dataplex *`).",
    "BIGQUERY_DATASET_ID": "Default BigQuery dataset ID.",
    "BIGQUERY_REGION": "BigQuery region for INFORMATION_SCHEMA queries.",
    "DATAPLEX_LOCATION": "Dataplex location, e.g. `us` (for `dataplex *`).",
    "GOOGLE_APPLICATION_CREDENTIALS": "Path to a GCP service-account JSON (secret).",
    "CSV_DIRECTORY": "Directory containing CSV metadata files (for `csv ingest`).",
    "OSI_SPEC_SOURCE": "Path or URL to an OSI YAML spec (for `osi ingest`).",
    "OSI_SEMANTIC_MODEL_NAME": "Name of the OsiSemanticModel to export (for `osi export`).",
    "QUERY_LOG_FILE": "Path to a query-log JSON file (for `query-log ingest`).",
    "JDBC_URL": "JDBC connection URL, e.g. jdbc:postgresql://host:5432/mydb (for `jdbc schema`).",
    "JDBC_DRIVER": "Fully-qualified JDBC driver class, e.g. org.postgresql.Driver (for `jdbc schema`).",
    "JDBC_DRIVER_JAR": "Filesystem path to the JDBC driver JAR (for `jdbc schema`).",
    "SCHEMACRAWLER_JAR": (
        "Filesystem path or classpath glob to the SchemaCrawler distribution JARs "
        "(for `jdbc schema`)."
    ),
    "JDBC_USER": "Database username (for `jdbc schema`).",
    "JDBC_PASSWORD": "Database password (secret; for `jdbc schema`).",
    "JDBC_SOURCE_DATABASE_NAME": (
        "Name for the graph Database node; needed when it cannot be derived from "
        "JDBC_URL (for `jdbc schema`)."
    ),
    "JDBC_PLATFORM": "Hosting platform for the graph Database node, e.g. AWS_RDS (for `jdbc schema`).",
    "JDBC_SERVICE": (
        "Database service/engine for the graph Database node; defaults to the "
        "product SchemaCrawler reports (for `jdbc schema`)."
    ),
    "JDBC_TIMEOUT": "Max seconds for the SchemaCrawler subprocess (default: 120; for `jdbc schema`).",
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

    # Embeddings (LiteLLM, multi-provider). Provider auth (OPENAI_API_KEY,
    # GEMINI_API_KEY, AZURE_*, AWS_*, ...) is read directly from the environment
    # by LiteLLM, so no API key is parsed onto this settings object.
    embedding_model: str = Field(
        default="text-embedding-3-small", validation_alias="EMBEDDING_MODEL"
    )
    # None => let LiteLLM use the model's native dimension. Set via
    # --embedding-dimensions to request truncation on models that support it.
    embedding_dimensions: int | None = Field(default=None, validation_alias="EMBEDDING_DIMENSIONS")
    embedding_batch_size: int = Field(default=100, validation_alias="EMBEDDING_BATCH_SIZE")

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
    # Query log
    query_log_file: str | None = Field(default=None, validation_alias="QUERY_LOG_FILE")

    # JDBC (via SchemaCrawler)
    jdbc_url: str | None = Field(default=None, validation_alias="JDBC_URL")
    jdbc_driver: str | None = Field(default=None, validation_alias="JDBC_DRIVER")
    jdbc_driver_jar: str | None = Field(default=None, validation_alias="JDBC_DRIVER_JAR")
    schemacrawler_jar: str | None = Field(default=None, validation_alias="SCHEMACRAWLER_JAR")
    jdbc_user: str | None = Field(default=None, validation_alias="JDBC_USER")
    jdbc_password: SecretStr | None = Field(default=None, validation_alias="JDBC_PASSWORD")
    jdbc_source_database_name: str | None = Field(
        default=None, validation_alias="JDBC_SOURCE_DATABASE_NAME"
    )
    jdbc_platform: str | None = Field(default=None, validation_alias="JDBC_PLATFORM")
    jdbc_service: str | None = Field(default=None, validation_alias="JDBC_SERVICE")
    jdbc_timeout: int = Field(default=120, validation_alias="JDBC_TIMEOUT")


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
