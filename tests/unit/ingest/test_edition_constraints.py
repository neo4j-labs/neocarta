"""Characterize the edition-aware constraint behavior without a Neo4j container.

The Layer B graph goldens are node/rel-data only and therefore edition-agnostic
(generated on the Community testcontainer). The one edition delta — ``IS UNIQUE``
(Community) vs ``NODE KEY`` (Enterprise) — is characterized here by stubbing the
edition probe and recording the Cypher ``write_neo4j_constraints`` emits, so a later
refactor (S5 generic writer) that changes constraint selection is caught.
"""

from types import SimpleNamespace

import pytest

from neocarta.enums import NodeLabel
from neocarta.ingest.rdbms.constraints import KEY_CONSTRAINTS_LOOKUP, UNIQUE_CONSTRAINTS_LOOKUP
from neocarta.ingest.utils import write_neo4j_constraints

_LABELS = [
    NodeLabel.DATABASE,
    NodeLabel.SCHEMA,
    NodeLabel.TABLE,
    NodeLabel.COLUMN,
    NodeLabel.VALUE,
]


class _RecordingDriver:
    """A minimal Neo4j driver double that records the Cypher it is asked to write."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute_query(self, query_: str, **_kwargs: object) -> tuple:
        self.queries.append(query_)
        return ([], SimpleNamespace(counters=SimpleNamespace()), [])


def test_community_edition_emits_unique_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Community database gets ``IS UNIQUE`` constraints, one per node label."""
    monkeypatch.setattr("neocarta.ingest.utils.is_enterprise_edition", lambda *_a, **_k: False)
    driver = _RecordingDriver()

    write_neo4j_constraints(driver, _LABELS, KEY_CONSTRAINTS_LOOKUP, UNIQUE_CONSTRAINTS_LOOKUP)

    assert driver.queries == [UNIQUE_CONSTRAINTS_LOOKUP[label] for label in _LABELS]
    assert all("IS UNIQUE" in query for query in driver.queries)
    assert not any("NODE KEY" in query for query in driver.queries)


def test_enterprise_edition_emits_node_key_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    """An Enterprise database gets ``NODE KEY`` constraints, one per node label."""
    monkeypatch.setattr("neocarta.ingest.utils.is_enterprise_edition", lambda *_a, **_k: True)
    driver = _RecordingDriver()

    write_neo4j_constraints(driver, _LABELS, KEY_CONSTRAINTS_LOOKUP, UNIQUE_CONSTRAINTS_LOOKUP)

    assert driver.queries == [KEY_CONSTRAINTS_LOOKUP[label] for label in _LABELS]
    assert all("NODE KEY" in query for query in driver.queries)
