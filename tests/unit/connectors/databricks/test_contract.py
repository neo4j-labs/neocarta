"""Pure-Python tests for the graph contract derivations.

The per-label property lists are derived from the Pydantic models rather than
hand-maintained, so these tests pin the derivation (alias handling, REFERENCES
endpoint exclusion) without any Spark.
"""

from __future__ import annotations

from neocarta.connectors.databricks.contract import (
    MANAGED_NODE_LABELS,
    MANAGED_REL_TYPES,
    NODE_PROPERTIES,
    REFERENCES_PROPERTIES,
)
from neocarta.enums import NodeLabel
from neocarta.enums import RelationshipType as RelType


def test_managed_node_labels_are_the_rdbms_subset():
    """The connector manages exactly Database/Schema/Table/Column/Value."""
    assert MANAGED_NODE_LABELS == (
        NodeLabel.DATABASE,
        NodeLabel.SCHEMA,
        NodeLabel.TABLE,
        NodeLabel.COLUMN,
        NodeLabel.VALUE,
    )


def test_managed_rel_types_cover_structure_and_references():
    """HAS_* structural edges plus REFERENCES are managed."""
    assert set(MANAGED_REL_TYPES) == {
        RelType.HAS_SCHEMA,
        RelType.HAS_TABLE,
        RelType.HAS_COLUMN,
        RelType.HAS_VALUE,
        RelType.REFERENCES,
    }


def test_node_properties_declared_for_every_managed_label():
    """Every managed label has a non-empty derived property tuple."""
    for label in MANAGED_NODE_LABELS:
        assert label in NODE_PROPERTIES
        assert NODE_PROPERTIES[label], f"{label} has no graph properties"


def test_schema_property_alias_surfaces_unprefixed():
    """The ``schema_`` field alias surfaces as the graph property ``schema``."""
    # Table and Column carry structural identity including the `schema` property.
    assert "schema" in NODE_PROPERTIES[NodeLabel.TABLE]
    assert "schema_" not in NODE_PROPERTIES[NodeLabel.TABLE]


def test_references_properties_exclude_join_endpoints():
    """Endpoint join keys are never stored as REFERENCES edge properties."""
    assert "source_column_id" not in REFERENCES_PROPERTIES
    assert "target_column_id" not in REFERENCES_PROPERTIES
