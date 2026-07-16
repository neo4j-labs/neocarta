"""Tests for the shared CLI connector helpers in ``_common.py``.

Covers the LiteLLM embedder construction (provider-agnostic, optional
``dimensions`` argument), the ``batch_size`` threaded into ``run()``, and the
embedding-run error wrapper that keeps the CLI's structured-error contract
intact.
"""

from unittest.mock import MagicMock, patch

import pytest

from neocarta._cli.commands._common import (
    _apply_neo4j_overrides,
    _build_embedder,
    _run_embeddings,
)
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
        dimensions=None,
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
        dimensions=512,
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
    embedder.run.assert_called_once_with(node_labels=[NodeLabel.TABLE], batch_size=100)


def test_run_embeddings_forwards_batch_size():
    # EMBEDDING_BATCH_SIZE / --embedding-batch-size resolves onto the settings and
    # must reach embedder.run() — it was previously dropped.
    embedder = MagicMock()

    _run_embeddings(embedder, [NodeLabel.TABLE, NodeLabel.COLUMN], batch_size=32)

    embedder.run.assert_called_once_with(
        node_labels=[NodeLabel.TABLE, NodeLabel.COLUMN], batch_size=32
    )


def test_apply_neo4j_overrides_prefers_flags_over_env_values():
    # Flags supplied on the command line win over the env-derived settings.
    settings = CLISettings(
        neo4j_uri="bolt://env:7687",
        neo4j_username="env_user",
        neo4j_database="env_db",
    )

    _apply_neo4j_overrides(
        settings,
        neo4j_uri="bolt://flag:7687",
        neo4j_username="flag_user",
        neo4j_database="flag_db",
    )

    assert settings.neo4j_uri == "bolt://flag:7687"
    assert settings.neo4j_username == "flag_user"
    assert settings.neo4j_database == "flag_db"


def test_apply_neo4j_overrides_leaves_env_values_when_flags_absent():
    # A None override means "flag not supplied": the env-derived value (and the
    # built-in `neo4j` database default) must survive untouched.
    settings = CLISettings(
        neo4j_uri="bolt://env:7687",
        neo4j_username="env_user",
    )

    _apply_neo4j_overrides(settings)

    assert settings.neo4j_uri == "bolt://env:7687"
    assert settings.neo4j_username == "env_user"
    assert settings.neo4j_database == "neo4j"


def test_apply_neo4j_overrides_does_not_touch_password():
    # The password is deliberately not a flag; the override helper must never
    # alter it (it is read only from NEO4J_PASSWORD).
    settings = CLISettings(neo4j_password="env_secret")  # noqa: S106

    _apply_neo4j_overrides(settings, neo4j_uri="bolt://flag:7687")

    assert settings.neo4j_password is not None
    assert settings.neo4j_password.get_secret_value() == "env_secret"


def test_run_embeddings_passes_neocarta_error_through():
    # NeocartaError subclasses are re-raised unchanged so the command's
    # cli_error_from adapter maps them to their declared exit code.
    err = EnrichmentError("provider exploded")
    embedder = MagicMock()
    embedder.run.side_effect = err

    with pytest.raises(EnrichmentError) as excinfo:
        _run_embeddings(embedder, [NodeLabel.COLUMN])

    assert excinfo.value is err
