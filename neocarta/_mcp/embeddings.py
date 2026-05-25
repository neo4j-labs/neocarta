"""Embedding utilities for the MCP server."""

from neo4j import AsyncDriver

from ..enrichment.embeddings import LiteLLMEmbeddingsConnector
from .settings import mcp_server_settings


def create_embedder(
    neo4j_driver: AsyncDriver,
    database_name: str = "neo4j",
) -> LiteLLMEmbeddingsConnector:
    """Create a LiteLLMEmbeddingsConnector configured for the MCP server.

    Parameters
    ----------
    neo4j_driver: AsyncDriver
        The Neo4j async driver (stored on the connector but not used for
        single-embedding calls like ``_create_embedding_async``).
    database_name: str
        The Neo4j database name.

    Returns:
    -------
    LiteLLMEmbeddingsConnector
        Connector configured with the MCP server's embedding model, dimensions,
        and optional API overrides.
    """
    return LiteLLMEmbeddingsConnector(
        neo4j_driver=neo4j_driver,  # type: ignore[arg-type]
        embedding_model=mcp_server_settings.embedding_model,
        database_name=database_name,
    )
