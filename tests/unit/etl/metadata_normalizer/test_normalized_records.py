"""Layer R: golden-master the normalized records each connector's declaration produces.

The S1-band characterization target ``docs/testing/test-quality-inventory.md`` records —
*"golden-master the normalized schema each connector emits (the flat records) so the S1 split
holds parity"*.

**Three of these goldens predate this ticket.** ``bigquery_schema_records.json``,
``jdbc_schema_records.json`` and ``csv_records.json`` were captured by the S1.6 spike (#297) from a
throwaway prototype under ``tests/support/``. They are reproduced here **byte for byte** by the
production component, unchanged, which is the acceptance criterion for #298: the oracle was
committed before the code that now has to match it. The other two are new, captured from the same
production path.

Regenerate with ``UPDATE_GOLDENS=1 uv run pytest <path>``, and treat any diff without a matching
code change as a suspected regression (``docs/testing/characterization-harness.md``).
"""

from pathlib import Path

import pytest

from neocarta.etl.metadata_normalizer import normalize
from tests.support.characterization import assert_matches_golden, dump_records
from tests.support.connectors.offline import build_extractor
from tests.support.connectors.registry import BY_CONNECTOR

GOLDEN_DIR = Path(__file__).parent / "golden"

#: The three whose goldens were committed by S1.6, before the production component existed.
PRE_EXISTING = ("bigquery/schema", "jdbc/schema", "csv")


def golden_path(connector):
    """``bigquery/schema`` -> ``golden/bigquery_schema_records.json``, the S1.6 filenames."""
    return GOLDEN_DIR / f"{connector.replace('/', '_')}_records.json"


def records_for(connector):
    """Normalize one connector's offline extract through the production component."""
    return normalize(build_extractor(connector), BY_CONNECTOR[connector].mapping).records


class TestNormalizedRecordGoldens:
    """The records each connector's declaration produces, frozen."""

    def test_records_match_the_golden(self, connector):
        assert_matches_golden(golden_path(connector), dump_records(records_for(connector)))

    @pytest.mark.parametrize("pre_existing", PRE_EXISTING)
    def test_the_spike_goldens_are_reproduced_unchanged(self, pre_existing):
        """AC: the production component reproduces the pre-#298 oracle byte for byte.

        Stated separately from the sweep above because it is a different claim. The sweep says
        "output is frozen"; this says "output equals what a *different* implementation produced
        before this component was written", which is the only version of the claim that can fail
        for an interesting reason. ``update=False`` so a repo-wide regeneration run cannot
        quietly satisfy it.
        """
        path = golden_path(pre_existing)
        assert path.exists(), f"{pre_existing}'s S1.6 golden is missing"
        assert_matches_golden(path, dump_records(records_for(pre_existing)), update=False)


class TestGoldensCanFail:
    """Negative controls. A golden that cannot fail guards nothing."""

    def test_a_dropped_field_is_caught(self):
        """Removing one field from one record must break the comparison."""
        dumped = dump_records(records_for("bigquery/schema"))
        del dumped["columns"][0]["data_type"]
        with pytest.raises(AssertionError):
            assert_matches_golden(golden_path("bigquery/schema"), dumped, update=False)

    def test_a_reordered_table_is_caught(self):
        """Record order is contract behaviour, so reversing a table must break the comparison.

        Layer R preserves source order because it is deterministic connector output, and sorting
        it would hide an ordering regression.
        """
        dumped = dump_records(records_for("csv"))
        dumped["columns"].reverse()
        with pytest.raises(AssertionError):
            assert_matches_golden(golden_path("csv"), dumped, update=False)

    def test_a_dropped_table_is_caught(self):
        """An undeclared table is a different claim from an empty one (**D10**)."""
        dumped = dump_records(records_for("databricks/tags"))
        del dumped["governance_tag_values"]
        with pytest.raises(AssertionError):
            assert_matches_golden(golden_path("databricks/tags"), dumped, update=False)


class TestTheGoldenSetMatchesTheDeclaredSet:
    """One assertion covers both directions: a declaration with no golden, and the reverse.

    A golden left behind by a deleted declaration would silently stop being checked; a declaration
    with no golden would silently stop being guarded.
    """

    def test_goldens_and_declarations_correspond(self):
        expected = {golden_path(name).name for name in BY_CONNECTOR}
        found = {path.name for path in GOLDEN_DIR.glob("*_records.json")}
        assert found == expected


class TestNormalizingTwiceIsStable:
    """``normalize()`` assigns; it never accumulates.

    The spike's prototype originally appended, silently doubling every family on a second call.
    A connector's ``transform()`` is re-callable after a failed ``load()``, so this is reachable
    in normal use rather than theoretical.
    """

    def test_the_same_extract_normalizes_identically_twice(self, connector):
        extractor = build_extractor(connector)
        mapping = BY_CONNECTOR[connector].mapping
        first = dump_records(normalize(extractor, mapping).records)
        second = dump_records(normalize(extractor, mapping).records)
        assert first == second
