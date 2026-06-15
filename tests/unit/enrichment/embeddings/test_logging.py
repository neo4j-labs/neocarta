"""Logging behaviour for the embeddings subsystem (counts only; never text or vectors)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector, OpenAIEmbeddingsConnector
from neocarta.enrichment.embeddings.utils import write_embeddings_to_graph
from neocarta.enums import NodeLabel

_BASE_LOGGER = "neocarta.enrichment.embeddings.base"
_UTILS_LOGGER = "neocarta.enrichment.embeddings.utils"
_OPENAI_LOGGER = "neocarta.enrichment.embeddings.openai_embeddings"


def _fake_embeddings_response(**kwargs):
    """One embedding per input (returned reversed to exercise index sorting)."""
    inputs = kwargs["input"]
    data = [SimpleNamespace(index=i, embedding=[float(i)]) for i in range(len(inputs))]
    return SimpleNamespace(data=list(reversed(data)))


def test_create_embeddings_sync_logs_count_not_text(caplog):
    client = MagicMock()
    client.embeddings.create.side_effect = _fake_embeddings_response
    connector = OpenAIEmbeddingsConnector(neo4j_driver=MagicMock(), client=client)
    nodes = pd.DataFrame(
        {
            "id": ["a", "b", "c"],
            "node_label": ["Column", "Column", "Column"],
            "description": ["alpha secret", "beta secret", "gamma secret"],
        }
    )

    with caplog.at_level(logging.INFO, logger=_BASE_LOGGER):
        connector.create_embeddings_sync(nodes, batch_size=10)

    msgs = [r.getMessage() for r in caplog.records if r.name == _BASE_LOGGER]
    assert any("Embedded 3 descriptions" in m for m in msgs)
    # The description text must never appear in a log line.
    assert all("secret" not in m for m in msgs)


def test_probe_dimensions_logs_dimension_and_model(caplog):
    # LiteLLM connector leaves dimensions=None, so it actually probes (and logs).
    connector = LiteLLMEmbeddingsConnector(
        neo4j_driver=MagicMock(), embedding_model="text-embedding-3-small"
    )
    with patch("neocarta.enrichment.embeddings.litellm_embeddings.litellm") as mock_litellm:
        mock_litellm.embedding.return_value = SimpleNamespace(
            data=[{"embedding": [0.0, 0.1, 0.2, 0.3, 0.4]}]
        )
        with caplog.at_level(logging.INFO, logger=_BASE_LOGGER):
            connector._probe_dimensions_sync()

    msgs = [r.getMessage() for r in caplog.records if r.name == _BASE_LOGGER]
    assert any(
        "Detected embedding dimension 5" in m and "text-embedding-3-small" in m for m in msgs
    )


# A realistic provider error whose str() echoes both the input description and a
# (masked) API key — exactly what the OpenAI/LiteLLM SDKs put in the exception body.
_LEAKY_ERROR = RuntimeError(
    "Error code: 400 - {'error': {'message': \"Invalid input "
    "'super secret table description'; key sk-proj-LEAKED\"}}"
)


def test_provider_error_logs_type_only_without_leak(caplog):
    client = MagicMock()
    client.embeddings.create.side_effect = _LEAKY_ERROR
    connector = OpenAIEmbeddingsConnector(neo4j_driver=MagicMock(), client=client)

    with caplog.at_level(logging.WARNING, logger=_OPENAI_LOGGER):
        result = connector._create_embedding_sync("super secret table description")

    assert result is None
    records = [r for r in caplog.records if r.name == _OPENAI_LOGGER]
    assert records
    assert records[0].levelno == logging.WARNING
    msg = records[0].getMessage()
    # Only the exception type is logged — never the echoed input or key.
    assert "RuntimeError" in msg
    assert "super secret" not in msg
    assert "sk-proj-LEAKED" not in msg


def test_provider_error_async_logs_type_only_without_leak(caplog):
    async_client = MagicMock()
    async_client.embeddings.create = AsyncMock(side_effect=_LEAKY_ERROR)
    connector = OpenAIEmbeddingsConnector(neo4j_driver=MagicMock(), async_client=async_client)

    with caplog.at_level(logging.WARNING, logger=_OPENAI_LOGGER):
        result = asyncio.run(connector._create_embedding_async("super secret table description"))

    assert result is None
    msgs = [r.getMessage() for r in caplog.records if r.name == _OPENAI_LOGGER]
    assert any("RuntimeError" in m for m in msgs)
    assert all("super secret" not in m and "sk-proj-LEAKED" not in m for m in msgs)


def test_create_embeddings_async_logs_count_not_text(caplog):
    async_client = MagicMock()
    async_client.embeddings.create = AsyncMock(side_effect=_fake_embeddings_response)
    connector = OpenAIEmbeddingsConnector(neo4j_driver=MagicMock(), async_client=async_client)
    nodes = pd.DataFrame(
        {
            "id": ["a", "b", "c"],
            "node_label": ["Column", "Column", "Column"],
            "description": ["alpha secret", "beta secret", "gamma secret"],
        }
    )

    with caplog.at_level(logging.INFO, logger=_BASE_LOGGER):
        asyncio.run(connector.create_embeddings_async(nodes, batch_size=10))

    msgs = [r.getMessage() for r in caplog.records if r.name == _BASE_LOGGER]
    assert any("Embedded 3 descriptions" in m for m in msgs)
    assert all("secret" not in m for m in msgs)


def test_probe_dimensions_async_logs_dimension_and_model(caplog):
    connector = LiteLLMEmbeddingsConnector(
        neo4j_driver=MagicMock(), embedding_model="text-embedding-3-small"
    )
    with patch("neocarta.enrichment.embeddings.litellm_embeddings.litellm") as mock_litellm:
        mock_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [0.0, 0.1, 0.2, 0.3, 0.4]}])
        )
        with caplog.at_level(logging.INFO, logger=_BASE_LOGGER):
            asyncio.run(connector._probe_dimensions_async())

    msgs = [r.getMessage() for r in caplog.records if r.name == _BASE_LOGGER]
    assert any(
        "Detected embedding dimension 5" in m and "text-embedding-3-small" in m for m in msgs
    )


def test_run_logs_per_label_summary(caplog):
    # OpenAI connector defaults dimensions=768, so the probe early-returns (no client call).
    connector = OpenAIEmbeddingsConnector(neo4j_driver=MagicMock(), client=MagicMock())
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
        caplog.at_level(logging.INFO, logger=_BASE_LOGGER),
    ):
        connector.run(node_labels=[NodeLabel.TABLE], batch_size=10)

    msgs = [r.getMessage() for r in caplog.records if r.name == _BASE_LOGGER]
    assert any("Embedding Table nodes" in m for m in msgs)
    assert any("No Table nodes needed embedding" in m for m in msgs)
    # The NodeLabel enum renders as its value ("Table"), not "NodeLabel.TABLE".
    assert all("NodeLabel.TABLE" not in m for m in msgs)


def test_write_embeddings_to_graph_logs_pattern_count_not_vectors(caplog):
    summary = MagicMock()
    summary.counters.properties_set = 2
    driver = MagicMock()
    driver.execute_query.return_value = ([], summary, None)
    embeddings_df = pd.DataFrame({"id": ["a", "b"], "embedding": [[0.11, 0.22], [0.33, 0.44]]})

    with caplog.at_level(logging.INFO, logger=_UTILS_LOGGER):
        write_embeddings_to_graph(embeddings_df, NodeLabel.TABLE, driver)

    msgs = [r.getMessage() for r in caplog.records if r.name == _UTILS_LOGGER]
    assert any("Wrote 2 embeddings to (:Table)" in m for m in msgs)
    # Embedding vector values must never be logged.
    assert all("0.11" not in m and "0.33" not in m for m in msgs)
