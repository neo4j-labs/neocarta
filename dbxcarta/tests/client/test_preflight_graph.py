"""Phase 4 stage precondition: Client confirms Ingest populated the graph.

Two contracts are covered:
  - the graph check is gated on a graph-consuming arm (graph_rag / schema_dump)
    being active, so a reference-only run does not newly require a graph;
  - ``_assert_graph_populated`` fails loudly when the graph has no Table nodes
    and passes when it does.
"""

from __future__ import annotations

from typing import Self

import pytest
from dbxcarta.client.eval import run
from dbxcarta.client.settings import ClientSettings

_BASE_SETTINGS: dict[str, str] = {
    "dbxcarta_catalog": "finance",
    "databricks_warehouse_id": "wh-123",
    "databricks_secret_scope": "dbxcarta-neo4j-finance",
    "dbxcarta_summary_volume": "/Volumes/finance/default/vol/summaries",
    "dbxcarta_summary_table": "finance.default.summary",
    "databricks_volume_path": "/Volumes/finance/default/vol",
    "dbxcarta_chat_endpoint": "chat-endpoint",
}


def _make(tmp_path, **overrides: str) -> ClientSettings:
    qfile = tmp_path / "questions.json"
    qfile.write_text("[]")
    base = {**_BASE_SETTINGS, "dbxcarta_client_questions": str(qfile)}
    return ClientSettings(_env_file=None, **{**base, **overrides})


def test_graph_check_skipped_without_graph_arm(monkeypatch, tmp_path) -> None:
    settings = _make(tmp_path, dbxcarta_client_arms="reference")
    calls: list[ClientSettings] = []
    monkeypatch.setattr(run, "preflight_warehouse", lambda ws, wid: None)
    monkeypatch.setattr(run, "_assert_graph_populated", calls.append)

    run._preflight(object(), settings)

    assert calls == []


@pytest.mark.parametrize("arm", ["graph_rag", "schema_dump"])
def test_graph_check_runs_for_graph_arm(monkeypatch, tmp_path, arm: str) -> None:
    settings = _make(tmp_path, dbxcarta_client_arms=arm)
    calls: list[ClientSettings] = []
    monkeypatch.setattr(run, "preflight_warehouse", lambda ws, wid: None)
    monkeypatch.setattr(run, "_assert_graph_populated", calls.append)

    run._preflight(object(), settings)

    assert calls == [settings]


class _FakeResult:
    def __init__(self, count: int) -> None:
        self._count = count

    def single(self) -> dict[str, int]:
        return {"c": self._count}


class _FakeSession:
    def __init__(self, count: int) -> None:
        self._count = count

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def run(self, _query: str) -> _FakeResult:
        return _FakeResult(self._count)


class _FakeDriver:
    def __init__(self, count: int) -> None:
        self._count = count

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def session(self) -> _FakeSession:
        return _FakeSession(self._count)


def _patch_neo4j(monkeypatch, count: int) -> None:
    import neo4j

    monkeypatch.setattr(
        "dbxcarta.client.neo4j_utils.neo4j_credentials",
        lambda settings: ("uri", "user", "pass"),
    )
    monkeypatch.setattr(neo4j.GraphDatabase, "driver", lambda uri, auth: _FakeDriver(count))


def test_assert_graph_populated_passes_with_tables(monkeypatch, tmp_path) -> None:
    _patch_neo4j(monkeypatch, count=12)

    run._assert_graph_populated(_make(tmp_path))  # no raise


def test_assert_graph_populated_raises_on_empty_graph(monkeypatch, tmp_path) -> None:
    _patch_neo4j(monkeypatch, count=0)

    with pytest.raises(RuntimeError, match="run the Ingest job before the"):
        run._assert_graph_populated(_make(tmp_path))
