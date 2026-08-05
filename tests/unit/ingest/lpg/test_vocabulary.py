"""Tests for the reserved LPG vocabulary the Neo4j connector excludes."""

from neocarta.enums import NodeLabel, RelationshipType
from neocarta.ingest.lpg import RESERVED_NODE_LABELS, RESERVED_RELATIONSHIP_TYPES


def test_reserved_node_labels_are_the_lpg_labels_plus_metadata_singleton():
    assert {
        NodeLabel.DATABASE,
        NodeLabel.SCHEMA,
        NodeLabel.NODE,
        NodeLabel.RELATIONSHIP,
        NodeLabel.PROPERTY,
        NodeLabel.NEOCARTA_GRAPH,
    } == RESERVED_NODE_LABELS


def test_reserved_relationship_types_are_the_lpg_edge_types():
    assert {
        RelationshipType.HAS_SCHEMA,
        RelationshipType.HAS_NODE,
        RelationshipType.HAS_RELATIONSHIP,
        RelationshipType.HAS_SOURCE_NODE,
        RelationshipType.HAS_TARGET_NODE,
        RelationshipType.HAS_PROPERTY,
    } == RESERVED_RELATIONSHIP_TYPES


def test_reserved_sets_do_not_over_reserve_rdbms_vocabulary():
    # A genuine source graph's Table/Column labels or HAS_TABLE edges must not be reserved.
    assert NodeLabel.TABLE not in RESERVED_NODE_LABELS
    assert NodeLabel.COLUMN not in RESERVED_NODE_LABELS
    assert RelationshipType.HAS_TABLE not in RESERVED_RELATIONSHIP_TYPES


def test_reserved_sets_are_immutable():
    assert isinstance(RESERVED_NODE_LABELS, frozenset)
    assert isinstance(RESERVED_RELATIONSHIP_TYPES, frozenset)
