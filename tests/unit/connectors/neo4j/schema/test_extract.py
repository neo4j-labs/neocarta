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
        "__neocarta_graph__": {
            "type": "node",
            "properties": {"latest_version": {"type": "STRING"}},
        },
        "Person": {"type": "node"},
    }
    cache: dict = {}
    with pytest.warns(Neo4jSchemaWarning, match="reserved LPG node label"):
        _flatten_schema(schema_map, cache)
    assert list(cache["node_info"]["label"]) == ["Person"]  # metadata singleton excluded


def test_flatten_schema_excludes_reserved_lpg_vocabulary():
    """A same-database re-ingest of neocarta's own output keeps only genuine source schema."""
    # What apoc.meta.schema() reports after neocarta has written its LPG metadata into
    # the same database that holds a genuine ``Person``/``KNOWS`` source graph.
    schema_map = {
        "__neocarta_graph__": {
            "type": "node",
            "properties": {"latest_version": {"type": "STRING"}},
        },
        "Database": {
            "type": "node",
            "relationships": {"HAS_SCHEMA": {"direction": "out", "labels": ["Schema"]}},
        },
        "Schema": {
            "type": "node",
            "relationships": {"HAS_NODE": {"direction": "out", "labels": ["Node"]}},
        },
        "Node": {
            "type": "node",
            "relationships": {"HAS_PROPERTY": {"direction": "out", "labels": ["Property"]}},
        },
        "Relationship": {"type": "node"},
        "Property": {"type": "node"},
        "HAS_SCHEMA": {"type": "relationship", "properties": {}},
        "HAS_NODE": {"type": "relationship", "properties": {}},
        "HAS_RELATIONSHIP": {"type": "relationship", "properties": {}},
        "HAS_SOURCE_NODE": {"type": "relationship", "properties": {}},
        "HAS_TARGET_NODE": {"type": "relationship", "properties": {}},
        "HAS_PROPERTY": {"type": "relationship", "properties": {}},
        "Person": {
            "type": "node",
            "properties": {"name": {"type": "STRING"}},
            "relationships": {"KNOWS": {"direction": "out", "labels": ["Person"]}},
        },
        "KNOWS": {"type": "relationship", "properties": {}},
    }
    cache: dict = {}
    with pytest.warns(Neo4jSchemaWarning):
        _flatten_schema(schema_map, cache)

    # Only the genuine source schema survives — none of neocarta's own vocabulary.
    assert list(cache["node_info"]["label"]) == ["Person"]
    assert list(cache["relationship_info"]["type"]) == ["KNOWS"]
    assert list(cache["node_property_info"]["label"].unique()) == ["Person"]
    ep = cache["relationship_endpoint_info"]
    assert list(ep["type"]) == ["KNOWS"]


def test_flatten_schema_drops_endpoints_touching_reserved_vocabulary():
    """Genuine nodes that point at a reserved label or via a reserved type are dropped."""
    schema_map = {
        "Person": {
            "type": "node",
            "relationships": {
                # genuine relationship whose endpoint is a reserved-label node
                "OWNS": {"direction": "out", "labels": ["Database"]},
                # genuine endpoint using a reserved relationship type
                "HAS_NODE": {"direction": "out", "labels": ["Person"]},
                # genuine, fully non-reserved edge — this one survives
                "KNOWS": {"direction": "out", "labels": ["Person"]},
            },
        },
        "Database": {"type": "node"},  # reserved label present (shared database)
    }
    cache: dict = {}
    with pytest.warns(Neo4jSchemaWarning, match="reserved LPG node label"):
        _flatten_schema(schema_map, cache)

    assert list(cache["node_info"]["label"]) == ["Person"]
    assert list(cache["relationship_endpoint_info"]["type"]) == ["KNOWS"]
