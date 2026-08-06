"""The declaration types: what they accept, and what they refuse at import time.

The two guards matter because both failure modes are otherwise silent and surface far from their
cause — a misspelled table binds rows nothing reads, and a mismatched record type produces rows
the bundle only rejects once someone projects it.
"""

import dataclasses

import pytest

from neocarta.errors import ConfigError
from neocarta.etl.metadata_normalizer import (
    TABLE_RECORD_TYPES,
    ConnectorMapping,
    SourceTable,
    hatch_usage,
)
from neocarta.etl.metadata_normalizer.normalized_schema import ColumnRecord, DatabaseRecord


class TestTableRecordTypes:
    """The table→record map is derived from the bundle, not restated."""

    def test_it_covers_every_contract_table(self):
        """Pinned as a literal, not against ``model_fields``.

        Comparing the derived map to the thing it is derived *from* is a tautology — both sides
        are the same expression — so it would stay green through any change to the bundle. The
        13 names are spelled out instead, which is what makes adding or renaming a table a
        decision somebody has to confirm here.
        """
        assert set(TABLE_RECORD_TYPES) == {
            "databases",
            "schemas",
            "tables",
            "columns",
            "foreign_keys",
            "values",
            "glossaries",
            "categories",
            "business_terms",
            "business_term_assignments",
            "governance_tag_keys",
            "governance_tag_values",
            "lineage",
        }


class TestDeclarationGuards:
    """A declaration the contract cannot hold fails when its module is imported."""

    def test_an_unknown_table_is_rejected(self):
        with pytest.raises(ConfigError, match=r"unknown normalized table 'colunms'"):
            ConnectorMapping(
                tables={"colunms": SourceTable(record=ColumnRecord, source="column_info")}
            )

    def test_the_error_lists_the_real_tables(self):
        """A typo is easiest to fix next to the correct spellings."""
        with pytest.raises(ConfigError, match="columns"):
            ConnectorMapping(tables={"colunms": SourceTable(record=ColumnRecord, source="x")})

    def test_a_mismatched_record_type_is_rejected(self):
        with pytest.raises(ConfigError, match=r"holds ColumnRecord.*binds DatabaseRecord"):
            ConnectorMapping(
                tables={"columns": SourceTable(record=DatabaseRecord, source="column_info")}
            )

    def test_a_record_subclass_is_accepted(self):
        """A connector may narrow a record; it may not substitute a different one."""

        class NarrowedColumn(ColumnRecord):
            pass

        mapping = ConnectorMapping(
            tables={"columns": SourceTable(record=NarrowedColumn, source="column_info")}
        )
        assert mapping.tables["columns"].record is NarrowedColumn


class TestSourceTable:
    """One source or many read the same downstream."""

    def test_a_single_source_normalizes_to_a_tuple(self):
        assert SourceTable(record=DatabaseRecord, source="database_info").sources == (
            "database_info",
        )

    def test_a_tuple_source_is_preserved_in_order(self):
        table = SourceTable(record=DatabaseRecord, source=("first", "second"))
        assert table.sources == ("first", "second")


class TestDeclarationsAreReplaceable:
    """Frozen dataclasses, so a test can vary one knob without rebuilding the declaration.

    Load-bearing: the S1.6 parity suite uses ``dataclasses.replace`` to prove the
    ``drop_self_references`` hatch actually changes output.
    """

    def test_replace_produces_a_valid_declaration(self):
        original = ConnectorMapping(
            tables={"databases": SourceTable(record=DatabaseRecord, source="database_info")},
            drop_self_references=True,
        )
        changed = dataclasses.replace(original, drop_self_references=False)
        assert changed.drop_self_references is False
        assert changed.tables == original.tables

    def test_replace_still_runs_the_guards(self):
        original = ConnectorMapping(
            tables={"databases": SourceTable(record=DatabaseRecord, source="database_info")}
        )
        with pytest.raises(ConfigError):
            dataclasses.replace(
                original, tables={"nope": SourceTable(record=DatabaseRecord, source="x")}
            )


class TestHatchUsage:
    """The gate metric's input: every hatch use is countable, unused hatches are omitted."""

    def test_no_hatches_counts_nothing(self):
        mapping = ConnectorMapping(
            tables={"databases": SourceTable(record=DatabaseRecord, source="database_info")}
        )
        assert hatch_usage(mapping) == {}

    def test_each_hatch_is_counted_under_its_own_name(self):
        mapping = ConnectorMapping(
            tables={
                "databases": SourceTable(
                    record=DatabaseRecord,
                    source="database_info",
                    project=lambda row: row,
                    row_filter=lambda _row: True,
                ),
                "columns": SourceTable(
                    record=ColumnRecord, source="column_info", project=lambda row: row
                ),
            },
            drop_self_references=True,
            property_scope=lambda _: [],
        )
        assert hatch_usage(mapping) == {
            "pre_fold": 2,
            "row_filter": 1,
            "drop_self_references": 1,
            "property_scope": 1,
        }

    def test_constants_are_not_a_hatch(self):
        """Literal injection is part of the declaration, not an escape from it."""
        mapping = ConnectorMapping(
            tables={
                "databases": SourceTable(
                    record=DatabaseRecord, source="database_info", constants={"platform": "GCP"}
                )
            }
        )
        assert hatch_usage(mapping) == {}
