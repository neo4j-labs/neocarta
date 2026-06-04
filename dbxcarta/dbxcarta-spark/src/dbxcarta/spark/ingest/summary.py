"""Run-summary data model and wire shape.

The in-memory shape is nominal — `ExtractCounts`, `EmbeddingCounts`,
`SampleValueCounts`, `CoarseFKCounts` — so
that no pipeline site pokes stringly-typed keys into a dict-bag. The flat
`row_counts: dict[str, int]` and `embedding_*: dict[str, int/float]` shape
still appears on the wire (JSON + Delta), but only at the `to_dict()`
serialization boundary. Delta DDL is unchanged; JSON contract is unchanged.

Moving that shape across process boundaries (stdout / JSON volume file /
Delta table) and reading it back lives in `summary_io`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dbxcarta.spark.contract import NodeLabel
    from dbxcarta.spark.ingest.fk.declared import DeclaredCounters
    from dbxcarta.spark.ingest.fk.inference import CoarseFKCounts
    from dbxcarta.spark.ingest.transform.sample_values import SampleStats


@dataclass
class FKSkipCounts:
    """Set when the `dbxcarta_fk_max_columns` guardrail skips FK discovery.

    `None` on `RunSummary` means the guardrail did not fire. The row_counts
    keys are deliberately namespaced `fk_discovery_skipped*`: the bare
    `fk_skipped` key belongs to declared-FK accounting (`fk_declared -
    fk_resolved`), which `verify.references._check_accounting` invariant-
    checks. Reusing it would make a guardrail trip fail that invariant.
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

    Captured from SampleStats via `from_sample_stats`; flat serialization to
    `row_counts` happens in `as_row_counts`. Optional fields (percentiles)
    are emitted only when non-None — matches the legacy pipeline behaviour
    where the percentile keys were skipped if unset.
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
        """Copy Spark sample statistics into the run-summary DTO.

        Keeping this conversion here prevents the pipeline from depending on
        the summary's flattened wire keys.
        """
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

        Percentile keys are included only when the sampler computed them, which
        keeps empty or disabled sampling runs from emitting misleading zeroes.
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
class EmbeddingCounts:
    """Per-label embedding bookkeeping.

    Keyed by `NodeLabel` enum in memory; serialization to the Delta/JSON
    wire flattens to `dict[str, ...]` using `label.value` via `as_*_map`.
    """

    model: str | None = None
    failure_threshold: float | None = None
    flags: dict[NodeLabel, bool] = field(default_factory=dict)
    attempts: dict[NodeLabel, int] = field(default_factory=dict)
    successes: dict[NodeLabel, int] = field(default_factory=dict)
    failure_rate_per_label: dict[NodeLabel, float] = field(default_factory=dict)
    ledger_hits: dict[NodeLabel, int] = field(default_factory=dict)
    aggregate_failure_rate: float | None = None

    def as_flags_map(self) -> dict[str, bool]:
        """Return embedding enablement keyed by public node-label strings."""
        return {k.value: v for k, v in self.flags.items()}

    def as_attempts_map(self) -> dict[str, int]:
        """Return embedding attempt counts keyed by public node-label strings."""
        return {k.value: v for k, v in self.attempts.items()}

    def as_successes_map(self) -> dict[str, int]:
        """Return embedding success counts keyed by public node-label strings."""
        return {k.value: v for k, v in self.successes.items()}

    def as_failure_rate_map(self) -> dict[str, float]:
        """Return per-label embedding failure rates keyed by public labels."""
        return {k.value: v for k, v in self.failure_rate_per_label.items()}

    def as_ledger_hits_map(self) -> dict[str, int]:
        """Return per-label ledger hit counts keyed by public labels."""
        return {k.value: v for k, v in self.ledger_hits.items()}


@dataclass
class VerifyResult:
    """Verify outcome captured into the RunSummary.

    `ok=False` means at least one violation. `violations` is the full list
    surfaced through the JSON output for auditability without driver logs.
    Delta only retains the flat `verify_ok`/`verify_violation_count` summary
    columns to keep the table schema simple.
    """

    ok: bool
    violations: list[dict[str, str]]  # [{"code": str, "message": str}, ...]


@dataclass
class RunSummary:
    """Run-level aggregate.

    In-memory: nominal sub-dataclasses for each counter group.
    On the wire: flat `row_counts` dict + flat `embedding_*` maps. The
    `to_dict` / `to_json_dict` methods are the sole place where enum keys
    become strings and sub-dataclasses flatten into the legacy wire shape.
    """

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
    fk_metadata: CoarseFKCounts | None = None
    sample_values: SampleValueCounts | None = None
    embeddings: EmbeddingCounts = field(default_factory=EmbeddingCounts)
    neo4j_counts: dict[str, int] = field(default_factory=dict)
    verify: VerifyResult | None = None
    fk_skip: FKSkipCounts | None = None
    # Set to a loud message when the value path ran and found candidate
    # columns but produced zero Value nodes — a strong signal that sampling
    # silently failed (unreadable schemas, cardinality wipeout) rather than
    # the catalog genuinely having no sampleable values. None otherwise.
    value_sampling_warning: str | None = None

    def finish(self, *, status: str, error: str | None = None) -> None:
        """Mark the run terminal and stamp its end time.

        The pipeline calls this exactly once on the success or failure path
        before emitters serialize the summary.
        """
        self.status = status
        self.error = error
        self.ended_at = datetime.now(UTC)

    def _build_row_counts(self) -> dict[str, int]:
        """Flatten all nominal counter groups into the legacy `row_counts` shape."""
        out: dict[str, int] = {}
        out.update(self.extract.as_row_counts())
        if self.fk_declared is not None:
            out.update(self.fk_declared.as_row_counts())
        if self.fk_metadata is not None:
            out.update(self.fk_metadata.as_summary_dict("fk_inferred_metadata"))
        if self.sample_values is not None:
            out.update(self.sample_values.as_row_counts())
        if self.fk_skip is not None:
            out.update(self.fk_skip.as_row_counts())
        return out

    def to_dict(self) -> dict[str, Any]:
        """Returns dict with datetime objects — suitable for Spark Row.

        Serialization shape is the legacy flat contract: `row_counts` is a
        single dict[str, int], embedding fields are flat `dict[str, ...]`.
        """
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "contract_version": self.contract_version,
            "catalog": self.catalog,
            "schemas": self.schemas,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "row_counts": self._build_row_counts(),
            "neo4j_counts": dict(self.neo4j_counts),
            "error": self.error,
            "value_sampling_warning": self.value_sampling_warning,
            "embedding_model": self.embeddings.model,
            "embedding_flags": self.embeddings.as_flags_map(),
            "embedding_attempts": self.embeddings.as_attempts_map(),
            "embedding_successes": self.embeddings.as_successes_map(),
            "embedding_failure_rate_per_label": self.embeddings.as_failure_rate_map(),
            "embedding_failure_rate": self.embeddings.aggregate_failure_rate,
            "embedding_failure_threshold": self.embeddings.failure_threshold,
            "embedding_ledger_hits": self.embeddings.as_ledger_hits_map(),
            # Flat verify summary — kept flat so the Delta schema doesn't need
            # a nested struct. The JSON output replaces these with a richer
            # nested `verify` object that includes the violation list.
            "verify_ok": None if self.verify is None else self.verify.ok,
            "verify_violation_count": (0 if self.verify is None else len(self.verify.violations)),
        }

    def to_json_dict(self) -> dict[str, Any]:
        """Returns dict with ISO string timestamps — suitable for JSON serialization."""
        d = self.to_dict()
        d["started_at"] = self.started_at.isoformat()
        d["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        if self.verify is not None:
            d.pop("verify_ok", None)
            d.pop("verify_violation_count", None)
            d["verify"] = {
                "ok": self.verify.ok,
                "violation_count": len(self.verify.violations),
                "violations": self.verify.violations,
            }
        return d
