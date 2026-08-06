"""The component facade: what it returns, and why it returns two shapes of it.

The distinction these tests protect is **D10**. ``records`` is sparse — only declared tables
appear — so *"this connector does not produce that"* and *"it produced nothing this run"* stay
different claims. ``as_schema()`` projects onto the ratified bundle, whose 13 tables all default
to ``[]`` and therefore cannot express the difference. Keeping the bundle as the state would
silently widen every connector to the full contract.
"""

from typing import ClassVar

import pytest

from neocarta.errors import ConfigError
from neocarta.etl.metadata_normalizer import (
    ConnectorMapping,
    NormalizedRecords,
    SourceTable,
    normalize,
)
from neocarta.etl.metadata_normalizer.normalized_schema import (
    ColumnRecord,
    DatabaseRecord,
    NormalizedStructuralSchema,
)

SPARSE = ConnectorMapping(
    tables={"databases": SourceTable(record=DatabaseRecord, source="database_info")}
)
CACHE = {"database_info": [{"database_name": "db"}]}


class TestNormalize:
    """A cache in, normalized-schema output out."""

    def test_it_binds_the_declared_tables(self):
        output = normalize(CACHE, SPARSE)
        assert [record.database_name for record in output.records["databases"]] == ["db"]

    def test_it_captures_the_source_columns(self):
        output = normalize(CACHE, SPARSE)
        assert output.source_columns == {"databases": ("database_name",)}

    def test_it_reads_an_extractor_by_attribute(self):
        class Extractor:
            database_info: ClassVar[list[dict[str, str]]] = [{"database_name": "db"}]

        output = normalize(Extractor(), SPARSE)
        assert len(output.records["databases"]) == 1

    def test_a_missing_source_is_not_silently_empty(self):
        """A declared source that the cache does not have is a wiring bug, not zero rows."""
        with pytest.raises((KeyError, AttributeError)):
            normalize({"wrong_key": []}, SPARSE)


class TestSparseness:
    """**D10**: absent and empty are different claims."""

    def test_only_declared_tables_appear_in_records(self):
        output = normalize(CACHE, SPARSE)
        assert tuple(output.records) == ("databases",)

    def test_a_declared_but_empty_table_still_appears(self):
        mapping = ConnectorMapping(
            tables={
                "databases": SourceTable(record=DatabaseRecord, source="database_info"),
                "columns": SourceTable(record=ColumnRecord, source="column_info"),
            }
        )
        output = normalize({**CACHE, "column_info": []}, mapping)
        assert output.records["columns"] == []
        assert "columns" in output.records

    def test_declaration_order_is_preserved(self):
        mapping = ConnectorMapping(
            tables={
                "columns": SourceTable(record=ColumnRecord, source="column_info"),
                "databases": SourceTable(record=DatabaseRecord, source="database_info"),
            }
        )
        output = normalize({**CACHE, "column_info": []}, mapping)
        assert tuple(output.records) == ("columns", "databases")


class TestAsSchema:
    """The projection onto the ratified bundle."""

    def test_it_returns_the_contract_type(self):
        schema = normalize(CACHE, SPARSE).as_schema()
        assert isinstance(schema, NormalizedStructuralSchema)

    def test_declared_rows_survive_the_projection(self):
        schema = normalize(CACHE, SPARSE).as_schema()
        assert [record.database_name for record in schema.databases] == ["db"]

    def test_undeclared_tables_become_empty_lists(self):
        """The documented cost of the projection: the bundle cannot say "not declared"."""
        schema = normalize(CACHE, SPARSE).as_schema()
        assert schema.columns == []
        assert schema.governance_tag_keys == []

    def test_the_projection_loses_the_sparseness_the_records_keep(self):
        """Stated as a test so the tradeoff cannot be quietly forgotten."""
        output = normalize(CACHE, SPARSE)
        assert set(output.records) == {"databases"}
        assert len(output.as_schema().model_dump()) == len(NormalizedStructuralSchema.model_fields)


class TestNormalizedRecordsRejectsAnUnknownTable:
    """The guard on the path ``ConnectorMapping`` cannot reach.

    ``as_schema()`` projects through ``NormalizedStructuralSchema(**records)`` and pydantic ignores
    unknown keys, so a mis-keyed table would vanish with nothing raised. The declaration path is
    guarded at import; **S3** builds this type directly, which is the path that guard misses.
    """

    def test_a_misspelled_table_raises(self):
        with pytest.raises(ConfigError, match="unknown normalized table"):
            NormalizedRecords(records={"databses": []}, source_columns={})

    def test_records_would_otherwise_vanish_silently(self):
        """The failure this prevents: pydantic drops the unknown key without complaint."""
        from neocarta.etl.metadata_normalizer.normalized_schema import NormalizedStructuralSchema

        assert NormalizedStructuralSchema(colunms=[1, 2, 3]).columns == []


class TestNormalizedRecordsIsInert:
    """The result is a value, not a handle on the extractor."""

    def test_it_is_frozen(self):
        output = normalize(CACHE, SPARSE)
        with pytest.raises(AttributeError):
            output.records = {}

    def test_it_can_be_built_directly(self):
        """S3 consumes this shape, so it has to be constructible without a normalizer."""
        output = NormalizedRecords(records={"databases": []}, source_columns={})
        assert output.as_schema().databases == []
