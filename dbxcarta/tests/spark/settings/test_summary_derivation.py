"""Phase 5c: SparkIngestSettings derives the summary sinks from the volume root.

Locks the Phase 6 guarantee for the ingest job: with the summary vars absent,
the settings derive them from DATABRICKS_VOLUME_PATH via the core resolver; an
explicit value wins; and with neither the sinks nor the base supplied, config
load fails loudly rather than producing a wrong sink.
"""

from __future__ import annotations

import pytest
from dbxcarta.core.config import derive_ops_config
from dbxcarta.spark.settings import SparkIngestSettings
from pydantic import ValidationError

_VOLUME = "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops"
_REQUIRED: dict[str, str] = {
    "databricks_secret_scope": "dbxcarta-neo4j-test",
    "dbxcarta_catalog": "dense-schema-example",
}


def _make(**overrides: str) -> SparkIngestSettings:
    return SparkIngestSettings(_env_file=None, **{**_REQUIRED, **overrides})


def test_summary_sinks_derived_from_volume_path() -> None:
    settings = _make(
        databricks_volume_path=_VOLUME,
        dbxcarta_summary_volume="",
        dbxcarta_summary_table="",
    )
    expected = derive_ops_config(_VOLUME)

    assert settings.dbxcarta_summary_volume == expected.summary_volume
    assert settings.dbxcarta_summary_table == expected.summary_table


def test_explicit_summary_wins_without_volume_path() -> None:
    settings = _make(
        databricks_volume_path="",
        dbxcarta_summary_volume="/Volumes/cat/schema/vol/dbxcarta",
        dbxcarta_summary_table="cat.schema.table",
    )

    assert settings.dbxcarta_summary_volume == "/Volumes/cat/schema/vol/dbxcarta"
    assert settings.dbxcarta_summary_table == "cat.schema.table"


def test_missing_sinks_and_base_fails_loudly() -> None:
    with pytest.raises(ValidationError, match="cannot be derived"):
        _make(
            databricks_volume_path="",
            dbxcarta_summary_volume="",
            dbxcarta_summary_table="",
        )
