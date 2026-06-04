"""Phase 3/4 settings: relationship-write parallelism and the FK guardrail.

Pins the safe defaults (rel-write partitions = 1, FK guardrail disabled)
and the field-level rejection of values that would break the
coalesce/repartition helper or the guardrail contract. No Spark, no cloud
infra — the boundary itself.
"""

from __future__ import annotations

import pytest
from dbxcarta.spark.settings import SparkIngestSettings
from pydantic import ValidationError

_BASE = {
    "databricks_secret_scope": "dbxcarta-neo4j-test",
    "dbxcarta_catalog": "main",
    "dbxcarta_summary_volume": "/Volumes/cat/schema/vol/dbxcarta",
    "dbxcarta_summary_table": "cat.schema.table",
}


def test_defaults_are_the_safe_values() -> None:
    """Default = single-partition writes and guardrail disabled, so default
    behavior is unchanged by Phase 3/4."""
    s = SparkIngestSettings(**_BASE)
    assert s.dbxcarta_rel_write_partitions == 1
    assert s.dbxcarta_fk_max_columns == 0


@pytest.mark.parametrize("n", [2, 8, 64])
def test_rel_write_partitions_accepts_values_above_one(n: int) -> None:
    s = SparkIngestSettings(dbxcarta_rel_write_partitions=n, **_BASE)
    assert s.dbxcarta_rel_write_partitions == n


@pytest.mark.parametrize("bad", [0, -1, -10])
def test_rel_write_partitions_rejects_below_one(bad: int) -> None:
    with pytest.raises(ValidationError, match="must be >= 1"):
        SparkIngestSettings(dbxcarta_rel_write_partitions=bad, **_BASE)


@pytest.mark.parametrize("n", [0, 1, 5000])
def test_fk_max_columns_accepts_zero_and_positive(n: int) -> None:
    s = SparkIngestSettings(dbxcarta_fk_max_columns=n, **_BASE)
    assert s.dbxcarta_fk_max_columns == n


@pytest.mark.parametrize("bad", [-1, -100])
def test_fk_max_columns_rejects_negative(bad: int) -> None:
    with pytest.raises(ValidationError, match="must be >= 0"):
        SparkIngestSettings(dbxcarta_fk_max_columns=bad, **_BASE)
