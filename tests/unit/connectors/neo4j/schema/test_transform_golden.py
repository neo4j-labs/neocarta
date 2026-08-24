"""Layer A characterization: Neo4j schema transform-level output (no Docker).

Golden-masters the LPG node/relationship lists ``Neo4jSchemaTransformer`` produces
from the shared APOC-shaped extractor cache. Regenerate with ``UPDATE_GOLDENS=1``.
"""

from pathlib import Path

import pytest

from neocarta.connectors.neo4j.schema.transform import Neo4jSchemaTransformer
from tests.support.characterization import assert_matches_golden, serialize_transform

_GOLDEN = Path(__file__).parent / "golden" / "neo4j_schema_transform.json"


def _output(extractor_with_cache) -> dict:
    """Drive the transformer exactly as the connector does, then serialize its output."""
    transformer = Neo4jSchemaTransformer()
    transformer.build_all(extractor_with_cache, source_name="dbms", source_database="neo4j")
    return serialize_transform(transformer)


def test_neo4j_schema_transform_output_matches_golden(extractor_with_cache) -> None:
    """Current Neo4j schema transform output matches the committed golden."""
    assert_matches_golden(_GOLDEN, _output(extractor_with_cache))


def test_golden_detects_injected_change(extractor_with_cache, monkeypatch) -> None:
    """An injected node-id change makes the comparison fail -- the golden catches regressions."""
    monkeypatch.setattr(
        "neocarta.connectors.neo4j.schema.transform.generate_node_id",
        lambda *_args, **_kwargs: "collapsed",
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(_GOLDEN, _output(extractor_with_cache), update=False)
