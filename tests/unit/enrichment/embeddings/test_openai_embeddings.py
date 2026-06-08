import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from neocarta.enrichment.embeddings import OpenAIEmbeddingsConnector
from neocarta.enums import NodeLabel


def test_run_keeps_neo4j_driver_open():
    driver = MagicMock()
    connector = OpenAIEmbeddingsConnector(
        neo4j_driver=driver,
        client=MagicMock(),
    )

    with (
        patch("neocarta.enrichment.embeddings.base.create_vector_index"),
        patch(
            "neocarta.enrichment.embeddings.base.get_nodes_to_embed",
            return_value=pd.DataFrame(columns=["id", "node_label", "description"]),
        ),
        patch("neocarta.enrichment.embeddings.base.write_embeddings_to_graph"),
        patch.object(
            connector,
            "create_embeddings_sync",
            return_value=pd.DataFrame(columns=["id", "embedding"]),
        ),
    ):
        connector.run(node_labels=[NodeLabel.TABLE], batch_size=10)

    driver.close.assert_not_called()


def test_arun_keeps_neo4j_driver_open():
    driver = MagicMock()
    connector = OpenAIEmbeddingsConnector(
        neo4j_driver=driver,
        async_client=MagicMock(),
    )

    with (
        patch("neocarta.enrichment.embeddings.base.create_vector_index"),
        patch(
            "neocarta.enrichment.embeddings.base.get_nodes_to_embed",
            return_value=pd.DataFrame(columns=["id", "node_label", "description"]),
        ),
        patch("neocarta.enrichment.embeddings.base.write_embeddings_to_graph"),
        patch.object(
            connector,
            "create_embeddings_async",
            new=AsyncMock(return_value=pd.DataFrame(columns=["id", "embedding"])),
        ),
    ):
        asyncio.run(connector.arun(node_labels=[NodeLabel.TABLE], batch_size=10))

    driver.close.assert_not_called()
