from __future__ import annotations

from types import SimpleNamespace

import pytest
from databricks.sdk.service.sql import StatementState
from dbxcarta.core import executor as executor_module
from dbxcarta.core.executor import catalog_exists, execute_ddl_blocking, fetch_rows


def _response(
    *,
    statement_id: str | None = "stmt-1",
    first_rows: list[list[object]] | None = None,
    next_chunk_index: int | None = None,
    column_names: list[str | None] | None = None,
):
    names = column_names if column_names is not None else ["id", "name"]
    return SimpleNamespace(
        statement_id=statement_id,
        status=SimpleNamespace(state=StatementState.SUCCEEDED),
        manifest=SimpleNamespace(
            schema=SimpleNamespace(columns=[SimpleNamespace(name=name) for name in names])
        ),
        result=SimpleNamespace(
            data_array=first_rows or [],
            next_chunk_index=next_chunk_index,
        ),
    )


class _StatementExecution:
    def __init__(self, response, chunks):
        self._response = response
        self._chunks = chunks
        self.chunk_calls: list[tuple[str, int]] = []

    def execute_statement(self, **_kwargs):
        return self._response

    def get_statement_result_chunk_n(self, statement_id: str, chunk_index: int):
        self.chunk_calls.append((statement_id, chunk_index))
        return self._chunks[chunk_index]


class _Workspace:
    def __init__(self, statement_execution):
        self.statement_execution = statement_execution


def test_fetch_rows_reads_all_result_chunks() -> None:
    statement_execution = _StatementExecution(
        _response(first_rows=[[1, "a"]], next_chunk_index=1),
        {
            1: SimpleNamespace(data_array=[[2, "b"]], next_chunk_index=2),
            2: SimpleNamespace(data_array=[[3, "c"]], next_chunk_index=None),
        },
    )
    ws = _Workspace(statement_execution)

    columns, rows, error = fetch_rows(ws, "warehouse", "SELECT 1")

    assert error is None
    assert columns == ["id", "name"]
    assert rows == [[1, "a"], [2, "b"], [3, "c"]]
    assert statement_execution.chunk_calls == [("stmt-1", 1), ("stmt-1", 2)]


def test_fetch_rows_requires_statement_id_for_paginated_result() -> None:
    statement_execution = _StatementExecution(
        _response(statement_id=None, first_rows=[[1, "a"]], next_chunk_index=1),
        {},
    )
    ws = _Workspace(statement_execution)

    columns, rows, error = fetch_rows(ws, "warehouse", "SELECT 1")

    assert columns is None
    assert rows is None
    assert error == "statement id missing for paginated result"
    assert statement_execution.chunk_calls == []


def test_fetch_rows_uses_fallback_name_for_unnamed_columns() -> None:
    statement_execution = _StatementExecution(
        _response(first_rows=[[1, "a"]], column_names=["id", None]),
        {},
    )
    ws = _Workspace(statement_execution)

    columns, rows, error = fetch_rows(ws, "warehouse", "SELECT 1")

    assert error is None
    assert columns == ["id", "col_2"]
    assert rows == [[1, "a"]]


def _catalogs_workspace(*names: str) -> _Workspace:
    rows = [[name] for name in names]
    return _Workspace(_StatementExecution(_response(first_rows=rows, column_names=["catalog"]), {}))


def test_catalog_exists_true_when_present() -> None:
    ws = _catalogs_workspace("dbxcarta-catalog", "dense-schema-example")
    assert catalog_exists(ws, "warehouse", "dense-schema-example") is True


def test_catalog_exists_false_when_absent() -> None:
    ws = _catalogs_workspace("dbxcarta-catalog")
    assert catalog_exists(ws, "warehouse", "dense-schema-example") is False


def test_catalog_exists_raises_when_listing_fails() -> None:
    response = SimpleNamespace(
        statement_id="stmt-1",
        status=SimpleNamespace(
            state=StatementState.FAILED,
            error=SimpleNamespace(message="permission denied"),
        ),
        manifest=None,
        result=None,
    )
    ws = _Workspace(_StatementExecution(response, {}))
    with pytest.raises(RuntimeError, match="permission denied"):
        catalog_exists(ws, "warehouse", "dense-schema-example")


def _stmt(state, *, statement_id: str | None = "stmt-1", message: str | None = None):
    error = SimpleNamespace(message=message) if message else None
    return SimpleNamespace(
        statement_id=statement_id,
        status=SimpleNamespace(state=state, error=error),
    )


class _BlockingStatementExecution:
    """Returns a scripted execute response, then a queue of get responses."""

    def __init__(self, execute_response, get_responses=()):
        self._execute_response = execute_response
        self._get_responses = list(get_responses)
        self.get_calls = 0

    def execute_statement(self, **_kwargs):
        return self._execute_response

    def get_statement(self, _statement_id: str):
        self.get_calls += 1
        return self._get_responses.pop(0)


def test_execute_ddl_blocking_succeeds_without_polling(monkeypatch) -> None:
    monkeypatch.setattr(
        executor_module, "time", SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda _s: None)
    )
    execution = _BlockingStatementExecution(_stmt(StatementState.SUCCEEDED))
    ws = _Workspace(execution)

    assert execute_ddl_blocking(ws, "warehouse", "CREATE TABLE t") is None
    assert execution.get_calls == 0


def test_execute_ddl_blocking_polls_until_terminal(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        executor_module,
        "time",
        SimpleNamespace(monotonic=lambda: 0.0, sleep=sleeps.append),
    )
    execution = _BlockingStatementExecution(
        _stmt(StatementState.RUNNING),
        get_responses=[
            _stmt(StatementState.RUNNING),
            _stmt(StatementState.SUCCEEDED),
        ],
    )
    ws = _Workspace(execution)

    execute_ddl_blocking(ws, "warehouse", "INSERT OVERWRITE t", poll_interval_sec=3.0)

    assert execution.get_calls == 2
    assert sleeps == [3.0, 3.0]


def test_execute_ddl_blocking_raises_on_failed_statement(monkeypatch) -> None:
    monkeypatch.setattr(
        executor_module, "time", SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda _s: None)
    )
    execution = _BlockingStatementExecution(_stmt(StatementState.FAILED, message="syntax error"))
    ws = _Workspace(execution)

    with pytest.raises(RuntimeError, match="syntax error"):
        execute_ddl_blocking(ws, "warehouse", "CREATE TABLE t", label="CREATE t")


def test_execute_ddl_blocking_raises_without_statement_id(monkeypatch) -> None:
    monkeypatch.setattr(
        executor_module, "time", SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda _s: None)
    )
    execution = _BlockingStatementExecution(_stmt(StatementState.PENDING, statement_id=None))
    ws = _Workspace(execution)

    with pytest.raises(RuntimeError, match="no statement id"):
        execute_ddl_blocking(ws, "warehouse", "CREATE TABLE t")


def test_execute_ddl_blocking_times_out(monkeypatch) -> None:
    # monotonic returns 0 for the start sample, then 1.0 thereafter so the
    # deadline (start + 0) is immediately exceeded inside the poll loop.
    ticks = iter([0.0, 1.0, 1.0])
    monkeypatch.setattr(
        executor_module,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _s: None),
    )
    execution = _BlockingStatementExecution(_stmt(StatementState.RUNNING))
    ws = _Workspace(execution)

    with pytest.raises(TimeoutError, match="did not complete"):
        execute_ddl_blocking(ws, "warehouse", "CREATE TABLE t", total_timeout_sec=0.0)
    assert execution.get_calls == 0
