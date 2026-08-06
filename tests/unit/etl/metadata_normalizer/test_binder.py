"""Unit tests for the record binder — the surface S1.1-S1.5 left missing.

The binder's whole claim is that it can be thin because the normalized records already own
renaming and coercion. These tests pin the parts that claim rests on: that raw pandas values
reach the contract's validators untouched, that non-pandas caches work, and that constant
injection and the two row-level hatches compose in a fixed order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pytest

from neocarta.etl.metadata_normalizer import (
    ConnectorMapping,
    SourceTable,
    bind,
    observed_columns,
)
from neocarta.etl.metadata_normalizer.binder import bind_table
from neocarta.etl.metadata_normalizer.normalized_schema import (
    ColumnRecord,
    DatabaseRecord,
    SchemaRecord,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# One column row per cluster, in each source's own vocabulary. The point is that none of these
# needs a rename: the ratified aliases already absorb all three spellings.
CLUSTER_ROWS: dict[str, dict[str, Any]] = {
    "bigquery": {
        "table_catalog": "proj",
        "table_schema": "ds",
        "table_name": "orders",
        "column_name": "id",
        "data_type": "INT64",
        "is_nullable": "YES",
    },
    "unity_catalog": {
        "catalog_name": "main",
        "schema_name": "sales",
        "table_name": "orders",
        "column_name": "id",
        "column_type": "INT",
        "nullable": True,
    },
    "dataplex": {
        "project_id": "proj",
        "dataset_id": "ds",
        "table_id": "orders",
        "column_name": "id",
        "column_data_type": "INTEGER",
        "column_mode": "REQUIRED",
    },
    "jdbc": {
        "database_name": "db",
        "schema_name": "public",
        "table_name": "orders",
        "column_name": "id",
        "type": "int4",
        "nullable": False,
    },
}


class TestNoRenamesNeeded:
    """Divergent source vocabularies bind onto canonical tokens with no mapping code."""

    @pytest.mark.parametrize("cluster", sorted(CLUSTER_ROWS))
    def test_container_and_type_resolve(self, cluster: str) -> None:
        record = bind([CLUSTER_ROWS[cluster]], ColumnRecord)[0]
        assert record.table_name == "orders"
        assert record.column_name == "id"
        assert record.data_type is not None
        assert record.schema_name in {"ds", "sales", "public"}

    @pytest.mark.parametrize(
        ("cluster", "expected"),
        [("bigquery", True), ("unity_catalog", True), ("dataplex", False), ("jdbc", False)],
    )
    def test_nullability_value_domain_is_coerced(self, cluster: str, expected: bool) -> None:
        """``YES``/``REQUIRED``/native bools all fold to a bool via the contract's validator."""
        assert bind([CLUSTER_ROWS[cluster]], ColumnRecord)[0].nullable is expected


class TestRawValuesReachTheValidators:
    """Pandas artefacts are passed through, not cleaned up on the way in.

    The contract's coercions (``coerce_str_or_none``, ``coerce_nullable``) are written to
    receive ``NaN`` and numpy scalars. Sanitizing in the binder would bypass them and put a
    second owner on value handling (GUIDE §4).
    """

    def test_nan_becomes_none_not_the_string_nan(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "database_name": "db",
                    "schema_name": "s",
                    "table_name": "t",
                    "column_name": "c",
                    "description": np.nan,
                }
            ]
        )
        assert bind(frame, ColumnRecord)[0].description is None

    def test_numpy_bool_is_accepted(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "database_name": "db",
                    "schema_name": "s",
                    "table_name": "t",
                    "column_name": "c",
                    "nullable": np.bool_(False),
                }
            ]
        )
        assert bind(frame, ColumnRecord)[0].nullable is False

    def test_an_unrecognised_nullability_token_is_rejected(self) -> None:
        """``REPEATED`` is refused rather than guessed at — the contract's documented stance.

        Note the error names the **alias** (``column_mode``), not the canonical field: the
        binder validates the source row as-is, so a connector author reading the failure sees
        the column they actually supplied. Dataplex's ``REPEATED`` mode is the listed S4
        reconciliation for this connector (``docs/refactor/field-vocabulary.md``).
        """
        with pytest.raises(ValueError, match="column_mode"):
            bind([{**CLUSTER_ROWS["dataplex"], "column_mode": "REPEATED"}], ColumnRecord)


class TestNonPandasSources:
    """A frame-first binder would exclude Unity Catalog by construction."""

    def test_a_list_of_typed_dicts_binds(self) -> None:
        rows = [CLUSTER_ROWS["unity_catalog"]]
        assert bind(rows, ColumnRecord)[0].database_name == "main"

    def test_none_yields_nothing(self) -> None:
        """An absent source is "this connector emits nothing here", not an error."""
        assert bind(None, ColumnRecord) == []

    def test_a_dict_shaped_cache_is_subscripted(self) -> None:
        cache = {"database_info": [{"database_name": "db"}]}
        table = SourceTable(record=DatabaseRecord, source="database_info")
        assert bind_table(cache, table)[0].database_name == "db"

    def test_a_cache_key_that_shadows_a_dict_method_still_resolves(self) -> None:
        """A mapping is read by key, never by attribute.

        Reading attributes first would resolve ``"items"`` to the bound ``dict.items`` method
        rather than the rows, and the resulting failure would be far from its cause.
        """
        cache = {"items": [{"database_name": "db"}]}
        table = SourceTable(record=DatabaseRecord, source="items")
        assert bind_table(cache, table)[0].database_name == "db"


class TestRowPreparationOrder:
    """Constant injection and the two row-level hatches apply in a fixed, documented order."""

    def test_constants_are_injected(self) -> None:
        record = bind([{"database_name": "db"}], DatabaseRecord, constants={"platform": "gcp"})[0]
        # Injected *before* validation, so the record's own `coerce_upper` still runs.
        assert record.platform == "GCP"

    def test_a_real_column_beats_a_declared_constant(self) -> None:
        """A source that reports its own platform is more specific than the declaration."""
        record = bind(
            [{"database_name": "db", "platform": "aws"}],
            DatabaseRecord,
            constants={"platform": "GCP"},
        )[0]
        assert record.platform == "AWS"

    def test_project_runs_after_constants(self) -> None:
        def project(row: dict[str, Any]) -> dict[str, Any]:
            return {**row, "schema_name": row["platform"].lower()}

        record = bind(
            [{"database_name": "db"}],
            SchemaRecord,
            constants={"platform": "GCP"},
            project=project,
        )[0]
        assert record.schema_name == "gcp"

    def test_row_filter_drops_before_validation(self) -> None:
        """A filtered row is never validated, so it need not even be a valid record."""
        rows: list[Mapping[str, Any]] = [{"database_name": "keep"}, {"nothing_valid": 1}]
        kept = bind(rows, DatabaseRecord, row_filter=lambda row: "database_name" in row)
        assert [record.database_name for record in kept] == ["keep"]


class TestMultiSourceTables:
    """One normalized table fed from several frames, in declared order."""

    def test_frames_concatenate_in_declaration_order(self) -> None:
        cache = {
            "first": [{"database_name": "a"}],
            "second": [{"database_name": "b"}],
        }
        table = SourceTable(record=DatabaseRecord, source=("first", "second"))
        assert [r.database_name for r in bind_table(cache, table)] == ["a", "b"]


class TestSparseDeclarations:
    """An undeclared table is absent, which is a different claim from empty (**D10**)."""

    def test_only_declared_tables_appear(self) -> None:
        from neocarta.etl.metadata_normalizer import bind_all

        mapping = ConnectorMapping(
            tables={"databases": SourceTable(record=DatabaseRecord, source="database_info")}
        )
        bound = bind_all({"database_info": [{"database_name": "db"}]}, mapping)
        assert set(bound) == {"databases"}


class TestObservedColumns:
    """``source_columns`` is half the component's output and the only input to a
    column-presence ``property_scope`` hatch — but the Layer R goldens cannot see it
    (``dump_records`` serializes only ``.records``), so its two documented semantics are
    pinned here."""

    def test_a_frame_reports_declared_columns_even_with_no_rows(self):
        """A header-only source must still report its columns.

        Otherwise a column-presence scope collapses to an empty allowlist for that family, which
        every layer downstream reads as "write the loader defaults" — a **D10** clobber.
        """
        mapping = ConnectorMapping(
            tables={"databases": SourceTable(record=DatabaseRecord, source="database_info")}
        )
        empty = pd.DataFrame(columns=["database_name", "platform", "service"])
        assert observed_columns({"database_info": empty}, mapping) == {
            "databases": ("database_name", "platform", "service")
        }

    def test_a_multi_source_table_de_duplicates_across_its_sources(self):
        """CSV feeds ``business_term_assignments`` from two frames that share most columns."""
        mapping = ConnectorMapping(
            tables={
                "databases": SourceTable(record=DatabaseRecord, source=("first", "second")),
            }
        )
        cache = {
            "first": pd.DataFrame(columns=["database_name", "platform"]),
            "second": pd.DataFrame(columns=["database_name", "service"]),
        }
        assert observed_columns(cache, mapping) == {
            "databases": ("database_name", "platform", "service")
        }


class TestRowPreparationOrderIsFixed:
    """``project`` runs before ``row_filter``, so a filter can test a derived field.

    The docstring promises this composition; without a test the two steps could be swapped in a
    refactor and every existing declaration would still pass, because none uses both hatches on
    one table.
    """

    def test_a_row_filter_sees_the_projected_row(self):
        kept = bind(
            [{"database_name": "a"}, {"database_name": "b"}],
            DatabaseRecord,
            project=lambda row: {**row, "keep": row["database_name"] == "a"},
            row_filter=lambda row: row["keep"],
        )
        assert [record.database_name for record in kept] == ["a"]
