import asyncio
from types import SimpleNamespace
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


def _fake_embeddings_response(**kwargs):
    # One embedding per input, returned out of order to verify index sorting.
    inputs = kwargs["input"]
    data = [SimpleNamespace(index=i, embedding=[float(i)]) for i in range(len(inputs))]
    return SimpleNamespace(data=list(reversed(data)))


def test_create_embeddings_sync_sends_one_request_per_batch():
    driver = MagicMock()
    client = MagicMock()
    client.embeddings.create.side_effect = _fake_embeddings_response
    connector = OpenAIEmbeddingsConnector(neo4j_driver=driver, client=client)

    nodes = pd.DataFrame(
        {
            "id": ["a", "b", "c"],
            "node_label": ["Column", "Column", "Column"],
            "description": ["alpha", "beta", "gamma"],
        }
    )

    result = connector.create_embeddings_sync(nodes, batch_size=10)

    # The whole batch is embedded in a single call, with the descriptions as a list.
    assert client.embeddings.create.call_count == 1
    assert client.embeddings.create.call_args.kwargs["input"] == ["alpha", "beta", "gamma"]
    # Results are paired back to ids in input order (index sorting undoes the shuffle).
    assert list(result["id"]) == ["a", "b", "c"]
    assert list(result["embedding"]) == [[0.0], [1.0], [2.0]]


def test_create_embeddings_async_sends_one_request_per_batch():
    driver = MagicMock()
    async_client = MagicMock()
    async_client.embeddings.create = AsyncMock(side_effect=_fake_embeddings_response)
    connector = OpenAIEmbeddingsConnector(neo4j_driver=driver, async_client=async_client)

    nodes = pd.DataFrame(
        {
            "id": ["a", "b", "c"],
            "node_label": ["Column", "Column", "Column"],
            "description": ["alpha", "beta", "gamma"],
        }
    )

    result = asyncio.run(connector.create_embeddings_async(nodes, batch_size=10))

    assert async_client.embeddings.create.call_count == 1
    assert async_client.embeddings.create.call_args.kwargs["input"] == ["alpha", "beta", "gamma"]
    assert list(result["id"]) == ["a", "b", "c"]
    assert list(result["embedding"]) == [[0.0], [1.0], [2.0]]
