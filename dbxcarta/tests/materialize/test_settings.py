from __future__ import annotations

import pytest
from dbxcarta.materialize.settings import MaterializeSettings


def test_derives_summary_and_blueprint_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBXCARTA_CATALOG", "data_cat")
    monkeypatch.setenv("DATABRICKS_VOLUME_PATH", "/Volumes/ops/sch/vol")
    # Ensure no inherited explicit values mask the derivation under test.
    monkeypatch.delenv("DBXCARTA_SUMMARY_VOLUME", raising=False)
    monkeypatch.delenv("DBXCARTA_SUMMARY_TABLE", raising=False)
    monkeypatch.delenv("DBXCARTA_BLUEPRINT_VOLUME", raising=False)

    s = MaterializeSettings()
    assert s.dbxcarta_catalog == "data_cat"
    assert s.dbxcarta_summary_volume == "/Volumes/ops/sch/vol/dbxcarta/runs"
    assert s.dbxcarta_summary_table == "ops.sch.dbxcarta_run_summary"
    assert s.dbxcarta_blueprint_volume == "/Volumes/ops/sch/vol/dbxcarta/blueprint/blueprint.json"


def test_explicit_summary_values_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBXCARTA_CATALOG", "data_cat")
    monkeypatch.setenv("DATABRICKS_VOLUME_PATH", "/Volumes/ops/sch/vol")
    monkeypatch.setenv("DBXCARTA_SUMMARY_VOLUME", "/Volumes/ops/sch/vol/dbxcarta/runs")
    monkeypatch.setenv("DBXCARTA_SUMMARY_TABLE", "ops.sch.custom_summary")
    monkeypatch.delenv("DBXCARTA_BLUEPRINT_VOLUME", raising=False)

    s = MaterializeSettings()
    assert s.dbxcarta_summary_table == "ops.sch.custom_summary"


def test_rejects_volume_path_that_is_not_a_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBXCARTA_CATALOG", "data_cat")
    monkeypatch.setenv("DATABRICKS_VOLUME_PATH", "not/a/volume")
    with pytest.raises(ValueError):
        MaterializeSettings()
