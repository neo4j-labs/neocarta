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
from pydantic import Field
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
    "BIGQUERY_DATASET_ID": "Default BigQuery dataset ID.",
    "BIGQUERY_REGION": "BigQuery region for INFORMATION_SCHEMA queries.",
    "GOOGLE_APPLICATION_CREDENTIALS": "Path to a GCP service-account JSON (secret).",
}


class CLISettings(BaseSettings):
    """All environment-driven settings consumed by the CLI."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    # Neo4j
    neo4j_uri: str | None = Field(default=None, validation_alias="NEO4J_URI")
    neo4j_username: str | None = Field(default=None, validation_alias="NEO4J_USERNAME")
    neo4j_password: str | None = Field(default=None, validation_alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", validation_alias="NEO4J_DATABASE")

    # Embeddings / OpenAI
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 100

    # BigQuery
    gcp_project_id: str | None = Field(default=None, validation_alias="GCP_PROJECT_ID")
    bigquery_dataset_id: str | None = Field(default=None, validation_alias="BIGQUERY_DATASET_ID")
    bigquery_region: str = Field(default="region-us", validation_alias="BIGQUERY_REGION")


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
