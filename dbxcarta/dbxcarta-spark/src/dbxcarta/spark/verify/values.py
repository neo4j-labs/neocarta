"""HAS_VALUE / Value-node invariants. Self-skips when the run had no Values."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from dbxcarta.spark.contract import NodeLabel, generate_value_id
from dbxcarta.spark.verify import Violation, scoped_catalogs, single_value

if TYPE_CHECKING:
    from neo4j import Driver


_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def check(
    driver: Driver,
    summary: dict[str, Any],
    *,
    sample_limit: int,
    catalogs: list[str] | None = None,
) -> list[Violation]:
    counts = summary.get("row_counts") or {}
    if counts.get("value_nodes", 0) == 0:
        return []
    out: list[Violation] = []
    out.extend(_check_value_count(driver, summary, catalogs=catalogs))
    out.extend(_check_sampling_accounting(summary))
    out.extend(_check_parent_column_type(driver))
    out.extend(_check_relationship_integrity(driver, sample_limit=sample_limit))
    out.extend(_check_value_id_shape(driver))
    return out


def _check_value_count(
    driver: Driver, summary: dict[str, Any], *, catalogs: list[str] | None = None
) -> list[Violation]:
    expected = (summary.get("row_counts") or {}).get("value_nodes")
    if expected is None:
        return []
    _, prefixes = scoped_catalogs(summary, catalogs)
    with driver.session() as s:
        actual = single_value(
            s.run(
                f"MATCH (n:{NodeLabel.VALUE})"
                " WHERE any(p IN $prefixes WHERE n.id STARTS WITH p)"
                " RETURN count(n) AS cnt",
                prefixes=prefixes,
            ),
            "cnt",
        )
    if actual != expected:
        return [
            Violation(
                code="values.count_mismatch",
                message=f"Neo4j has {actual} Value nodes; summary reported {expected}.",
                details={"neo4j": actual, "summary": expected},
            )
        ]
    return []


def _check_sampling_accounting(summary: dict[str, Any]) -> list[Violation]:
    rc = summary.get("row_counts") or {}
    sampled = rc.get("sampled_columns", 0)
    skipped = rc.get("skipped_columns", 0)
    candidate = rc.get("candidate_columns", 0)
    out: list[Violation] = []
    if sampled > candidate:
        out.append(
            Violation(
                code="values.sampled_exceeds_candidate",
                message=f"sampled_columns ({sampled}) > candidate_columns ({candidate}).",
                details={"sampled": sampled, "candidate": candidate},
            )
        )
    if sampled + skipped != candidate:
        out.append(
            Violation(
                code="values.sampled_plus_skipped_neq_candidate",
                message=f"sampled+skipped ({sampled}+{skipped}) != candidate ({candidate}).",
                details={"sampled": sampled, "skipped": skipped, "candidate": candidate},
            )
        )
    return out


def _check_parent_column_type(driver: Driver) -> list[Violation]:
    """Values only attach to STRING/BOOLEAN columns."""
    with driver.session() as s:
        bad = single_value(
            s.run(
                "MATCH (c:Column)-[:HAS_VALUE]->(:Value) "
                "WHERE NOT c.type IN ['STRING', 'BOOLEAN'] "
                "RETURN count(DISTINCT c) AS cnt"
            ),
            "cnt",
        )
    if bad:
        return [
            Violation(
                code="values.parent_column_wrong_type",
                message=f"{bad} Column node(s) with HAS_VALUE have type outside STRING/BOOLEAN.",
                details={"count": bad},
            )
        ]
    return []


def _check_relationship_integrity(driver: Driver, *, sample_limit: int) -> list[Violation]:
    """No orphan Value nodes; each Value has exactly one incoming HAS_VALUE;
    Column out-degree is bounded by `sample_limit` (the configured per-column cap).
    """
    out: list[Violation] = []
    with driver.session() as s:
        orphans = single_value(
            s.run(
                "MATCH (v:Value) WHERE NOT ( (:Column)-[:HAS_VALUE]->(v) ) RETURN count(v) AS cnt"
            ),
            "cnt",
        )
        if orphans:
            out.append(
                Violation(
                    code="values.orphan_value_node",
                    message=f"{orphans} Value node(s) have no incoming HAS_VALUE from a Column.",
                    details={"count": orphans},
                )
            )
        bad_in = single_value(
            s.run(
                "MATCH (v:Value) "
                "WITH v, size([ (c:Column)-[:HAS_VALUE]->(v) | c ]) AS in_cnt "
                "WHERE in_cnt <> 1 RETURN count(v) AS cnt"
            ),
            "cnt",
        )
        if bad_in:
            out.append(
                Violation(
                    code="values.value_multi_parent",
                    message=f"{bad_in} Value node(s) have incoming HAS_VALUE count != 1.",
                    details={"count": bad_in},
                )
            )
        over = single_value(
            s.run(
                "MATCH (c:Column)-[r:HAS_VALUE]->() "
                "WITH c, count(r) AS d WHERE d > $limit "
                "RETURN count(c) AS cnt",
                limit=sample_limit,
            ),
            "cnt",
        )
        if over:
            out.append(
                Violation(
                    code="values.column_outdegree_exceeds_limit",
                    message=f"{over} Column node(s) exceed {sample_limit} HAS_VALUE edges.",
                    details={"count": over, "limit": sample_limit},
                )
            )
    return out


def _check_value_id_shape(driver: Driver) -> list[Violation]:
    """Random sample of Value nodes: id == f'{column_id}.{md5(value)}'."""
    out: list[Violation] = []
    with driver.session() as s:
        rows = s.run(
            "MATCH (c:Column)-[:HAS_VALUE]->(v:Value) "
            "RETURN c.id AS col_id, v.id AS val_id, v.value AS val "
            "ORDER BY rand() LIMIT 20"
        ).data()
    if not rows:
        out.append(
            Violation(
                code="values.no_value_nodes_sampled",
                message="value_nodes > 0 in summary but no (Column)-[:HAS_VALUE]->(:Value) rows returned.",
            )
        )
        return out
    for row in rows:
        col_id, val_id, val = row["col_id"], row["val_id"], row["val"]
        expected = generate_value_id(col_id, val)
        if val_id != expected:
            out.append(
                Violation(
                    code="values.id_shape_mismatch",
                    message=f"Value id {val_id!r} != generate_value_id({col_id!r}, value).",
                    details={"col_id": col_id, "got": val_id, "expected": expected},
                )
            )
            continue
        if not val_id.startswith(col_id + "."):
            out.append(
                Violation(
                    code="values.id_missing_column_prefix",
                    message=f"Value id {val_id!r} missing column prefix.",
                    details={"col_id": col_id, "val_id": val_id},
                )
            )
            continue
        suffix = val_id[len(col_id) + 1 :]
        if not _HEX32.match(suffix):
            out.append(
                Violation(
                    code="values.id_suffix_not_md5",
                    message=f"Value id suffix {suffix!r} is not 32 hex chars.",
                    details={"col_id": col_id, "suffix": suffix},
                )
            )
    return out
