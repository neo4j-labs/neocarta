"""Unit tests for the Neo4j schema extractor."""

import pytest

from neocarta.connectors.neo4j.schema.extract import Neo4jSchemaExtractor, _flatten_schema
from neocarta.warnings import Neo4jSchemaWarning


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


def test_flatten_schema_skips_non_dict_entry():
    cache: dict = {}
    with pytest.warns(Neo4jSchemaWarning):
        _flatten_schema({"Bad": "not-a-dict"}, cache)
    assert cache["node_info"].empty
    assert cache["relationship_info"].empty


def test_flatten_schema_skips_non_dict_property_meta():
    schema_map = {
        "Person": {"type": "node", "properties": {"bad": "oops", "ok": {"type": "STRING"}}}
    }
    cache: dict = {}
    with pytest.warns(Neo4jSchemaWarning):
        _flatten_schema(schema_map, cache)
    assert list(cache["node_info"]["label"]) == ["Person"]
    assert list(cache["node_property_info"]["property"]) == ["ok"]  # "bad" skipped


def test_flatten_schema_skips_non_dict_relationships():
    schema_map = {"Person": {"type": "node", "relationships": "bad"}}
    cache: dict = {}
    with pytest.warns(Neo4jSchemaWarning):
        _flatten_schema(schema_map, cache)
    assert list(cache["node_info"]["label"]) == ["Person"]
    assert cache["relationship_endpoint_info"].empty


def test_flatten_schema_skips_neocarta_metadata_label():
    schema_map = {
        "__neocarta_graph__": {"type": "node", "properties": {"latest_version": {"type": "STRING"}}},
        "Person": {"type": "node"},
    }
    cache: dict = {}
    _flatten_schema(schema_map, cache)
    assert list(cache["node_info"]["label"]) == ["Person"]  # metadata singleton excluded
