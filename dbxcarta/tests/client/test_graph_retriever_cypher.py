"""Regression guard for OPTIONAL MATCH on REFERENCES in GraphRetriever.

The REFERENCES lookup must use OPTIONAL MATCH so that deployments with no
REFERENCES edges in the graph do not trigger Neo4j's 01N51
UnknownRelationshipTypeWarning.

The relationship is bound as `[r:REFERENCES]` to filter on r.confidence;
the regex tolerates an optional binding identifier so this guard continues
to protect the OPTIONAL-MATCH invariant.
"""

from __future__ import annotations

import re

from dbxcarta.client.graph_retriever import (
    _JOIN_COLUMN_IDS_CYPHER,
    _REFERENCES_CRITERIA_CYPHER,
    _REFERENCES_TABLE_IDS_CYPHER,
)

# A MATCH clause on [:REFERENCES] or [r:REFERENCES] that is NOT preceded
# by OPTIONAL. (?<!OPTIONAL ) is a fixed-width negative lookbehind.
_WARNING_PATTERN = re.compile(r"(?<!OPTIONAL )\bMATCH\b[^\n]*\[\w*:REFERENCES\]")

# The non-OPTIONAL form of the REFERENCES query. Embedded here so that if the
# implementation ever regresses to this shape, the regex test catches it.
_PRE_CHANGE_CYPHER = (
    "UNWIND $col_ids AS cid "
    "MATCH (c:Column {id: cid})-[:REFERENCES]-(other:Column) "
    "MATCH (other)<-[:HAS_COLUMN]-(t:Table) "
    "RETURN DISTINCT t.id AS tid"
)


def test_pre_change_cypher_triggers_warning_pattern() -> None:
    assert _WARNING_PATTERN.search(_PRE_CHANGE_CYPHER) is not None


def test_post_change_cypher_does_not_trigger_warning_pattern() -> None:
    assert _WARNING_PATTERN.search(_REFERENCES_TABLE_IDS_CYPHER) is None


def test_post_change_cypher_uses_optional_match_on_references() -> None:
    assert "OPTIONAL MATCH" in _REFERENCES_TABLE_IDS_CYPHER
    assert ":REFERENCES]" in _REFERENCES_TABLE_IDS_CYPHER


def test_criteria_cypher_does_not_trigger_warning_pattern() -> None:
    """The criteria Cypher also queries REFERENCES for join-predicate fetch.

    The 01N51 warning triggers per-match-clause, so it must also use OPTIONAL MATCH.
    """
    assert _WARNING_PATTERN.search(_REFERENCES_CRITERIA_CYPHER) is None
    assert "OPTIONAL MATCH" in _REFERENCES_CRITERIA_CYPHER


def test_join_column_ids_cypher_does_not_trigger_warning_pattern() -> None:
    """_JOIN_COLUMN_IDS_CYPHER also traverses REFERENCES to find value-fetch targets."""
    assert _WARNING_PATTERN.search(_JOIN_COLUMN_IDS_CYPHER) is None
    assert "OPTIONAL MATCH" in _JOIN_COLUMN_IDS_CYPHER
