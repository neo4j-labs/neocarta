"""REFERENCES (FK) edge invariants.

- Edge-count invariant: Neo4j REFERENCES count matches summary fk_edges.
- Accounting invariant: fk_skipped == fk_declared - fk_resolved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dbxcarta.spark.contract import NodeLabel, RelType
from dbxcarta.spark.verify import Violation, scoped_catalogs, single_value

if TYPE_CHECKING:
    from neo4j import Driver


def _expected_edge_total(summary: dict[str, Any]) -> int:
    """Total REFERENCES edges the writer is expected to have produced.

    The summary's `fk_edges` counter only counts *declared* FKs from the
    catalog; metadata-inferred FKs are tracked under a separate
    `fk_inferred_metadata_accepted` counter but are written to Neo4j as
    REFERENCES edges alongside the declared ones. Comparing `fk_edges` to
    Neo4j's REFERENCES count without summing the inferred total will always
    look high by `accepted` whenever inference is on (its default).
    """
    counts: dict[str, int] = summary.get("row_counts") or {}
    return counts.get("fk_edges", 0) + counts.get("fk_inferred_metadata_accepted", 0)


def check(
    driver: Driver, summary: dict[str, Any], *, catalogs: list[str] | None = None
) -> list[Violation]:
    out: list[Violation] = []
    out.extend(_check_edge_count(driver, summary, catalogs=catalogs))
    out.extend(_check_accounting(summary))
    return out


def _check_edge_count(
    driver: Driver, summary: dict[str, Any], *, catalogs: list[str] | None = None
) -> list[Violation]:
    """Neo4j's REFERENCES edge count must match declared + inferred FKs from
    the summary. A mismatch implies the Spark Connector dropped rows where an
    endpoint Column node did not exist.

    Scoped via the source Column's id prefix across every resolved catalog so
    a multi-catalog run is checked against its aggregate summary total, not
    one catalog's subset, and a shared Neo4j instance does not produce false
    positives.
    """
    _, prefixes = scoped_catalogs(summary, catalogs)
    expected = _expected_edge_total(summary)
    with driver.session() as s:
        edges = single_value(
            s.run(
                f"MATCH (src:{NodeLabel.COLUMN})-[r:{RelType.REFERENCES}]->()"
                " WHERE any(p IN $prefixes WHERE src.id STARTS WITH p)"
                " RETURN count(r) AS cnt",
                prefixes=prefixes,
            ),
            "cnt",
        )
    if edges != expected:
        return [
            Violation(
                code="references.edge_count_mismatch",
                message=f"Neo4j has {edges} REFERENCES edges; run summary reported {expected} (declared + inferred).",
                details={"neo4j": edges, "summary_total": expected},
            )
        ]
    return []


def _check_accounting(summary: dict[str, Any]) -> list[Violation]:
    """fk_skipped must equal fk_declared - fk_resolved; resolved <= declared; skipped >= 0."""
    counts = summary.get("row_counts") or {}
    declared = counts.get("fk_declared", 0)
    resolved = counts.get("fk_resolved", 0)
    skipped = counts.get("fk_skipped", 0)
    out: list[Violation] = []
    if skipped != declared - resolved:
        out.append(
            Violation(
                code="references.accounting_mismatch",
                message=f"fk_skipped ({skipped}) != fk_declared - fk_resolved ({declared} - {resolved}).",
                details={"declared": declared, "resolved": resolved, "skipped": skipped},
            )
        )
    if resolved > declared:
        out.append(
            Violation(
                code="references.resolved_exceeds_declared",
                message=f"fk_resolved ({resolved}) > fk_declared ({declared}).",
                details={"declared": declared, "resolved": resolved},
            )
        )
    if skipped < 0:
        out.append(
            Violation(
                code="references.skipped_negative",
                message=f"fk_skipped ({skipped}) is negative.",
                details={"skipped": skipped},
            )
        )
    return out
