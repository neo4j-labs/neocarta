from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from dbxcarta.spark.ingest.summary_io import LoadSummaryError, load_summary_from_volume

_VOLUME = "/Volumes/main/ops/dbxcarta/summaries"


@dataclass
class _Entry:
    name: str


class _Download:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    @property
    def contents(self) -> _Contents:
        return _Contents(self._payload)


class _Contents:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


class _Files:
    def __init__(self, files: dict[str, dict[str, Any]]) -> None:
        self._files = files

    def list_directory_contents(self, *, directory_path: str) -> list[_Entry]:
        assert directory_path == _VOLUME
        return [_Entry(name) for name in self._files]

    def download(self, *, file_path: str) -> _Download:
        name = file_path[len(_VOLUME) + 1 :]
        return _Download(self._files[name])


class _WorkspaceClient:
    def __init__(self, files: dict[str, dict[str, Any]]) -> None:
        self.files = _Files(files)


def _summary(job_name: str, run_id: str, *, status: str = "success") -> dict[str, Any]:
    return {"job_name": job_name, "run_id": run_id, "status": status}


def test_no_run_id_skips_materialize_and_returns_ingest_summary() -> None:
    """Every job type writes into one shared volume. The materialize file sorts
    after the ingest file lexically (`dbxcarta_materialize_` > `dbxcarta_local_`),
    so a newest-first scan must use the `job_name` content guard, not the
    filename, or verify is handed the materialize summary that lacks row counts.
    """
    files = {
        "dbxcarta_local_20260603T000000Z.json": _summary("dbxcarta", "local"),
        "dbxcarta_materialize_local_20260603T000000Z.json": _summary(
            "dbxcarta_materialize", "local"
        ),
        "dbxcarta_client_local_20260603T000000Z.json": _summary("dbxcarta_client", "local"),
    }
    ws = _WorkspaceClient(files)

    loaded = load_summary_from_volume(ws, _VOLUME)

    assert loaded is not None
    assert loaded["job_name"] == "dbxcarta"
    assert loaded["run_id"] == "local"


def test_no_run_id_can_select_a_non_default_job_name() -> None:
    files = {
        "dbxcarta_local_20260603T000000Z.json": _summary("dbxcarta", "local"),
        "dbxcarta_materialize_local_20260603T000000Z.json": _summary(
            "dbxcarta_materialize", "local"
        ),
    }
    ws = _WorkspaceClient(files)

    loaded = load_summary_from_volume(ws, _VOLUME, job_name="dbxcarta_materialize")

    assert loaded is not None
    assert loaded["job_name"] == "dbxcarta_materialize"


def test_no_run_id_returns_none_when_no_summary_matches_job_name() -> None:
    files = {
        "dbxcarta_materialize_local_20260603T000000Z.json": _summary(
            "dbxcarta_materialize", "local"
        ),
    }
    ws = _WorkspaceClient(files)

    assert load_summary_from_volume(ws, _VOLUME) is None


def test_run_id_matches_exact_job_name_token_not_a_sibling_job() -> None:
    """The run-id branch keys on the `{job_name}_{run_id}_` filename token, so a
    same-run-id materialize file does not satisfy an ingest lookup.
    """
    files = {
        "dbxcarta_local_20260603T000000Z.json": _summary("dbxcarta", "local"),
        "dbxcarta_materialize_local_20260603T000000Z.json": _summary(
            "dbxcarta_materialize", "local"
        ),
    }
    ws = _WorkspaceClient(files)

    loaded = load_summary_from_volume(ws, _VOLUME, run_id="local")

    assert loaded is not None
    assert loaded["job_name"] == "dbxcarta"


def test_run_id_raises_on_duplicate_matches() -> None:
    files = {
        "dbxcarta_local_20260603T000000Z.json": _summary("dbxcarta", "local"),
        "dbxcarta_local_20260603T010000Z.json": _summary("dbxcarta", "local"),
    }
    ws = _WorkspaceClient(files)

    with pytest.raises(LoadSummaryError):
        load_summary_from_volume(ws, _VOLUME, run_id="local")
