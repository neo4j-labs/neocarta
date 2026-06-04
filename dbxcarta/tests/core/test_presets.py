"""Tests for the shared StandardPreset and ReadinessReport.

StandardPreset is the one preset every example uses, so the readiness rule, the
relabeled report, the questions-file validation, and the upload destination
check are exercised here once rather than per example.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dbxcarta.core.presets import (
    Preset,
    QuestionsUploadable,
    ReadinessCheckable,
    ReadinessReport,
    StandardPreset,
    _validate_questions_file,
)


class _FakeStatementExecution:
    """Returns the schema rows mapped to whichever catalog the SQL targets."""

    def __init__(self, schemas_by_catalog: dict[str, list[str]]) -> None:
        self._schemas_by_catalog = schemas_by_catalog

    def execute_statement(self, **kwargs: object) -> object:
        statement = str(kwargs["statement"])
        rows: list[list[str]] = []
        for catalog, schemas in self._schemas_by_catalog.items():
            if f"`{catalog}`" in statement:
                rows = [[name] for name in schemas]
                break
        return type(
            "Resp",
            (),
            {"result": type("Result", (), {"data_array": rows})()},
        )()


class _FakeWorkspaceClient:
    def __init__(self, schemas_by_catalog: dict[str, list[str]]) -> None:
        self.statement_execution = _FakeStatementExecution(schemas_by_catalog)


# questions_file is never opened by the readiness, protocol, or dest-validation
# tests below: readiness ignores it, and the dest check raises before any read.
# _validate_questions_file is exercised directly with tmp_path fixtures.
_QUESTIONS_PLACEHOLDER = Path("questions.json")


def _preset() -> StandardPreset:
    return StandardPreset(questions_file=_QUESTIONS_PLACEHOLDER)


def test_standard_preset_satisfies_protocols() -> None:
    preset = _preset()
    assert isinstance(preset, Preset)
    assert isinstance(preset, ReadinessCheckable)
    assert isinstance(preset, QuestionsUploadable)


# --- Readiness rule: a catalog needs a schema beyond information_schema/default


def test_readiness_not_ready_with_only_auto_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DBXCARTA_CATALOG", "cat")
    monkeypatch.delenv("DBXCARTA_CATALOGS", raising=False)
    ws = _FakeWorkspaceClient({"cat": ["information_schema", "default"]})
    report = _preset().readiness(ws=ws, warehouse_id="wh")  # type: ignore[arg-type]
    assert not report.ok()
    assert report.missing_required == ("cat",)
    assert report.present == ()


def test_readiness_ready_with_one_data_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DBXCARTA_CATALOG", "cat")
    monkeypatch.delenv("DBXCARTA_CATALOGS", raising=False)
    ws = _FakeWorkspaceClient({"cat": ["information_schema", "default", "sales"]})
    report = _preset().readiness(ws=ws, warehouse_id="wh")  # type: ignore[arg-type]
    assert report.ok()
    assert report.present == ("cat",)
    assert report.catalog == "cat"
    assert report.schema == ""


def test_readiness_checks_every_catalog_in_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DBXCARTA_CATALOG", "silver")
    monkeypatch.setenv("DBXCARTA_CATALOGS", "silver:silver,gold:gold")
    ws = _FakeWorkspaceClient(
        {
            "silver": ["information_schema", "default", "graph_schema"],
            "gold": ["information_schema", "default"],  # nothing materialized
        }
    )
    report = _preset().readiness(ws=ws, warehouse_id="wh")  # type: ignore[arg-type]
    assert report.present == ("silver",)
    assert report.missing_required == ("gold",)
    assert report.catalog == "silver,gold"
    assert not report.ok()


def test_readiness_fails_loud_without_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBXCARTA_CATALOG", raising=False)
    monkeypatch.delenv("DBXCARTA_CATALOGS", raising=False)
    ws = _FakeWorkspaceClient({})
    with pytest.raises(RuntimeError, match="DBXCARTA_CATALOG is not set"):
        _preset().readiness(ws=ws, warehouse_id="wh")  # type: ignore[arg-type]


# --- ReadinessReport.format relabel ------------------------------------------


def test_format_omits_empty_schema_and_relabels_catalogs() -> None:
    report = ReadinessReport(
        catalog="silver,gold",
        schema="",
        present=("silver", "gold"),
        missing_required=(),
        missing_optional=(),
    )
    formatted = report.format()
    assert "scope: silver,gold" in formatted
    assert "present catalogs: 2" in formatted
    assert "catalogs: ready" in formatted
    assert "status: ready" in formatted


def test_format_reports_missing_catalogs() -> None:
    report = ReadinessReport(
        catalog="silver,gold",
        schema="",
        present=("silver",),
        missing_required=("gold",),
        missing_optional=(),
    )
    formatted = report.format()
    assert "missing required: gold" in formatted
    assert "status: not ready" in formatted


# --- Questions file validation -----------------------------------------------


def test_validate_questions_file_accepts_non_empty_array(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    path.write_text('[{"question_id": "q1", "question": "how many rows?"}]')
    _validate_questions_file(path)  # does not raise


def test_validate_questions_file_rejects_empty_array(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    path.write_text("[]")
    with pytest.raises(ValueError):
        _validate_questions_file(path)


def test_validate_questions_file_requires_question_fields(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    path.write_text('[{"question_id": "q1"}]')
    with pytest.raises(ValueError):
        _validate_questions_file(path)


def test_validate_questions_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _validate_questions_file(tmp_path / "nope.json")


# --- Upload destination validation -------------------------------------------


def test_upload_requires_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBXCARTA_CLIENT_QUESTIONS", raising=False)
    with pytest.raises(RuntimeError, match="DBXCARTA_CLIENT_QUESTIONS"):
        _preset().upload_questions(ws=None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "dest",
    ["/tmp/questions.json", "/Volumes/cat/sch/vol/questions.txt"],
)
def test_upload_rejects_non_volumes_json_destination(
    dest: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DBXCARTA_CLIENT_QUESTIONS", dest)
    with pytest.raises(ValueError, match="/Volumes/"):
        _preset().upload_questions(ws=None)  # type: ignore[arg-type]
