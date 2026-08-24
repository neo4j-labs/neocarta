"""Tests for the shared graph-schema enums."""

from neocarta.enums import NodeLabel, RelationshipType


def test_lpg_node_labels_exist():
    assert NodeLabel.NODE == "Node"
    assert NodeLabel.RELATIONSHIP == "Relationship"
    assert NodeLabel.PROPERTY == "Property"


def test_lpg_relationship_types_exist():
    assert RelationshipType.HAS_NODE == "HAS_NODE"
    assert RelationshipType.HAS_RELATIONSHIP == "HAS_RELATIONSHIP"
    assert RelationshipType.HAS_SOURCE_NODE == "HAS_SOURCE_NODE"
    assert RelationshipType.HAS_TARGET_NODE == "HAS_TARGET_NODE"
    assert RelationshipType.HAS_PROPERTY == "HAS_PROPERTY"
