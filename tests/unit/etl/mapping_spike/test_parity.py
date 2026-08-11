"""AC-1: the candidate mapping mechanism reproduces today's output, byte for byte.

The S1.6 (#297) gate requires a chosen mechanism *demonstrated* to express the connector
matrix for ≥3 divergent connectors with byte-identical output via the #291 harness. This is
that demonstration, for ``bigquery/schema``, ``jdbc/schema`` and ``csv``.

The comparison is possible without building #298 because
``tests.support.characterization.serialize_transform`` is **duck-typed**: it reflects over
whatever ``*_nodes`` / ``*_relationships`` properties an object exposes. The prototype exposes
the same accessor names and emits the same legacy ``data_model`` classes, so today's committed
goldens are the oracle *unchanged*, and `test_bigquery_matches_the_committed_golden` compares
against the golden file on disk rather than only against a live re-run.

Byte-identity here means what it means everywhere else in this repo: equality of
``json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False) + "\\n"``
(``tests/support/characterization/golden.py``).

Each parity assertion is paired with a **sensitivity control** that injects a real change and
asserts the comparison notices — a parity test that cannot fail proves nothing
(``docs/testing/characterization-harness.md``).
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.support.characterization import canonical_json, serialize_transform
from tests.support.mapping_spike import CSV_EXCLUDED_FAMILIES, transformer_for

if TYPE_CHECKING:
    from .conftest import Case

_BIGQUERY_GOLDEN = (
    Path(__file__).parents[3]
    / "unit"
    / "connectors"
    / "bigquery"
    / "schema"
    / "golden"
    / "bigquery_schema_transform.json"
)


def _diff(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    """Render a unified diff of two serialized transform outputs."""
    return "".join(
        difflib.unified_diff(
            canonical_json(expected).splitlines(keepends=True),
            canonical_json(actual).splitlines(keepends=True),
            fromfile="hand-written transform",
            tofile="mapping mechanism",
        )
    )


def _shared_families(legacy: dict[str, Any], prototype: dict[str, Any]) -> list[str]:
    """The families both halves emit, excluding the property allowlist.

    ``_properties`` is compared separately and deliberately: Layer A only serializes it for a
    transformer exposing ``get_properties``, which JDBC does not, so folding it in here would
    make one connector's comparison silently weaker than another's.
    """
    return sorted((set(legacy) & set(prototype)) - {"_properties"})


def _assert_families_match(case: Case) -> None:
    """Assert every family both halves emit is byte-identical."""
    legacy, prototype = case.serialized()
    families = _shared_families(legacy, prototype)
    assert families, f"{case.name}: nothing was compared"
    expected = {family: legacy[family] for family in families}
    actual = {family: prototype[family] for family in families}
    assert canonical_json(expected) == canonical_json(actual), (
        f"{case.name} diverged:\n{_diff(expected, actual)}"
    )


class TestByteIdenticalOutput:
    """The mechanism's output equals the hand-written transform's, per connector."""

    def test_bigquery_matches_the_committed_golden(self, bigquery_case: Case) -> None:
        """The strongest form: equality with the golden **file**, not just a live re-run.

        Compares against ``bigquery_schema_transform.json`` as committed on ``main``, so the
        oracle is a frozen artifact no part of this change can influence.
        """
        produced = canonical_json(serialize_transform(bigquery_case.prototype))
        expected = _BIGQUERY_GOLDEN.read_text(encoding="utf-8")
        assert produced == expected, (
            "the mechanism diverged from the committed BigQuery golden:\n"
            + "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    produced.splitlines(keepends=True),
                    fromfile="committed golden",
                    tofile="mapping mechanism",
                )
            )
        )

    def test_bigquery_families_match(self, bigquery_case: Case) -> None:
        """All ten BigQuery families, including the filtered/self-FK-dropped references."""
        _assert_families_match(bigquery_case)

    def test_jdbc_families_match(self, jdbc_case: Case) -> None:
        """All eight JDBC families. It emits no ``Value`` nodes — SchemaCrawler samples none."""
        _assert_families_match(jdbc_case)

    def test_csv_families_match(self, csv_case: Case) -> None:
        """Every CSV family the tabular contract covers — 17 of them, glossary included."""
        _assert_families_match(csv_case)


class TestSparseAndExcludedSurfaces:
    """What the mechanism deliberately does *not* produce, asserted rather than assumed."""

    def test_jdbc_does_not_expose_value_families_at_all(self, jdbc_case: Case) -> None:
        """The sparse contract (**D10**) is structural, not an empty list.

        JDBC's declaration omits the ``values`` table because SchemaCrawler samples no data,
        so the generated transformer exposes **no** ``value_nodes`` accessor — matching
        ``JdbcSchemaTransformer``, which likewise has none. That distinction is load-bearing:
        an empty-but-present family would be serialized into Layer A output and no sparse
        connector could match its golden.
        """
        assert not hasattr(jdbc_case.prototype, "value_nodes")
        assert not hasattr(jdbc_case.prototype, "has_value_relationships")
        assert not hasattr(jdbc_case.legacy, "value_nodes")
        _, prototype = jdbc_case.serialized()
        # Eight families, plus the `_properties` allowlist the prototype adds and Layer A
        # cannot see on the legacy transformer (see TestPropertyScopeParity).
        assert len(_shared_families(prototype, prototype)) == 8

    def test_csv_query_families_are_excluded_not_forgotten(self, csv_case: Case) -> None:
        """CSV's query families have no normalized table at all, by **D11**.

        Named here so the CSV comparison is honestly reported as covering a subset. The query
        surface is a separate ingestion paradigm, listed under *"Not modelled (and why)"* in
        ``normalized_schema/README.md`` — not an omission in the declaration.
        """
        legacy, prototype = csv_case.serialized()
        uncovered = sorted(set(legacy) - set(prototype) - {"_properties"})
        assert uncovered, "expected CSV to have families outside the tabular contract"
        assert set(uncovered) <= set(CSV_EXCLUDED_FAMILIES), (
            f"CSV families outside the documented D11 exclusion list: {uncovered}"
        )


class TestPropertyScopeParity:
    """The **D10** layer-1 obligation, which Layer A cannot fully see.

    ``serialize_transform`` emits ``_properties`` only when the transformer exposes
    ``get_properties``. ``JdbcSchemaTransformer`` exposes ``get_database_properties`` /
    ``get_column_properties`` instead, so its allowlists never reach a Layer A golden. These
    tests compare against the production reductions directly, which is the only way to prove
    the mechanism owns property scope faithfully.
    """

    def test_jdbc_database_scope_matches(self, jdbc_case: Case) -> None:
        assert jdbc_case.prototype.get_properties("database_nodes") == (
            jdbc_case.legacy.get_database_properties()
        )

    def test_jdbc_column_scope_matches(self, jdbc_case: Case) -> None:
        assert jdbc_case.prototype.get_properties("column_nodes") == (
            jdbc_case.legacy.get_column_properties()
        )

    def test_jdbc_scope_is_not_the_trivial_answer(self, jdbc_case: Case) -> None:
        """Sensitivity: the JDBC fixture actually exercises the reduction both ways.

        ``description`` is unset on every column and so must be omitted, while
        ``is_primary_key`` is set on some and so must be kept. Without this, the two
        assertions above would pass just as happily against a constant list.
        """
        scope = jdbc_case.prototype.get_properties("column_nodes")
        assert "description" not in scope
        assert "is_primary_key" in scope

    def test_csv_scope_matches_every_family(self, csv_case: Case) -> None:
        """CSV's column-presence projection, family by family."""
        legacy, prototype = csv_case.serialized()
        for family, expected in legacy["_properties"].items():
            if family in CSV_EXCLUDED_FAMILIES:
                continue
            assert prototype["_properties"][family] == expected, family

    def test_csv_scope_is_derived_not_hardcoded(self, csv_case: Case) -> None:
        """Sensitivity: dropping a source column drops exactly its property.

        Re-scoping against a column list with ``description`` removed must change the answer;
        if it does not, the projection is not really reading the source header.
        """
        before = csv_case.prototype.get_properties("column_nodes")
        assert "description" in before
        csv_case.prototype._source_columns["columns"] = tuple(
            column
            for column in csv_case.prototype._source_columns["columns"]
            if column != "description"
        )
        assert "description" not in csv_case.prototype.get_properties("column_nodes")


class TestSensitivity:
    """Injected-change controls: the parity comparison must notice a real difference.

    Without these, every assertion above could be passing for the wrong reason — comparing
    two empty dicts, or two objects that happen to agree because neither does anything.
    """

    @pytest.mark.parametrize("case_name", ["bigquery_case", "jdbc_case", "csv_case"])
    def test_a_changed_id_rule_breaks_parity(self, case_name: str, request, monkeypatch) -> None:
        """Collapsing a production id helper must make the comparison fail, for each connector.

        The mechanism mints ids through the same ``generate_*_id`` functions today's
        transforms call, so patching one and rebuilding has to surface as a diff. Run per
        connector because a control that only covers BigQuery would leave the other two
        comparisons unguarded.
        """
        case: Case = request.getfixturevalue(case_name)
        monkeypatch.setattr(
            "tests.support.mapping_spike.transform.generate_table_id",
            lambda *_args, **_kwargs: "collapsed",
        )
        case.prototype = case.rebuild()
        with pytest.raises(AssertionError):
            _assert_families_match(case)

    def test_self_reference_hatch_actually_drops_a_row(self) -> None:
        """The ``drop_self_references`` hatch changes output on a self-referencing key.

        Driven from a hand-built record rather than a connector fixture, because none of the
        three committed fixtures contains a self-referencing foreign key — so asserting it
        through a connector would prove nothing. This is the guard three connectors duplicate
        today (BigQuery, JDBC, query-log), which one central transform can hold once.
        """
        from dataclasses import replace

        from neocarta.etl.metadata_normalizer.normalized_schema import (
            ForeignKeyRecord,
        )
        from tests.support.mapping_spike import JDBC_SCHEMA

        same_column = dict.fromkeys(
            (
                "source_database_name",
                "source_schema_name",
                "source_table_name",
                "source_column_name",
                "target_database_name",
                "target_schema_name",
                "target_table_name",
                "target_column_name",
            ),
            "x",
        )
        records = {"foreign_keys": [ForeignKeyRecord.model_validate(same_column)]}

        dropped = transformer_for(JDBC_SCHEMA).transform(records)
        kept = transformer_for(replace(JDBC_SCHEMA, drop_self_references=False)).transform(records)

        assert dropped.references_relationships == []
        assert len(kept.references_relationships) == 1


class TestRecordsAreIdentityAgnostic:
    """CSV's frames carry precomputed ids, and the mechanism reproduces them by *generation*.

    The sharpest form of the identity-agnostic claim, and the reason it lives here rather than
    with the Layer R goldens: it needs both halves at once — the records must ignore the
    extractor's `*_id` columns, *and* the graph the transform builds from them must still land on
    those exact ids. Only the prototype half has node ids to compare.
    """

    def test_generated_ids_still_match_the_precomputed_ones(self, csv_case: Case) -> None:
        precomputed = set(csv_case.extractor.column_info["column_id"])
        generated = {node.id for node in csv_case.prototype.column_nodes}
        assert generated == precomputed
