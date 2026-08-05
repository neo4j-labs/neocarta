"""Layer R: serialize the normalized records a connector emits, before any graph shaping.

The third seam in this harness, and the one
``docs/testing/test-quality-inventory.md`` reserves for the S1 band: *"golden-master the
normalized schema each connector emits (the flat records) so the S1 split holds parity."*
Layer A freezes a connector's **graph** output and Layer B its **post-ingest** state; neither
can see the normalized contract in between, which is precisely the surface S1 introduced and
S4 will cut connectors over to.

Why it earns its own layer rather than folding into Layer A: the two answer different
questions. A Layer A diff says "the graph changed"; a Layer R diff says *where* — whether a
connector stopped supplying a field, or the record→graph mapping changed meaning. During the
S4 cutover, when connectors are rewritten one at a time, that distinction is the difference
between a five-minute fix and bisecting a whole pipeline.

Determinism matches Layer A exactly: record order is **preserved** (it is deterministic
connector behaviour derived from ordered sources, so sorting would hide an ordering
regression), and only dict keys are sorted, at serialization time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel


def dump_records(records: Mapping[str, list[BaseModel]]) -> dict[str, Any]:
    """Serialize bound normalized records to a canonical, golden-comparable dict.

    Args:
        records: Normalized table name → its records, in source order.

    Returns:
        A dict keyed by normalized table name, each value a list of
        ``model_dump(mode="json")`` dicts in source order. Tables are included even when
        empty, because "declared but produced nothing" and "not declared at all" are
        different claims under the sparse contract (**D10**) and a golden should show which
        one held.
    """
    return {
        table: [record.model_dump(mode="json") for record in rows]
        for table, rows in records.items()
    }
