from __future__ import annotations

from typing import Any

import dbxcarta.spark.run as pipeline
from dbxcarta.spark.settings import SparkIngestSettings


def test_run_dbxcarta_accepts_explicit_settings_and_spark(monkeypatch) -> None:
    settings = SparkIngestSettings(
        databricks_secret_scope="dbxcarta-neo4j-test",
        dbxcarta_catalog="main",
        dbxcarta_schemas="schema_one,schema_two",
        dbxcarta_summary_volume="/Volumes/main/default/dbxcarta/summaries",
        dbxcarta_summary_table="main.default.dbxcarta_runs",
    )
    fake_spark = object()
    calls: dict[str, Any] = {}

    def fake_run(spark, passed_settings, schema_list, summary) -> None:
        calls["run"] = (spark, passed_settings, schema_list, summary.status)

    def fake_emit(summary, spark, volume_path, table_name) -> None:
        calls["emit"] = (spark, volume_path, table_name, summary.status)

    monkeypatch.setattr(pipeline, "_run", fake_run)
    monkeypatch.setattr(pipeline.summary_io, "emit", fake_emit)

    pipeline.run_dbxcarta(settings=settings, spark=fake_spark)

    assert calls["run"] == (
        fake_spark,
        settings,
        ["schema_one", "schema_two"],
        "running",
    )
    assert calls["emit"] == (
        fake_spark,
        "/Volumes/main/default/dbxcarta/summaries",
        "main.default.dbxcarta_runs",
        "success",
    )
