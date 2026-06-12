"""Unit tests for LiteLLMEmbeddingsConnector dimension / drop_params handling.

These cover issue #187: ``dimensions`` is a first-class argument that is sent to
LiteLLM with ``drop_params=True`` so models that don't support truncation ignore
it gracefully, while the dimension is still probed (never trusted blindly) so the
vector index matches the vectors actually returned.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def test_dimensions_none_leaves_call_kwargs_clean():
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock())
    assert "dimensions" not in connector._call_kwargs
    assert "drop_params" not in connector._call_kwargs
    # Unset so it is probed on first use.
    assert connector.dimensions is None


def test_dimensions_set_injects_dimensions_and_drop_params():
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock(), dimensions=256)
    assert connector._call_kwargs["dimensions"] == 256
    assert connector._call_kwargs["drop_params"] is True
    # Still probed on first use, so a dropped (unsupported) value is reflected by
    # the probe rather than trusted as-is.
    assert connector.dimensions is None


def test_litellm_kwargs_take_precedence_over_dimensions():
    connector = LiteLLMEmbeddingsConnector(
        neo4j_driver=MagicMock(),
        dimensions=256,
        litellm_kwargs={"dimensions": 512, "drop_params": False},
    )
    assert connector._call_kwargs["dimensions"] == 512
    assert connector._call_kwargs["drop_params"] is False


def test_dimensions_forwarded_to_litellm_call():
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock(), dimensions=256)
    fake_response = SimpleNamespace(data=[{"index": 0, "embedding": [0.1, 0.2]}])
    with patch(
        "neocarta.enrichment.embeddings.litellm_embeddings.litellm.embedding",
        return_value=fake_response,
    ) as mock_embed:
        connector._create_embedding_sync("hello")

    kwargs = mock_embed.call_args.kwargs
    assert kwargs["dimensions"] == 256
    assert kwargs["drop_params"] is True


def test_unsupported_dimensions_does_not_raise_when_litellm_drops_it():
    # drop_params=True means LiteLLM drops the unsupported param and still returns
    # a (native-size) vector — the connector must surface it, not error.
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock(), dimensions=99999)
    fake_response = SimpleNamespace(data=[{"index": 0, "embedding": [0.1, 0.2, 0.3]}])
    with patch(
        "neocarta.enrichment.embeddings.litellm_embeddings.litellm.embedding",
        return_value=fake_response,
    ):
        vector = connector._create_embedding_sync("hello")

    assert vector == [0.1, 0.2, 0.3]
