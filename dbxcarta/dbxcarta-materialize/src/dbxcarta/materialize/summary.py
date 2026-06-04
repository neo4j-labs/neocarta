"""Materialize run-summary: stdout, JSON volume file, and Delta table.

Mirrors the client's ``ClientRunSummary`` rather than reusing the ingest
``RunSummary``: each stage owns a self-contained summary that emits to the same
``dbxcarta_run_summary`` Delta table (``mergeSchema=true``), discriminated by
``job_name``, so all three stages report run history to one place without
coupling this package to the ingest layer. Lightweight by design: only stdlib
plus the core helpers, with PySpark imported inside ``emit_delta``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dbxcarta.core.identifiers import quote_qualified_name
from dbxcarta.core.materialize import MaterializeStats
from dbxcarta.core.volume_io import ensure_volume_subdirs

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

# The job_name discriminator for materialize rows in the shared run-summary
# table and the JSON filename prefix, alongside the ingest "dbxcarta" and the
# client "dbxcarta_client".
JOB_NAME = "dbxcarta_materialize"


@dataclass
class MaterializeRunSummary:
    """One materialize run's outcome: identity, status, and the table tally.

    The tally is held as a single :class:`MaterializeStats` so adding a counter
    is a one-line change to that dataclass, not a field mirrored across the
    summary, ``apply_stats``, and the wire dicts.
    """

    run_id: str
    job_name: str
    catalog: str
    schemas: list[str]
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    status: str = "running"
    error: str | None = None
    stats: MaterializeStats = field(default_factory=MaterializeStats)

    def apply_stats(self, stats: MaterializeStats) -> None:
        """Record the run tally on the summary (replaces any prior value)."""
        self.stats = stats

    def finish(self, *, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.ended_at = datetime.now(UTC)

    def _to_delta_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "catalog": self.catalog,
            "schemas": self.schemas,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "error": self.error,
            "schemas_created": self.stats.schemas_created,
            "tables_created": self.stats.tables_created,
            "rows_inserted": self.stats.rows_inserted,
            "tables_skipped": self.stats.tables_skipped,
            "type_fallbacks": self.stats.type_fallbacks,
            "pk_constraints_added": self.stats.pk_constraints_added,
            "fk_constraints_added": self.stats.fk_constraints_added,
        }

    def _to_json_dict(self) -> dict:
        d = self._to_delta_dict()
        d["started_at"] = self.started_at.isoformat()
        d["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        return d

    def emit_stdout(self) -> None:
        print(
            f"[dbxcarta_materialize] run_id={self.run_id} job={self.job_name} "
            f"status={self.status} catalog={self.catalog}"
        )
        s = self.stats
        print(
            f"  schemas={s.schemas_created} tables={s.tables_created} "
            f"rows={s.rows_inserted} skipped={s.tables_skipped} "
            f"type_fallbacks={s.type_fallbacks} pks={s.pk_constraints_added} "
            f"fks={s.fk_constraints_added}"
        )
        if self.error:
            print(f"  error: {self.error}")

    def emit_json(self, volume_path: str) -> None:
        ts = (self.ended_at or self.started_at).strftime("%Y%m%dT%H%M%SZ")
        path = Path(volume_path) / f"{self.job_name}_{self.run_id}_{ts}.json"
        ensure_volume_subdirs(path.parent)
        path.write_text(json.dumps(self._to_json_dict(), indent=2))

    def emit_delta(self, spark: SparkSession, table_name: str) -> None:
        from pyspark.sql import Row
        from pyspark.sql.types import (
            ArrayType,
            LongType,
            StringType,
            StructField,
            StructType,
            TimestampType,
        )

        schema = StructType(
            [
                StructField("run_id", StringType(), nullable=False),
                StructField("job_name", StringType()),
                StructField("catalog", StringType()),
                StructField("schemas", ArrayType(StringType())),
                StructField("started_at", TimestampType()),
                StructField("ended_at", TimestampType()),
                StructField("status", StringType()),
                StructField("error", StringType()),
                StructField("schemas_created", LongType()),
                StructField("tables_created", LongType()),
                StructField("rows_inserted", LongType()),
                StructField("tables_skipped", LongType()),
                StructField("type_fallbacks", LongType()),
                StructField("pk_constraints_added", LongType()),
                StructField("fk_constraints_added", LongType()),
            ]
        )
        quoted = quote_qualified_name(table_name, expected_parts=3)
        row = Row(**self._to_delta_dict())
        (
            spark.createDataFrame([row], schema=schema)
            .write.format("delta")
            .mode("append")
            .option("mergeSchema", "true")
            .saveAsTable(quoted)
        )

    def emit(self, spark: SparkSession, volume_path: str, table_name: str) -> None:
        self.emit_stdout()
        self.emit_json(volume_path)
        self.emit_delta(spark, table_name)
