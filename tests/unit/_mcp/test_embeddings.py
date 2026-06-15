"""Unit tests for the MCP server's embedder construction.

Covers issue #187: the MCP server must read ``EMBEDDING_DIMENSIONS`` and pass it
to the embedder so query embeddings match the dimension the graph was embedded
at. ``EMBEDDING_BATCH_SIZE`` deliberately does not apply (single-query embedding).
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# ``neocarta._mcp.settings`` instantiates a ``Settings()`` singleton at import,
# and its Neo4j fields are required — make sure they are present regardless of
# whether a .env is discoverable in the test environment.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")

from neocarta._mcp.embeddings import create_embedder


def test_create_embedder_forwards_dimensions():
    driver = MagicMock()
    fake_settings = SimpleNamespace(
        embedding_model="text-embedding-3-large",
        embedding_dimensions=256,
    )
    with (
        patch("neocarta._mcp.embeddings.mcp_server_settings", fake_settings),
        patch("neocarta._mcp.embeddings.LiteLLMEmbeddingsConnector") as mock_cls,
    ):
        result = create_embedder(driver, database_name="graph")

    mock_cls.assert_called_once_with(
        neo4j_driver=driver,
        embedding_model="text-embedding-3-large",
        database_name="graph",
        dimensions=256,
    )
    assert result is mock_cls.return_value


def test_create_embedder_dimensions_default_none():
    driver = MagicMock()
    fake_settings = SimpleNamespace(
        embedding_model="text-embedding-3-small",
        embedding_dimensions=None,
    )
    with (
        patch("neocarta._mcp.embeddings.mcp_server_settings", fake_settings),
        patch("neocarta._mcp.embeddings.LiteLLMEmbeddingsConnector") as mock_cls,
    ):
        create_embedder(driver)

    mock_cls.assert_called_once_with(
        neo4j_driver=driver,
        embedding_model="text-embedding-3-small",
        database_name="neo4j",
        dimensions=None,
    )
