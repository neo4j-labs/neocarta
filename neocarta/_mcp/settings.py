"""Settings for the MCP server loaded from environment variables."""

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    """MCP server settings loaded from environment variables.

    Embedding provider configuration is handled by LiteLLM. ``embedding_model``
    follows LiteLLM's naming (e.g. ``"text-embedding-3-small"``,
    ``"gemini-embedding-001"``, ...).
    Auth is read from the provider's environment
    variables (``OPENAI_API_KEY``, ``GEMINI_API_KEY``, ...).

    ``embedding_dimensions`` (``EMBEDDING_DIMENSIONS``) must match the dimension
    the graph was embedded at, so query embeddings and the stored vectors agree;
    models that do not support truncation ignore it. ``EMBEDDING_BATCH_SIZE`` is
    intentionally absent — the MCP server embeds a single query at a time and
    never batches, so it does not apply here.

    ``sql_dialect`` / ``default_project_id`` / ``default_schema_id`` configure how
    the ``capture_task_memory`` tool parses and canonicalizes captured SQL, keeping the
    memory tools warehouse-agnostic. ``sql_dialect`` is the sqlglot dialect (and
    platform selector) passed to ``parse_sql_query``; today only ``"bigquery"``
    and ``"snowflake"`` are supported. ``default_project_id`` / ``default_schema_id``
    fill in the catalog/namespace for SQL that is not fully qualified — the pair
    maps per warehouse (BigQuery: project → project_id, dataset → schema_id;
    Snowflake: database → project_id, schema → schema_id).
    """

    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int | None = None
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str = "neo4j"
    sql_dialect: str = "bigquery"
    default_project_id: str | None = None
    default_schema_id: str | None = None


mcp_server_settings = Settings()
