"""Join-line injection into the SQL-gen prompt.

The graph_rag_prompt renders the ContextBundle via bundle.to_text(), so
join_lines on the bundle flows directly into the prompt text. The tests
in this module cover two orthogonal halves of the feature:

1. Rendering (the bundle → text → prompt plumbing). Exercised via direct
   ContextBundle construction with JoinLine objects.

2. Flag gating (DBXCARTA_INJECT_CRITERIA → GraphRetriever branching).
   Exercised via a stub Neo4j session so the flag's effect on which
   Cypher statements run is observable without a live driver.
"""

from __future__ import annotations

from typing import Any, Self
from unittest.mock import MagicMock

from dbxcarta.client.graph_retriever import (
    _REFERENCES_CRITERIA_CYPHER,
    GraphRetriever,
    _references_criteria,
)
from dbxcarta.client.prompt import graph_rag_prompt
from dbxcarta.client.retriever import ColumnEntry, ContextBundle, JoinLine

_PREDICATE = "orders.customer_id = customers.id"


def _bundle(predicates: list[str]) -> ContextBundle:
    return ContextBundle(
        columns=[
            ColumnEntry("cat.s.orders", "customer_id", "BIGINT"),
            ColumnEntry("cat.s.customers", "id", "BIGINT", "Primary key"),
        ],
        join_lines=[JoinLine(p) for p in predicates],
    )


def test_bundle_to_text_renders_joins_section() -> None:
    text = _bundle([_PREDICATE]).to_text()
    assert "Joins:" in text
    assert _PREDICATE in text


def test_bundle_to_text_omits_section_when_empty() -> None:
    text = _bundle([]).to_text()
    assert "Joins:" not in text
    assert _PREDICATE not in text


def test_graph_rag_prompt_contains_predicate_when_bundle_has_join_lines() -> None:
    bundle = _bundle([_PREDICATE])
    prompt = graph_rag_prompt("q", "cat", ["s"], bundle.to_text())
    assert _PREDICATE in prompt


def test_graph_rag_prompt_omits_predicate_when_bundle_empty() -> None:
    bundle = _bundle([])
    prompt = graph_rag_prompt("q", "cat", ["s"], bundle.to_text())
    assert _PREDICATE not in prompt
    assert "Joins:" not in prompt


def test_join_lines_default_empty_back_compat() -> None:
    """ContextBundle constructed without join_lines defaults to [] and to_text() is well-defined."""
    bundle = ContextBundle(columns=[ColumnEntry("c.s.t", "col", "INT")])
    assert bundle.join_lines == []
    assert "Joins:" not in bundle.to_text()


# --- Flag-gating tests via stub session -------------------------------------


class _StubRow:
    """Accepts any key access and returns a sentinel string."""

    def __getitem__(self, _key: str) -> str:
        return "stub"


class _StubSession:
    """Minimal Neo4j session stand-in that records Cypher statements.

    Every .run() returns a single row that responds to any key, so each
    retrieve() helper produces non-empty output and the downstream
    criteria-fetch path is reached when the flag is on. The important
    thing is which statements were dispatched, recorded in .statements.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    def run(self, statement: str, **_: Any) -> list[_StubRow]:
        self.statements.append(statement)
        return [_StubRow()]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _CriteriaSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def run(self, statement: str, **_: Any) -> list[dict[str, Any]]:
        assert statement == _REFERENCES_CRITERIA_CYPHER
        return self.rows


def _retriever_with_stub(inject_criteria: bool, stub: _StubSession) -> GraphRetriever:
    """Build a GraphRetriever whose driver.session() yields the stub.

    The constructor opens a real Neo4j driver, which we bypass by
    instantiating the class without __init__ and wiring the fields used by
    retrieve() directly.
    """
    settings = MagicMock()
    settings.dbxcarta_client_top_k = 1
    settings.dbxcarta_catalog = "cat"
    settings.schemas_list = []
    settings.dbxcarta_confidence_threshold = 0.8
    settings.dbxcarta_inject_criteria = inject_criteria
    settings.dbxcarta_client_max_expansion_tables = 0

    driver = MagicMock()
    driver.session.return_value = stub

    retriever = GraphRetriever.__new__(GraphRetriever)
    retriever._settings = settings
    retriever._driver = driver
    return retriever


def test_retriever_runs_criteria_cypher_when_flag_on() -> None:
    stub = _StubSession()
    retriever = _retriever_with_stub(inject_criteria=True, stub=stub)
    retriever.retrieve("q", [0.0] * 4)
    assert any(_REFERENCES_CRITERIA_CYPHER in s for s in stub.statements)


def test_retriever_skips_criteria_cypher_when_flag_off() -> None:
    stub = _StubSession()
    retriever = _retriever_with_stub(inject_criteria=False, stub=stub)
    bundle = retriever.retrieve("q", [0.0] * 4)
    assert all(_REFERENCES_CRITERIA_CYPHER not in s for s in stub.statements)
    assert bundle.join_lines == []


def test_references_criteria_uses_persisted_criteria_when_present() -> None:
    session = _CriteriaSession(
        [
            {
                "crit": _PREDICATE,
                "source_col_id": "cat.s.orders.customer_id",
                "target_col_id": "cat.s.customers.id",
                "source": "declared",
                "confidence": 1.0,
            }
        ]
    )
    lines = _references_criteria(session, ["cat.s.orders.customer_id"], 0.8)
    assert len(lines) == 1
    assert lines[0].predicate == _PREDICATE
    assert lines[0].source == "declared"
    assert lines[0].confidence == 1.0


def test_references_criteria_synthesizes_predicate_when_criteria_missing() -> None:
    session = _CriteriaSession(
        [
            {
                "crit": None,
                "source_col_id": "cat.s.orders.customer_id",
                "target_col_id": "cat.s.customers.id",
                "source": "inferred_metadata",
                "confidence": 0.91,
            }
        ]
    )
    lines = _references_criteria(session, ["cat.s.orders.customer_id"], 0.8)
    assert len(lines) == 1
    assert lines[0].predicate == "cat.s.orders.customer_id = cat.s.customers.id"
    assert lines[0].source == "inferred_metadata"
    assert lines[0].confidence == 0.91
