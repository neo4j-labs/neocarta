"""Unit tests for LiteLLMEmbeddingsConnector dimension handling (issue #187).

``dimensions`` is a first-class argument. It is sent to the provider; if the
model rejects it (LiteLLM raises ``UnsupportedParamsError`` and does NOT honor
per-call ``drop_params`` on the embeddings path), the connector drops it and
retries with the native dimension. Because the dimension is always probed first,
the Neo4j vector index ends up matching the vectors actually returned.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector

_EMBED = "neocarta.enrichment.embeddings.litellm_embeddings.litellm.embedding"


def test_dimensions_none_leaves_call_kwargs_clean():
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock())
    assert "dimensions" not in connector._call_kwargs
    assert connector.dimensions is None  # probed on first use


def test_dimensions_set_injects_dimensions():
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock(), dimensions=256)
    assert connector._call_kwargs["dimensions"] == 256
    # No drop_params: it is not honored on the embeddings path (handled by retry).
    assert "drop_params" not in connector._call_kwargs
    # Still probed on first use, so a dropped (unsupported) value is reflected by
    # the probe rather than trusted as-is.
    assert connector.dimensions is None


def test_litellm_kwargs_take_precedence_over_dimensions():
    connector = LiteLLMEmbeddingsConnector(
        neo4j_driver=MagicMock(),
        dimensions=256,
        litellm_kwargs={"dimensions": 512},
    )
    assert connector._call_kwargs["dimensions"] == 512


def test_dimensions_forwarded_to_litellm_call():
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock(), dimensions=256)
    fake_response = SimpleNamespace(data=[{"index": 0, "embedding": [0.1, 0.2]}])
    with patch(_EMBED, return_value=fake_response) as mock_embed:
        connector._create_embedding_sync("hello")
    assert mock_embed.call_args.kwargs["dimensions"] == 256


def test_unsupported_dimensions_dropped_and_retried():
    # A model that can't truncate makes LiteLLM raise; the connector must drop
    # 'dimensions' and retry (permanently), returning the native-size vector.
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock(), dimensions=256)
    calls = []

    def fake(model, **kwargs):
        calls.append(dict(kwargs))
        if "dimensions" in kwargs:
            raise RuntimeError("Setting dimensions is not supported for this model")
        return SimpleNamespace(data=[{"index": 0, "embedding": [0.1, 0.2, 0.3]}])

    with patch(_EMBED, side_effect=fake):
        vector = connector._create_embedding_sync("hello")

    assert vector == [0.1, 0.2, 0.3]  # native vector, from the retry
    assert len(calls) == 2  # first attempt with dims (rejected), retry without
    assert "dimensions" in calls[0]  # first attempt carried the requested dim
    assert "dimensions" not in calls[1]  # retry dropped it
    assert "dimensions" not in connector._call_kwargs  # permanently dropped


def test_non_dimensions_error_is_not_retried():
    # A genuine failure (e.g. bad credentials) must NOT be retried as a
    # dimensions drop; the single-embedding path returns None after one attempt.
    connector = LiteLLMEmbeddingsConnector(neo4j_driver=MagicMock(), dimensions=256)
    calls = []

    def fake(model, **kwargs):
        calls.append(1)
        raise RuntimeError("AuthenticationError: invalid api key")

    with patch(_EMBED, side_effect=fake):
        vector = connector._create_embedding_sync("hello")

    assert vector is None
    assert len(calls) == 1  # no retry for non-dimensions errors
    assert connector._call_kwargs["dimensions"] == 256  # left intact
