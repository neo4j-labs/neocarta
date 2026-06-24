"""Query-shape tests for the governance-tag loader Cypher.

Mirrors ``tests/unit/connectors/test_loader.py``: it pins the exact Cypher the
governance node/relationship loaders build from the shared query helpers, so the
node labels, relationship types, and id-column names stay wired correctly. The
loader methods are exercised end-to-end (with real writes) in the connector
integration test.
"""

from neocarta.enums import NodeLabel, RelationshipType
from neocarta.ingest.utils import (
    _build_node_ingest_query,
    _build_relationship_ingest_query,
)


def test_governance_tag_key_node_query():
    query = _build_node_ingest_query(NodeLabel.GOVERNANCE_TAG_KEY, False, ["name", "description"])
    assert (
        query
        == """
UNWIND $rows as row
MERGE (n:GovernanceTagKey {id: row.id})
ON CREATE
    SET n.name = row.name,
        n.description = row.description"""
    )


def test_governance_tag_value_node_query_name_only():
    query = _build_node_ingest_query(NodeLabel.GOVERNANCE_TAG_VALUE, False, ["name"])
    assert (
        query
        == """
UNWIND $rows as row
MERGE (n:GovernanceTagValue {id: row.id})
ON CREATE
    SET n.name = row.name"""
    )


def test_has_value_option_relationship_query():
    query = _build_relationship_ingest_query(
        RelationshipType.HAS_VALUE_OPTION,
        NodeLabel.GOVERNANCE_TAG_KEY,
        NodeLabel.GOVERNANCE_TAG_VALUE,
        "governance_tag_key_id",
        "governance_tag_value_id",
        False,
        [],
    )
    assert (
        query
        == """
UNWIND $rows as row
MATCH (n1:GovernanceTagKey {id: row.governance_tag_key_id})
MATCH (n2:GovernanceTagValue {id: row.governance_tag_value_id})
MERGE (n1)-[r:HAS_VALUE_OPTION]->(n2)"""
    )


def test_has_definition_relationship_query():
    query = _build_relationship_ingest_query(
        RelationshipType.HAS_DEFINITION,
        NodeLabel.GOVERNANCE_TAG,
        NodeLabel.GOVERNANCE_TAG_VALUE,
        "governance_tag_id",
        "governance_tag_value_id",
        False,
        [],
    )
    assert (
        query
        == """
UNWIND $rows as row
MATCH (n1:GovernanceTag {id: row.governance_tag_id})
MATCH (n2:GovernanceTagValue {id: row.governance_tag_value_id})
MERGE (n1)-[r:HAS_DEFINITION]->(n2)"""
    )


def test_column_tagged_with_governance_tag_relationship_query():
    query = _build_relationship_ingest_query(
        RelationshipType.TAGGED_WITH,
        NodeLabel.COLUMN,
        NodeLabel.GOVERNANCE_TAG,
        "source_id",
        "governance_tag_id",
        False,
        [],
    )
    assert (
        query
        == """
UNWIND $rows as row
MATCH (n1:Column {id: row.source_id})
MATCH (n2:GovernanceTag {id: row.governance_tag_id})
MERGE (n1)-[r:TAGGED_WITH]->(n2)"""
    )
