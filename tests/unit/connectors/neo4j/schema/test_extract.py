"""Unit tests for the Neo4j schema extractor."""

from neocarta.connectors.neo4j.schema.extract import Neo4jSchemaExtractor, _flatten_schema


def test_property_accessors_return_cached_frames(extractor_with_cache):
    assert extractor_with_cache.node_info.iloc[0]["label"] == "Person"
    assert extractor_with_cache.relationship_info.iloc[0]["type"] == "KNOWS"


def test_absent_cache_returns_empty_frame():
    ext = Neo4jSchemaExtractor(source_neo4j_driver=None, source_name="dbms")
    assert ext.node_info.empty


def test_flatten_schema_builds_frames():
    schema_map = {
        "Person": {
            "type": "node",
            "properties": {
                "email": {"type": "STRING", "unique": True, "indexed": True, "existence": False},
            },
            "relationships": {"KNOWS": {"direction": "out", "labels": ["Person"]}},
        },
        "KNOWS": {"type": "relationship", "properties": {"since": {"type": "INTEGER"}}},
    }
    cache: dict = {}
    _flatten_schema(schema_map, cache)
    assert list(cache["node_info"]["label"]) == ["Person"]
    assert list(cache["relationship_info"]["type"]) == ["KNOWS"]
    prop = cache["node_property_info"].iloc[0]
    assert prop["property"] == "email"
    assert bool(prop["unique"]) is True
    ep = cache["relationship_endpoint_info"].iloc[0]
    assert ep["type"] == "KNOWS"
    assert ep["source_label"] == "Person"
    assert ep["target_label"] == "Person"
