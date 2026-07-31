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


def test_node_id_normalized_from_label():
    t = Neo4jSchemaTransformer()
    _seed(t, [{"label": "Person"}])
    assert t.node_nodes[0].id == "dbms.neo4j.person"


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
    assert prop.id == "dbms.neo4j.person.email"
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
