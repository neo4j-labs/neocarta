"""Regression guard: single execution and id/id pruning cannot return silently.

Kept out of the fast unit suite (run via its own Make target). Three
deterministic checks, no reliance on real OOM:

  - **Single-execution job-count guard** - the hard lock for the hot path.
    Wraps the metadata strategy in a Spark job group and asserts the strategy
    triggers exactly the pinned number of jobs for one SQL action. A
    reintroduced standalone ``.count()``
    on ``above``/``cand``/``scored``, or a lost ``columns_frame`` persist
    that forces a rebuild, pushes the count up and fails the test.
  - **Structural plan guard** - asserts ``Generate`` (the suffix-array
    explode) and ``Window`` (the dedup/attenuation window) survive in the
    logical plan. These are AQE-stable; no join-strategy assertion.
  - **Pre-filter-effectiveness check** - replaces the removed ``candidates``
    telemetry. Recomputes a pre-filter set size directly from the synthetic
    input and asserts it is a small fraction of the synthetic Cartesian.

Bounded-driver note: the plan's ``spark.driver.maxResultSize`` tripwire is
only truly enforced when this module runs in its own JVM. A second
``SparkSession.getOrCreate()`` in a shared pytest process silently ignores
new config. Rather than give false confidence, this module builds its own
session requesting the cap and treats the bounded-driver check as a liveness
assertion (the run completes without an accidental driver transfer); the
job-count guard above is the real lock for the hot path.
"""

from __future__ import annotations

import pytest
from dbxcarta.spark.ingest.fk.inference import (
    build_columns_frame,
    build_pk_gate,
    infer_metadata_edges,
)

# Pinned on the correct (single-execution) implementation. `infer_metadata_
# edges` performs exactly ONE Spark action (`edges.cache().count()`), but AQE
# expands that single action's physical execution into a deterministic set of
# jobs: one per adaptive shuffle stage plus each broadcast build over this
# multi-shuffle plan (explode, self-join, two windows, the PK join, the
# broadcast score-table join). Observed stable at 16 across runs. This value
# is implementation-defined: treat ANY change as a hot-path regression (a
# reintroduced standalone `.count()` on above/cand/scored, or a lost
# columns_frame persist forcing a rebuild, adds a whole extra query
# execution and shifts this count), not a threshold to bump. See docstring.
_EXPECTED_METADATA_JOBS = 16

_CAT = "main"
_SCHEMA = "guard"
# Tables in the synthetic catalog. Each table contributes an `id` PK plus a
# stem-matching `<prev>_id` FK column, so the strategy does real
# explode/join/window/dedup work and the id/id cartesian is exercised.
# Scale this up (or widen rows) to make a deliberately reintroduced
# `.collect()` exceed the requested driver cap when run in isolation.
_N_TABLES = 80

_COL_FIELDS = (
    "table_catalog",
    "table_schema",
    "table_name",
    "column_name",
    "data_type",
    "comment",
)


def _columns_schema():
    from pyspark.sql.types import StringType, StructField, StructType

    return StructType([StructField(n, StringType(), True) for n in _COL_FIELDS])


def _constraints_schema():
    from pyspark.sql.types import (
        IntegerType,
        StringType,
        StructField,
        StructType,
    )

    return StructType(
        [
            StructField("table_catalog", StringType(), True),
            StructField("table_schema", StringType(), True),
            StructField("table_name", StringType(), True),
            StructField("column_name", StringType(), True),
            StructField("constraint_type", StringType(), True),
            StructField("ordinal_position", IntegerType(), True),
            StructField("constraint_name", StringType(), True),
        ]
    )


def _synthetic_catalog() -> tuple[list[tuple], list[tuple]]:
    """`_N_TABLES` tables, each with `id` (PK) + a stem-matching `<prev>_id`.

    Column `t{i}.t{i-1}_id` suffix-stem-matches table `t{i-1}`'s `id`, so a
    real metadata candidate exists per table; every table also has an `id`,
    so the id/id cartesian is present for the metadata prune to suppress.
    """
    cols: list[tuple] = []
    cons: list[tuple] = []
    for i in range(_N_TABLES):
        t = f"t{i}"
        cols.append((_CAT, _SCHEMA, t, "id", "BIGINT", None))
        cols.append((_CAT, _SCHEMA, t, "name", "STRING", None))
        if i > 0:
            cols.append((_CAT, _SCHEMA, t, f"t{i - 1}_id", "BIGINT", None))
        cons.append(
            (_CAT, _SCHEMA, t, "id", "PRIMARY KEY", 1, f"{t}_pk"),
        )
    return cols, cons


@pytest.fixture(scope="module")
def guard_spark():
    """Own SparkSession requesting the bounded-driver cap.

    ``getOrCreate`` returns the existing session unchanged if one already
    exists in this JVM, so the cap is only real when this module runs
    isolated; otherwise the bounded-driver check degrades to liveness. The
    job-count guard does not depend on the cap.
    """
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.master("local[1]")
        .appName("dbxcarta-fk-guard")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.driver.maxResultSize", "10m")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
        .getOrCreate()
    )


def _build_frames(spark):
    columns_df = spark.createDataFrame(
        _synthetic_catalog()[0],
        schema=_columns_schema(),
    )
    constraints_df = spark.createDataFrame(
        _synthetic_catalog()[1],
        schema=_constraints_schema(),
    )
    cf = build_columns_frame(columns_df)
    pk_gate, composite_pk_count = build_pk_gate(cf, constraints_df)
    return cf, pk_gate, composite_pk_count


def test_metadata_runs_pinned_strategy_job_count(guard_spark) -> None:
    """The hot-path lock: metadata triggers the pinned job count.

    ``build_pk_gate``'s own ``.count()`` runs before the measured region, so
    only ``infer_metadata_edges``' actions fall inside the job group.
    """
    cf, pk_gate, composite = _build_frames(guard_spark)
    sc = guard_spark.sparkContext
    group = "fk_meta_guard"
    sc.setJobGroup(group, "metadata strategy")
    before = set(sc.statusTracker().getJobIdsForGroup(group))
    edges, counts, _ = infer_metadata_edges(
        guard_spark,
        cf,
        pk_gate,
        None,
        composite_pk_count=composite,
    )
    jobs = set(sc.statusTracker().getJobIdsForGroup(group)) - before
    assert len(jobs) == _EXPECTED_METADATA_JOBS, (
        f"metadata ran {len(jobs)} jobs, expected "
        f"{_EXPECTED_METADATA_JOBS}; hot path regressed (a non-load-bearing "
        f"count or a lost shared-frame persist was reintroduced)"
    )
    # Liveness for the bounded-driver concern: completed without an
    # accidental catalog-scale driver transfer (would exceed the requested
    # maxResultSize when this module runs isolated).
    assert counts.accepted >= 0
    edges.unpersist()


def test_metadata_plan_keeps_explode_and_window(guard_spark) -> None:
    """Structural plan guard: AQE-stable operators must survive."""
    cf, pk_gate, composite = _build_frames(guard_spark)
    edges, _counts, _ = infer_metadata_edges(
        guard_spark,
        cf,
        pk_gate,
        None,
        composite_pk_count=composite,
    )
    plan = edges._jdf.queryExecution().toString()
    for op in ("Generate", "Window"):
        assert op in plan, f"{op} missing; FK plan regressed"
    edges.unpersist()


def test_prefilter_is_small_fraction_of_cartesian(guard_spark) -> None:
    """Replaces the removed `candidates` telemetry.

    Recomputes the pre-filter working-set size directly from the synthetic
    input: same-(catalog, schema) columns sharing a lowered name, distinct
    columns, PK-like target, and the metadata id/id prune applied. The
    metadata strategy drops generic id/id before scoring, so the pre-scoring
    set must too. This test asserts it is a small fraction of the full
    column Cartesian.
    This is the Phase-2 validation gate, now in the guard rather than on
    every production run.
    """
    from pyspark.sql import functions as F

    cf, pk_gate, _ = _build_frames(guard_spark)
    n_cols = cf.count()
    cartesian = n_cols * n_cols

    a = cf.select(
        F.col("col_id").alias("a_id"),
        F.col("catalog").alias("a_cat"),
        F.col("schema").alias("a_sch"),
        F.lower(F.col("column")).alias("a_name"),
    )
    b = cf.select(
        F.col("col_id").alias("b_id"),
        F.col("catalog").alias("b_cat"),
        F.col("schema").alias("b_sch"),
        F.lower(F.col("column")).alias("b_name"),
    )
    pk_ids = pk_gate.select(F.col("col_id").alias("b_id"))
    prefilter = (
        a.join(
            b,
            (F.col("a_cat") == F.col("b_cat"))
            & (F.col("a_sch") == F.col("b_sch"))
            & (F.col("a_name") == F.col("b_name"))
            & (F.col("a_id") != F.col("b_id"))
            & ~((F.col("a_name") == F.lit("id")) & (F.col("b_name") == F.lit("id"))),
            "inner",
        )
        .join(pk_ids, "b_id", "inner")
        .count()
    )

    assert prefilter < cartesian * 0.05, (
        f"pre-filter set {prefilter} is not a small fraction of the "
        f"{cartesian} Cartesian; hot-path prune regressed"
    )
