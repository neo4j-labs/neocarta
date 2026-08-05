"""Unit tests for the Neo4j schema transformer."""

import pandas as pd

from neocarta.connectors.neo4j.schema.transform import Neo4jSchemaTransformer
from neocarta.enums import NodeLabel


def _seed(transformer, node_labels):
    transformer.transform_to_node_nodes(
        pd.DataFrame(node_labels), source_name="dbms", source_database="neo4j"
    )


def test_one_node_per_label_no_additional_labels():
    t = Neo4jSchemaTransformer()
    _seed(t, [{"label": "Person"}, {"label": "Employee"}])
    assert len({n.id for n in t.node_nodes}) == 2
    assert all(n.additional_labels is None for n in t.node_nodes)


def test_node_id_preserves_label_case():
    t = Neo4jSchemaTransformer()
    _seed(t, [{"label": "Person"}])
    # Neo4j labels are case-sensitive, so the id keeps the label verbatim.
    assert t.node_nodes[0].id == "dbms.neo4j.Person"


def test_property_flags_and_nullable_from_existence():
    t = Neo4jSchemaTransformer()
    node_props = pd.DataFrame(
        [
            {
                "label": "Person",
                "property": "email",
                "type": "STRING",
                "unique": True,
                "indexed": True,
                "existence": True,
            }
        ]
    )
    t.transform_to_property_nodes(
        node_props, pd.DataFrame(), source_name="dbms", source_database="neo4j"
    )
    prop = t.property_nodes[0]
    assert prop.id == "dbms.neo4j.Person.email"
    assert prop.unique is True
    assert prop.indexed is True
    assert prop.existence is True
    assert prop.nullable is False


def test_build_all_excludes_property_when_filtered(extractor_with_cache):
    t = Neo4jSchemaTransformer()
    t.build_all(
        extractor_with_cache,
        source_name="dbms",
        source_database="neo4j",
        include_nodes=[NodeLabel.NODE, NodeLabel.RELATIONSHIP],
    )
    assert t.node_nodes  # NODE included
    assert t.property_nodes == []  # PROPERTY excluded
    assert t.node_has_property_relationships == []


def _full_extractor():
    from types import SimpleNamespace

    return SimpleNamespace(
        database_info=pd.DataFrame([{"source_name": "dbms"}]),
        schema_info=pd.DataFrame([{"source_name": "dbms", "database": "neo4j"}]),
        node_info=pd.DataFrame([{"label": "Person"}]),
        relationship_info=pd.DataFrame([{"type": "KNOWS"}]),
        node_property_info=pd.DataFrame(
            [
                {
                    "label": "Person",
                    "property": "name",
                    "type": "STRING",
                    "unique": False,
                    "indexed": False,
                    "existence": False,
                }
            ]
        ),
        relationship_property_info=pd.DataFrame(
            [
                {
                    "rel_type": "KNOWS",
                    "property": "since",
                    "type": "INTEGER",
                    "unique": False,
                    "indexed": False,
                    "existence": False,
                }
            ]
        ),
        relationship_endpoint_info=pd.DataFrame(
            [{"type": "KNOWS", "source_label": "Person", "target_label": "Person"}]
        ),
    )


def test_property_only_filter_has_no_owners():
    t = Neo4jSchemaTransformer()
    t.build_all(
        _full_extractor(),
        source_name="dbms",
        source_database="neo4j",
        include_nodes=[NodeLabel.PROPERTY],
    )
    assert t.property_nodes == []
    assert t.node_has_property_relationships == []
    assert t.relationship_has_property_relationships == []


def test_node_property_filter_excludes_relationship_owned_props():
    t = Neo4jSchemaTransformer()
    t.build_all(
        _full_extractor(),
        source_name="dbms",
        source_database="neo4j",
        include_nodes=[NodeLabel.NODE, NodeLabel.PROPERTY],
    )
    assert [p.name for p in t.property_nodes] == ["name"]  # node-owned only
    assert t.node_has_property_relationships
    assert t.relationship_has_property_relationships == []


def test_relationship_property_filter_excludes_node_owned_props():
    t = Neo4jSchemaTransformer()
    t.build_all(
        _full_extractor(),
        source_name="dbms",
        source_database="neo4j",
        include_nodes=[NodeLabel.RELATIONSHIP, NodeLabel.PROPERTY],
    )
    assert [p.name for p in t.property_nodes] == ["since"]  # rel-owned only
    assert t.relationship_has_property_relationships
    assert t.node_has_property_relationships == []


def test_repeated_run_resets_stale_caches():
    t = Neo4jSchemaTransformer()
    t.build_all(_full_extractor(), source_name="dbms", source_database="neo4j")  # full run
    assert t.node_nodes
    assert t.relationship_nodes
    assert t.property_nodes
    # second run keeps only the roots -> earlier lists must not persist
    t.build_all(_full_extractor(), source_name="dbms", source_database="neo4j", include_nodes=[])
    assert t.node_nodes == []
    assert t.relationship_nodes == []
    assert t.property_nodes == []
    assert t.has_node_relationships == []
    assert t.node_has_property_relationships == []
