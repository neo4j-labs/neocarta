"""Tests for the shared CLI connector helpers in ``_common.py``.

Covers the LiteLLM embedder construction (provider-agnostic, optional
dimensions forwarded via ``litellm_kwargs``) and the embedding-run error wrapper
that keeps the CLI's structured-error contract intact.
"""

from unittest.mock import MagicMock, patch

import pytest

from neocarta._cli.commands._common import _build_embedder, _run_embeddings
from neocarta._cli.config import CLISettings
from neocarta._cli.errors import CLIError
from neocarta.enums import NodeLabel
from neocarta.errors import EnrichmentError


def test_build_embedder_returns_litellm_connector_without_dimensions():
    settings = CLISettings(
        embedding_model="text-embedding-3-small",
        embedding_dimensions=None,
        neo4j_database="neo4j",
    )
    driver = MagicMock()
    with patch("neocarta.enrichment.embeddings.LiteLLMEmbeddingsConnector") as mock_cls:
        result = _build_embedder(settings, driver)

    mock_cls.assert_called_once_with(
        neo4j_driver=driver,
        embedding_model="text-embedding-3-small",
        database_name="neo4j",
        litellm_kwargs=None,
    )
    assert result is mock_cls.return_value


def test_build_embedder_forwards_dimensions_when_set():
    settings = CLISettings(
        embedding_model="gemini-embedding-001",
        embedding_dimensions=512,
        neo4j_database="graph",
    )
    driver = MagicMock()
    with patch("neocarta.enrichment.embeddings.LiteLLMEmbeddingsConnector") as mock_cls:
        _build_embedder(settings, driver)

    mock_cls.assert_called_once_with(
        neo4j_driver=driver,
        embedding_model="gemini-embedding-001",
        database_name="graph",
        litellm_kwargs={"dimensions": 512},
    )


def test_run_embeddings_wraps_non_neocarta_error():
    # LiteLLM surfaces missing creds / bad model id as a plain RuntimeError from
    # the dimension probe — it must become a clean upstream_error envelope.
    probe_failure = RuntimeError("Failed to probe embedding dimension")
    embedder = MagicMock()
    embedder.run.side_effect = probe_failure

    with pytest.raises(CLIError) as excinfo:
        _run_embeddings(embedder, [NodeLabel.TABLE])

    assert excinfo.value.code == "upstream_error"
    assert excinfo.value.__cause__ is probe_failure
    embedder.run.assert_called_once_with(node_labels=[NodeLabel.TABLE])


def test_run_embeddings_passes_neocarta_error_through():
    # NeocartaError subclasses are re-raised unchanged so the command's
    # cli_error_from adapter maps them to their declared exit code.
    err = EnrichmentError("provider exploded")
    embedder = MagicMock()
    embedder.run.side_effect = err

    with pytest.raises(EnrichmentError) as excinfo:
        _run_embeddings(embedder, [NodeLabel.COLUMN])

    assert excinfo.value is err
