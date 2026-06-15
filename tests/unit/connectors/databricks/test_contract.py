"""Pure-Python tests for the graph contract derivations.

The per-label property lists are derived from the Pydantic models rather than
hand-maintained, so these tests pin the derivation (alias handling, REFERENCES
endpoint exclusion) without any Spark.
"""

from __future__ import annotations

from neocarta.connectors.databricks.contract import (
    DEFAULT_EMBEDDING_ENDPOINT,
    EMBEDDING_TEXT_EXPR,
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


def test_qualified_name_is_a_declared_property_for_node_labels():
    """Database/Schema/Table/Column carry the readable `qualified_name` path
    alongside their hashed `id`. Value nodes do not (no qualified path)."""
    for label in (NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN):
        assert "qualified_name" in NODE_PROPERTIES[label], f"{label} missing qualified_name"
    assert "qualified_name" not in NODE_PROPERTIES[NodeLabel.VALUE]


def test_schema_property_alias_surfaces_unprefixed():
    """The ``schema_`` field alias surfaces as the graph property ``schema``."""
    # Table and Column carry structural identity including the `schema` property.
    assert "schema" in NODE_PROPERTIES[NodeLabel.TABLE]
    assert "schema_" not in NODE_PROPERTIES[NodeLabel.TABLE]


def test_references_properties_exclude_join_endpoints():
    """Endpoint join keys are never stored as REFERENCES edge properties."""
    assert "source_column_id" not in REFERENCES_PROPERTIES
    assert "target_column_id" not in REFERENCES_PROPERTIES


def test_embedding_is_a_declared_property_for_every_embeddable_label():
    """Every embeddable label carries an `embedding` graph property (added by
    inline embedding or by enrichment), so the write boundary allows it. Value
    is never embedded, so it has no `embedding` property."""
    for label in set(MANAGED_NODE_LABELS) - {NodeLabel.VALUE}:
        assert "embedding" in NODE_PROPERTIES[label], f"{label} is missing `embedding`"
    assert "embedding" not in NODE_PROPERTIES[NodeLabel.VALUE]


def test_embedding_text_expr_covers_every_embeddable_label():
    """The embedding-text map defines one expression per embeddable label.

    Value is a managed label but is never embedded (no neocarta path embeds it;
    it is reached by HAS_VALUE traversal, not vector search), so it carries no
    embedding-text expression.
    """
    assert set(EMBEDDING_TEXT_EXPR) == set(MANAGED_NODE_LABELS) - {NodeLabel.VALUE}
    assert all(expr for expr in EMBEDDING_TEXT_EXPR.values())


def test_embedding_text_expr_is_never_a_graph_property():
    """`embedding_text` is transient: it must not be a declared node property."""
    for props in NODE_PROPERTIES.values():
        assert "embedding_text" not in props


def test_embedding_text_is_name_type_comment():
    """Embedding text is composed as `name | type | comment`, matching the
    shared enrichment embed path so inline and external embed the identical
    text. Only Column carries a type (`data_type`); the others are
    `name | comment`."""
    assert EMBEDDING_TEXT_EXPR[NodeLabel.TABLE] == (
        "concat_ws(' | ', name, nullif(trim(comment), ''))"
    )
    assert EMBEDDING_TEXT_EXPR[NodeLabel.COLUMN] == (
        "concat_ws(' | ', name, data_type, nullif(trim(comment), ''))"
    )
    assert EMBEDDING_TEXT_EXPR[NodeLabel.SCHEMA] == (
        "concat_ws(' | ', name, nullif(trim(comment), ''))"
    )
    # Database embeds a single scalar column. Value nodes are never embedded, so
    # they have no embedding-text expression.
    assert EMBEDDING_TEXT_EXPR[NodeLabel.DATABASE] == "name"
    assert NodeLabel.VALUE not in EMBEDDING_TEXT_EXPR


def test_default_embedding_endpoint_is_the_gte_foundation_model():
    """The inline default endpoint is the 1024-dim Databricks GTE model."""
    assert DEFAULT_EMBEDDING_ENDPOINT == "databricks-gte-large-en"
