"""Run-summary data model.

The in-memory shape is nominal — `ExtractCounts`, `SampleValueCounts`,
`DeclaredCounters`, `FKSkipCounts` — so no pipeline site pokes stringly-typed
keys into a dict-bag. `to_dict()` flattens the counter groups into a single
`row_counts` map for callers that want to serialize the returned summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neocarta.connectors.databricks.ingest.fk.declared import DeclaredCounters
    from neocarta.connectors.databricks.ingest.transform.sample_values import SampleStats


@dataclass
class FKSkipCounts:
    """Set when the `fk_max_columns` guardrail skips declared-FK discovery.

    `None` on `RunSummary` means the guardrail did not fire. The row_counts
    keys are namespaced `fk_discovery_skipped*` to avoid colliding with the
    declared-FK accounting keys.
    """

    column_count: int = 0
    column_limit: int = 0

    def as_row_counts(self) -> dict[str, int]:
        """Flatten the guardrail trip into the shared row_counts map."""
        return {
            "fk_discovery_skipped": 1,
            "fk_discovery_skipped_column_count": self.column_count,
            "fk_discovery_skipped_column_limit": self.column_limit,
        }


@dataclass
class ExtractCounts:
    """Counts captured immediately after Unity Catalog extraction."""

    schemas: int = 0
    tables: int = 0
    columns: int = 0

    def as_row_counts(self) -> dict[str, int]:
        """Flatten extraction counters into the shared row_counts map."""
        return {
            "schemas": self.schemas,
            "tables": self.tables,
            "columns": self.columns,
        }


@dataclass
class SampleValueCounts:
    """Mirrors sample_values.SampleStats but lives on RunSummary.

    Optional fields (percentiles) are emitted only when non-None.
    """

    candidate_columns: int = 0
    sampled_columns: int = 0
    skipped_columns: int = 0
    skipped_schemas: int = 0
    cardinality_failed_tables: int = 0
    cardinality_wall_clock_ms: int = 0
    sample_wall_clock_ms: int = 0
    value_nodes: int = 0
    has_value_edges: int = 0
    cardinality_min: int | None = None
    cardinality_p25: int | None = None
    cardinality_p50: int | None = None
    cardinality_p75: int | None = None
    cardinality_p95: int | None = None
    cardinality_max: int | None = None

    @classmethod
    def from_sample_stats(cls, stats: SampleStats) -> SampleValueCounts:
        """Copy Spark sample statistics into the run-summary DTO."""
        return cls(
            candidate_columns=stats.candidate_columns,
            sampled_columns=stats.sampled_columns,
            skipped_columns=stats.skipped_columns,
            skipped_schemas=stats.skipped_schemas,
            cardinality_failed_tables=stats.cardinality_failed_tables,
            cardinality_wall_clock_ms=stats.cardinality_wall_clock_ms,
            sample_wall_clock_ms=stats.sample_wall_clock_ms,
            value_nodes=stats.value_nodes,
            has_value_edges=stats.has_value_edges,
            cardinality_min=stats.cardinality_min,
            cardinality_p25=stats.cardinality_p25,
            cardinality_p50=stats.cardinality_p50,
            cardinality_p75=stats.cardinality_p75,
            cardinality_p95=stats.cardinality_p95,
            cardinality_max=stats.cardinality_max,
        )

    def as_row_counts(self) -> dict[str, int]:
        """Flatten sample-value counters into the shared row_counts map.

        Percentile keys are included only when the sampler computed them.
        """
        out: dict[str, int] = {
            "candidate_columns": self.candidate_columns,
            "sampled_columns": self.sampled_columns,
            "skipped_columns": self.skipped_columns,
            "skipped_schemas": self.skipped_schemas,
            "cardinality_failed_tables": self.cardinality_failed_tables,
            "cardinality_wall_clock_ms": self.cardinality_wall_clock_ms,
            "sample_wall_clock_ms": self.sample_wall_clock_ms,
            "value_nodes": self.value_nodes,
            "has_value_edges": self.has_value_edges,
        }
        for name in (
            "cardinality_min",
            "cardinality_p25",
            "cardinality_p50",
            "cardinality_p75",
            "cardinality_p95",
            "cardinality_max",
        ):
            val = getattr(self, name)
            if val is not None:
                out[name] = val
        return out


@dataclass
class RunSummary:
    """Run-level aggregate, returned to the caller of the ingest."""

    run_id: str
    job_name: str
    contract_version: str
    catalog: str
    schemas: list[str]
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    status: str = "running"
    error: str | None = None
    extract: ExtractCounts = field(default_factory=ExtractCounts)
    fk_declared: DeclaredCounters | None = None
    sample_values: SampleValueCounts | None = None
    neo4j_counts: dict[str, int] = field(default_factory=dict)
    fk_skip: FKSkipCounts | None = None
    # Set to a loud message when the value path ran and found candidate columns
    # but produced zero Value nodes — a strong signal that sampling silently
    # failed (unreadable schemas, cardinality wipeout) rather than the catalog
    # genuinely having no sampleable values. None otherwise.
    value_sampling_warning: str | None = None

    def finish(self, *, status: str, error: str | None = None) -> None:
        """Mark the run terminal and stamp its end time."""
        self.status = status
        self.error = error
        self.ended_at = datetime.now(UTC)

    def _build_row_counts(self) -> dict[str, int]:
        """Flatten all nominal counter groups into the `row_counts` shape."""
        out: dict[str, int] = {}
        out.update(self.extract.as_row_counts())
        if self.fk_declared is not None:
            out.update(self.fk_declared.as_row_counts())
        if self.sample_values is not None:
            out.update(self.sample_values.as_row_counts())
        if self.fk_skip is not None:
            out.update(self.fk_skip.as_row_counts())
        return out

    def to_dict(self) -> dict[str, Any]:
        """Flat, serializable view of the run summary."""
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "contract_version": self.contract_version,
            "catalog": self.catalog,
            "schemas": self.schemas,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status,
            "row_counts": self._build_row_counts(),
            "neo4j_counts": dict(self.neo4j_counts),
            "error": self.error,
            "value_sampling_warning": self.value_sampling_warning,
        }
