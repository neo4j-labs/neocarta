"""Driving tests for the governance relationship loaders.

Unlike ``test_governance_queries.py`` (which exercises the shared query *builder*
in isolation), these construct a real :class:`Neo4jRDBMSLoader` with a mock driver,
call each governance relationship loader, and assert the Cypher the loader actually
builds references only ``row.<field>`` tokens that exist on the relationship
model's ``model_dump()``. A mismatched id-column string would MATCH a missing row
key and silently write zero edges; driving the loaders through the models makes
that a hard failure instead of a silent one.
"""

import re
from unittest.mock import MagicMock

import pytest

from neocarta.data_model.governance import (
    GovernanceTagValue,
    HasDefinition,
    HasValueOption,
    TaggedWithGovernanceTag,
)
from neocarta.enums import NodeLabel
from neocarta.ingest.indexes import create_vector_index
from neocarta.ingest.rdbms import Neo4jRDBMSLoader


def _loader_capturing() -> tuple[Neo4jRDBMSLoader, list[str]]:
    """A loader whose mock driver records every Cypher string passed to it."""
    captured: list[str] = []
    driver = MagicMock()

    def _exec(*_args, query_=None, parameters_=None, **_kwargs):
        captured.append(query_)
        return (None, MagicMock(), None)  # (_, summary, _) for _run_write's unpack

    driver.execute_query.side_effect = _exec
    return Neo4jRDBMSLoader(driver, "neo4j"), captured


def _merge_query(captured: list[str]) -> str:
    """The relationship MERGE query (relationship loaders write no constraints/indexes)."""
    return next(q for q in captured if q and "MERGE (n1)" in q)


def _row_tokens(cypher: str) -> set[str]:
    return set(re.findall(r"row\.(\w+)", cypher))


def test_has_value_option_loader_columns_match_model():
    loader, captured = _loader_capturing()
    rel = HasValueOption(governance_tag_key_id="k", governance_tag_value_id="v")
    loader.load_has_value_option_relationships([rel])
    q = _merge_query(captured)
    assert "(n1:GovernanceTagKey {id: row.governance_tag_key_id})" in q
    assert "(n2:GovernanceTagValue {id: row.governance_tag_value_id})" in q
    assert "[r:HAS_VALUE_OPTION]" in q
    # No column references a field the model does not emit (catches a silent-zero-edge typo).
    assert _row_tokens(q) <= set(rel.model_dump())


def test_has_definition_loader_columns_match_model():
    loader, captured = _loader_capturing()
    rel = HasDefinition(governance_tag_id="g", governance_tag_value_id="v")
    loader.load_has_definition_relationships([rel])
    q = _merge_query(captured)
    assert "(n1:GovernanceTag {id: row.governance_tag_id})" in q
    assert "(n2:GovernanceTagValue {id: row.governance_tag_value_id})" in q
    assert "[r:HAS_DEFINITION]" in q
    assert _row_tokens(q) <= set(rel.model_dump())


@pytest.mark.parametrize(
    ("loader_method", "label"),
    [
        ("load_column_tagged_with_governance_tag_relationships", "Column"),
        ("load_table_tagged_with_governance_tag_relationships", "Table"),
        ("load_schema_tagged_with_governance_tag_relationships", "Schema"),
    ],
)
def test_tagged_with_governance_tag_loaders_columns_match_model(loader_method, label):
    loader, captured = _loader_capturing()
    rel = TaggedWithGovernanceTag(source_label=label, source_id="s", governance_tag_id="g")
    getattr(loader, loader_method)([rel])
    q = _merge_query(captured)
    assert f"(n1:{label} {{id: row.source_id}})" in q
    assert "(n2:GovernanceTag {id: row.governance_tag_id})" in q
    assert "[r:TAGGED_WITH]" in q
    assert _row_tokens(q) <= set(rel.model_dump())


def test_governance_tag_value_node_default_is_name_only():
    """The value-node loader defaults to name-only — values are bare on most platforms,
    so the default must not write a NULL description (connector contract)."""
    loader, captured = _loader_capturing()
    loader.load_governance_tag_value_nodes([GovernanceTagValue(id="s.k.h", name="pii")])
    merge = next(q for q in captured if q and "MERGE (n:GovernanceTagValue" in q)
    assert "n.name = row.name" in merge
    assert "description" not in merge


def test_create_vector_index_for_governance_tag_key():
    """The --embeddings path's vector index targets GovernanceTagKey.embedding (backs vector search)."""
    driver = MagicMock()
    driver.execute_query.return_value = (None, MagicMock(), None)  # (_, summary, _) unpack
    create_vector_index(
        driver, NodeLabel.GOVERNANCE_TAG_KEY, dimensions=1536, database_name="neo4j"
    )
    q = driver.execute_query.call_args.kwargs["query_"]
    assert "governancetagkey_vector_index" in q
    assert "FOR (n:GovernanceTagKey)" in q
    assert "ON n.embedding" in q
    assert "`vector.dimensions`: 1536" in q
