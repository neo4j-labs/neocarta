"""Declared-FK counter shape and wire-key parity.

Counter names must match the existing row_counts wire shape except for
`fk_references` → `fk_edges` (the deliberate rename).
"""

from __future__ import annotations

from dbxcarta.spark.ingest.fk.declared import DeclaredCounters


def test_as_row_counts_keys_match_wire_shape() -> None:
    c = DeclaredCounters(fk_declared=10, fk_resolved=9, fk_skipped=1, fk_edges=12)
    assert c.as_row_counts() == {
        "fk_declared": 10,
        "fk_resolved": 9,
        "fk_skipped": 1,
        "fk_edges": 12,
    }


def test_accounting_invariant_held_by_caller() -> None:
    """DeclaredCounters doesn't enforce fk_skipped == fk_declared - fk_resolved
    itself — discover_declared sets the fields. Validates that the fields
    simply pass through so the caller-side invariant test stays meaningful."""
    c = DeclaredCounters(fk_declared=5, fk_resolved=3, fk_skipped=2, fk_edges=4)
    assert c.fk_skipped == c.fk_declared - c.fk_resolved
