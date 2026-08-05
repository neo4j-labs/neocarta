"""Seam 1: golden-master the normalized records each connector emits.

The S1-band characterization target ``docs/testing/test-quality-inventory.md`` records —
*"golden-master the normalized schema each connector emits (the flat records) so the S1 split
holds parity"* — captured here for the three connectors in the S1.6 (#297) proof set.

These goldens are the **permanent** half of this ticket. The prototype under
``tests/support/mapping_spike/`` is throwaway (#298 owns the production component), but the
records themselves are contract output: when S4 rewrites a connector to emit normalized
records directly, these files are what prove it emits the *same* ones. That is also why they
live in the production test tree while the mechanism does not.

Regenerate with ``UPDATE_GOLDENS=1 uv run pytest <path>``, and treat any diff without a
matching code change as a suspected regression (``docs/testing/characterization-harness.md``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.support.characterization import assert_matches_golden, dump_records
from tests.support.mapping_spike import bind_all

if TYPE_CHECKING:
    from .conftest import Case

_GOLDEN_DIR = Path(__file__).parent / "golden"


def _records(case: Case) -> dict[str, list]:
    """Bind one connector's sources into normalized records."""
    return bind_all(case.extractor, case.mapping)


class TestNormalizedRecordGoldens:
    """The records each connector's declaration produces, frozen."""

    def test_bigquery(self, bigquery_case: Case) -> None:
        assert_matches_golden(
            _GOLDEN_DIR / "bigquery_schema_records.json", dump_records(_records(bigquery_case))
        )

    def test_jdbc(self, jdbc_case: Case) -> None:
        assert_matches_golden(
            _GOLDEN_DIR / "jdbc_schema_records.json", dump_records(_records(jdbc_case))
        )

    def test_csv(self, csv_case: Case) -> None:
        assert_matches_golden(_GOLDEN_DIR / "csv_records.json", dump_records(_records(csv_case)))


class TestGoldensCanFail:
    """Negative controls. A golden that cannot fail guards nothing."""

    def test_a_dropped_field_is_caught(self, bigquery_case: Case) -> None:
        """Removing one field from one record must break the comparison."""
        records = _records(bigquery_case)
        dumped = dump_records(records)
        del dumped["columns"][0]["data_type"]
        with pytest.raises(AssertionError):
            assert_matches_golden(
                _GOLDEN_DIR / "bigquery_schema_records.json", dumped, update=False
            )

    def test_a_reordered_table_is_caught(self, csv_case: Case) -> None:
        """Record order is contract behaviour, so reversing a table must break the comparison.

        Layer R preserves source order for the same reason Layer A does: it is deterministic
        connector output, and sorting it would hide an ordering regression.
        """
        dumped = dump_records(_records(csv_case))
        dumped["columns"].reverse()
        with pytest.raises(AssertionError):
            assert_matches_golden(_GOLDEN_DIR / "csv_records.json", dumped, update=False)


class TestRecordsAreIdentityAgnostic:
    """The contract's own invariant, checked against real connector output.

    ``normalized_schema/models.py`` promises records are *"identity-agnostic by default"* — no
    graph ids beyond the opt-in **D6** override. Worth asserting on live records because every
    one of these three connectors has precomputed ``*_id`` columns in its frames, and the only
    thing stopping them binding is canonical-first alias ordering.
    """

    @pytest.mark.parametrize("case_name", ["bigquery_case", "jdbc_case", "csv_case"])
    def test_no_explicit_id_is_set(self, case_name: str, request) -> None:
        case: Case = request.getfixturevalue(case_name)
        for table, rows in dump_records(_records(case)).items():
            for row in rows:
                assert row.get("explicit_id") is None, f"{case.name}/{table}"

    def test_generated_ids_still_match_the_precomputed_ones(self, csv_case: Case) -> None:
        """CSV's frames carry precomputed ids, and the mechanism reproduces them by generation.

        The sharpest form of the identity-agnostic claim: CSV's extractor computes every
        ``*_id`` itself, the records ignore those columns entirely, and the graph output still
        matches the committed Layer A golden — so nothing is smuggling ids through the
        contract.
        """
        precomputed = set(csv_case.extractor.column_info["column_id"])
        generated = {node.id for node in csv_case.prototype.column_nodes}
        assert generated == precomputed
