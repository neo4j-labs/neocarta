"""Pipeline self-verification: pure assertion functions over a run summary.

The same functions run at the end of `dbxcarta.spark.run.run_dbxcarta` and from
the `dbxcarta verify` CLI. Inputs are a `dict` summary matching
`RunSummary.to_dict()`, a `neo4j.Driver`, and, for catalog-level checks, a
`WorkspaceClient` plus warehouse id. Outputs are aggregated into a `Report`.
Each check returns `list[Violation]`; an empty list means the check passed or
its preconditions were not met and it self-skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from neo4j import Driver


@dataclass
class Violation:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def single_value(result: Any, key: str) -> Any:
    """Return one field from a Neo4j result that must contain one record."""
    record = result.single()
    if record is None:
        raise RuntimeError(f"Neo4j query returned no rows for {key!r}")
    return record[key]


def scoped_catalog(summary: dict[str, Any]) -> tuple[str, str]:
    """Return ``(catalog_id, id_prefix)`` for catalog-scoped verify queries.

    Node ids are normalized through ``contract.generate_id`` (lowercased;
    spaces and hyphens become underscores). Scoping predicates must use the
    same normalized form: comparing the raw ``summary["catalog"]`` against
    ``n.id`` means a catalog or schema name containing a hyphen or space never
    matches, so every scoped count reads 0 even when the graph is correct.
    """
    from dbxcarta.spark.contract import generate_id

    catalog = summary.get("catalog") or ""
    catalog_id = generate_id(catalog) if catalog else ""
    return catalog_id, catalog_id + "."


def scoped_catalogs(
    summary: dict[str, Any], catalogs: list[str] | None
) -> tuple[list[str], list[str]]:
    """Return ``(catalog_ids, id_prefixes)`` for the full resolved-catalog set.

    A multi-catalog run (``dbxcarta_catalogs``) writes every resolved catalog
    into one graph, but ``RunSummary.row_counts`` are aggregate totals across
    all of them. The count invariants must therefore scope to every resolved
    catalog, not just the primary, or they read one catalog's subset and
    mismatch the aggregate summary on every run.

    ``catalogs`` is ``settings.resolved_catalogs()``. When it is falsy (the
    historical single-catalog callers and the direct-call unit tests), this
    falls back to the single ``summary["catalog"]`` so behavior is unchanged.
    Ids are normalized through ``contract.generate_id`` exactly as
    ``scoped_catalog`` does, for the same hyphen/space reason.
    """
    from dbxcarta.spark.contract import generate_id

    names = [c for c in (catalogs or []) if c]
    if not names:
        single = summary.get("catalog") or ""
        names = [single] if single else []
    ids = [generate_id(c) for c in names]
    return ids, [i + "." for i in ids]


@dataclass
class Report:
    run_id: str
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def format(self) -> str:
        if self.ok:
            return f"verify: run_id={self.run_id} OK ({len(self.violations)} violations)"
        lines = [f"verify: run_id={self.run_id} FAIL ({len(self.violations)} violations)"]
        for v in self.violations:
            lines.append(f"  [{v.code}] {v.message}")
            if v.details:
                lines.append(f"    {v.details}")
        return "\n".join(lines)


def verify_run(
    *,
    summary: dict[str, Any],
    neo4j_driver: Driver,
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
    sample_limit: int,
    catalogs: list[str] | None = None,
) -> Report:
    """Run every verify check against the given run summary; return one Report.

    ``catalog`` is the single primary catalog (still all the deferred
    information_schema sampling in ``catalog`` covers). ``catalogs`` is the
    full ``settings.resolved_catalogs()`` set; the count invariants scope to
    it so a multi-catalog run is verified against its aggregate summary
    totals. When ``catalogs`` is None the count checks fall back to the single
    ``summary["catalog"]``.
    """
    from dbxcarta.spark.verify import catalog as catalog_mod
    from dbxcarta.spark.verify import graph as graph_mod
    from dbxcarta.spark.verify import references as references_mod
    from dbxcarta.spark.verify import values as values_mod

    run_id = str(summary.get("run_id", ""))
    violations: list[Violation] = []

    violations.extend(_check_summary_shape(summary))
    violations.extend(graph_mod.check(neo4j_driver, summary, catalogs=catalogs))
    violations.extend(references_mod.check(neo4j_driver, summary, catalogs=catalogs))
    violations.extend(
        values_mod.check(neo4j_driver, summary, sample_limit=sample_limit, catalogs=catalogs)
    )
    violations.extend(
        catalog_mod.check(neo4j_driver, summary, ws=ws, warehouse_id=warehouse_id, catalog=catalog)
    )

    return Report(run_id=run_id, violations=violations)


def _check_summary_shape(summary: dict[str, Any]) -> list[Violation]:
    out: list[Violation] = []
    if summary.get("status") != "success":
        out.append(
            Violation(
                code="summary.status_not_success",
                message=f"Run status is {summary.get('status')!r}; verify only meaningful for successful runs.",
                details={"error": summary.get("error")},
            )
        )
    if not summary.get("run_id"):
        out.append(Violation(code="summary.missing_run_id", message="Run summary has no run_id."))
    if not summary.get("row_counts"):
        out.append(
            Violation(
                code="summary.missing_row_counts", message="Run summary has empty row_counts."
            )
        )
    return out


__all__ = [
    "Report",
    "Violation",
    "scoped_catalog",
    "scoped_catalogs",
    "single_value",
    "verify_run",
]
