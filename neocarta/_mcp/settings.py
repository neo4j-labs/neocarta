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
    """

    embedding_model: str = "text-embedding-3-small"
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str = "neo4j"


mcp_server_settings = Settings()
