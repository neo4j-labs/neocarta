"""Unit tests for the bootstrap/teardown UC-admin helpers."""

from __future__ import annotations

import pytest
from databricks.sdk.service.sql import StatementState
from dbxcarta.submit.uc_admin import (
    TeardownKind,
    TeardownTarget,
    drop_teardown_target,
    ensure_uc_volume,
    execute_statement,
    parse_teardown_target,
    parse_teardown_targets,
)


class _FakeError:
    def __init__(self, message: str) -> None:
        self.message = message


class _FakeStatus:
    def __init__(self, state: StatementState, error: _FakeError | None) -> None:
        self.state = state
        self.error = error


class _FakeResult:
    def __init__(self, rows: list[list[str]]) -> None:
        self.data_array = rows
        self.next_chunk_index = None


class _FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeManifest:
    def __init__(self, columns: list[str]) -> None:
        self.schema = _FakeSchema(columns)


class _FakeSchema:
    def __init__(self, columns: list[str]) -> None:
        self.columns = [_FakeColumn(name) for name in columns]


class _FakeResponse:
    def __init__(
        self,
        state: StatementState,
        error: _FakeError | None,
        *,
        result: _FakeResult | None = None,
        manifest: _FakeManifest | None = None,
    ) -> None:
        self.status = _FakeStatus(state, error)
        self.statement_id = "stmt-1"
        self.result = result
        self.manifest = manifest


class _FakeStatementExecution:
    def __init__(
        self, state: StatementState, error: _FakeError | None, catalogs: list[str]
    ) -> None:
        self.statements: list[str] = []
        self._state = state
        self._error = error
        self._catalogs = catalogs

    def execute_statement(self, *, statement: str, **kwargs: object) -> _FakeResponse:
        self.statements.append(statement)
        # SHOW CATALOGS is a read used by the catalog-existence guard; answer it
        # successfully regardless of the injected DDL failure state, so failure
        # injection exercises the CREATE path rather than the precheck.
        if statement.strip().upper().startswith("SHOW CATALOGS"):
            return _FakeResponse(
                StatementState.SUCCEEDED,
                None,
                result=_FakeResult([[name] for name in self._catalogs]),
                manifest=_FakeManifest(["catalog"]),
            )
        return _FakeResponse(self._state, self._error)


class _FakeWorkspaceClient:
    """Captures executed SQL without touching a real warehouse.

    Returns a synthetic statement response so :func:`execute_statement` can
    inspect its terminal state. Defaults to ``SUCCEEDED``; pass a different
    state (and optional error) to exercise the failure path. ``catalogs`` is the
    set the ``SHOW CATALOGS`` guard sees (empty by default, so the catalog is
    treated as absent and ``CREATE CATALOG`` runs).
    """

    def __init__(
        self,
        *,
        state: StatementState = StatementState.SUCCEEDED,
        error_message: str | None = None,
        catalogs: list[str] | None = None,
    ) -> None:
        error = _FakeError(error_message) if error_message is not None else None
        self.statement_execution = _FakeStatementExecution(state, error, catalogs or [])


def test_parse_teardown_target_catalog() -> None:
    target = parse_teardown_target("catalog:schemapile_lakehouse")
    assert target == TeardownTarget(kind=TeardownKind.CATALOG, catalog="schemapile_lakehouse")
    assert target.describe() == "catalog schemapile_lakehouse"


def test_parse_teardown_target_schema() -> None:
    target = parse_teardown_target("schema:dbxcarta-catalog.finance_genie_ops")
    assert target.kind is TeardownKind.SCHEMA
    assert target.catalog == "dbxcarta-catalog"
    assert target.schema == "finance_genie_ops"
    assert target.describe() == "schema dbxcarta-catalog.finance_genie_ops"


@pytest.mark.parametrize(
    "value",
    [
        "schemapile_lakehouse",  # no prefix
        "schema:onlycatalog",  # schema form missing .schema
        "bogus:catalog.schema",  # unknown prefix
    ],
)
def test_parse_teardown_target_rejects_malformed(value: str) -> None:
    with pytest.raises(ValueError):
        parse_teardown_target(value)


def test_parse_teardown_target_refuses_protected_catalog() -> None:
    with pytest.raises(ValueError, match="protected"):
        parse_teardown_target("catalog:main")
    with pytest.raises(ValueError, match="protected"):
        parse_teardown_target("schema:system.foo")


def test_parse_teardown_targets_splits_comma_separated() -> None:
    targets = parse_teardown_targets(
        "catalog:schemapile_lakehouse, schema:dbxcarta-catalog.schemapile_ops"
    )
    assert [t.describe() for t in targets] == [
        "catalog schemapile_lakehouse",
        "schema dbxcarta-catalog.schemapile_ops",
    ]


def test_parse_teardown_targets_single_value() -> None:
    targets = parse_teardown_targets("schema:dbxcarta-catalog.finance_genie_ops")
    assert len(targets) == 1
    assert targets[0].kind is TeardownKind.SCHEMA


def test_parse_teardown_targets_rejects_empty() -> None:
    with pytest.raises(ValueError):
        parse_teardown_targets("   ")


def test_parse_teardown_targets_propagates_protected_guard() -> None:
    with pytest.raises(ValueError, match="protected"):
        parse_teardown_targets("schema:cat.s, catalog:main")


def test_ensure_uc_volume_emits_idempotent_ddl() -> None:
    ws = _FakeWorkspaceClient()
    ensure_uc_volume(ws, "wh1", catalog="cat", schema="sch", volume="vol")
    stmts = ws.statement_execution.statements
    assert len(stmts) == 4
    assert stmts[0].startswith("SHOW CATALOGS")
    assert stmts[1].startswith("CREATE CATALOG IF NOT EXISTS `cat`")
    assert stmts[2].startswith("CREATE SCHEMA IF NOT EXISTS `cat`.`sch`")
    assert stmts[3].startswith("CREATE VOLUME IF NOT EXISTS `cat`.`sch`.`vol`")


def test_ensure_uc_volume_skips_create_when_catalog_exists() -> None:
    ws = _FakeWorkspaceClient(catalogs=["cat"])
    ensure_uc_volume(ws, "wh1", catalog="cat", schema="sch", volume="vol")
    stmts = ws.statement_execution.statements
    assert not any(s.startswith("CREATE CATALOG") for s in stmts)
    assert any(s.startswith("CREATE SCHEMA IF NOT EXISTS `cat`.`sch`") for s in stmts)
    assert any(s.startswith("CREATE VOLUME IF NOT EXISTS `cat`.`sch`.`vol`") for s in stmts)


def test_ensure_uc_volume_refuses_protected_catalog() -> None:
    ws = _FakeWorkspaceClient()
    with pytest.raises(ValueError, match="protected"):
        ensure_uc_volume(ws, "wh1", catalog="main", schema="s", volume="v")
    assert ws.statement_execution.statements == []


def test_drop_teardown_target_schema_cascades() -> None:
    ws = _FakeWorkspaceClient()
    drop_teardown_target(ws, "wh1", TeardownTarget(TeardownKind.SCHEMA, "cat", "sch"))
    assert ws.statement_execution.statements == ["DROP SCHEMA IF EXISTS `cat`.`sch` CASCADE"]


def test_drop_teardown_target_catalog_cascades() -> None:
    ws = _FakeWorkspaceClient()
    drop_teardown_target(ws, "wh1", TeardownTarget(TeardownKind.CATALOG, "cat"))
    assert ws.statement_execution.statements == ["DROP CATALOG IF EXISTS `cat` CASCADE"]


def test_execute_statement_raises_on_failed_state() -> None:
    ws = _FakeWorkspaceClient(state=StatementState.FAILED, error_message="permission denied")
    with pytest.raises(RuntimeError, match="permission denied"):
        execute_statement(ws, "wh1", "CREATE CATALOG `cat`")


def test_ensure_uc_volume_raises_when_create_fails() -> None:
    ws = _FakeWorkspaceClient(state=StatementState.FAILED, error_message="boom")
    with pytest.raises(RuntimeError, match="boom"):
        ensure_uc_volume(ws, "wh1", catalog="cat", schema="sch", volume="vol")
