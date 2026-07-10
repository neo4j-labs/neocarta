"""Unit tests for the MetadataNormalizer engine."""

from pydantic import BaseModel, Field

from neocarta.data_model.normalized import (
    ColumnRecord,
    DatabaseRecord,
    InformationSchemaTable,
    NormalizedMetadata,
)
from neocarta.normalization import MetadataNormalizer, RecordMapping, Retriever


class _FakeRetriever:
    """In-memory retriever that streams canned rows per record type."""

    def __init__(self, data):
        self._data = data

    def stream(self, record_type):
        return list(self._data.get(record_type, []))


class _Widget(BaseModel):
    label: str
    size: int | None = None


class _WidgetTable(NormalizedMetadata):
    widgets: list[_Widget] = Field(default_factory=list)


def test_normalize_renames_and_constructs_in_order():
    """The engine renames source keys, constructs records, and preserves stream order."""
    spec = [
        RecordMapping(
            record_type="widget",
            target_model=_Widget,
            mappings=[("name", "label"), ("dim", "size")],
            container_field="widgets",
        ),
    ]
    fake = _FakeRetriever({"widget": [{"name": "x", "dim": 3}, {"name": "y", "dim": None}]})

    result = MetadataNormalizer(fake, spec, _WidgetTable).normalize()

    assert isinstance(result, NormalizedMetadata)
    assert isinstance(result, _WidgetTable)
    assert [w.label for w in result.widgets] == ["x", "y"]
    assert result.widgets[0].size == 3
    assert result.widgets[1].size is None


def test_normalize_empty_stream_yields_empty_list():
    """An empty stream produces an empty container field."""
    spec = [
        RecordMapping(
            record_type="widget",
            target_model=_Widget,
            mappings=[("name", "label")],
            container_field="widgets",
        ),
    ]
    fake = _FakeRetriever({"widget": []})

    result = MetadataNormalizer(fake, spec, _WidgetTable).normalize()

    assert result.widgets == []


def test_fake_retriever_satisfies_protocol():
    """The fake retriever satisfies the runtime-checkable Retriever protocol."""
    assert isinstance(_FakeRetriever({}), Retriever)


def test_normalize_information_schema_integration():
    """A concrete InformationSchemaTable is populated with renamed, coerced records."""
    spec = [
        RecordMapping(
            record_type="database",
            target_model=DatabaseRecord,
            mappings=[
                ("catalog", "database_name"),
                ("plat", "platform"),
                ("svc", "service"),
            ],
            container_field="databases",
        ),
        RecordMapping(
            record_type="column",
            target_model=ColumnRecord,
            mappings=[
                ("db", "database_name"),
                ("sch", "schema_name"),
                ("tbl", "table_name"),
                ("col", "column_name"),
                ("nullable", "is_nullable"),
            ],
            container_field="columns",
        ),
    ]
    fake = _FakeRetriever(
        {
            "database": [{"catalog": "mydb", "plat": "gcp", "svc": "bigquery"}],
            "column": [
                {"db": "mydb", "sch": "s", "tbl": "t", "col": "c", "nullable": "YES"},
            ],
        },
    )

    result = MetadataNormalizer(fake, spec, InformationSchemaTable).normalize()

    assert isinstance(result, InformationSchemaTable)
    # databases: renamed values, with layer-3 validators uppercasing platform/service.
    assert isinstance(result.databases[0], DatabaseRecord)
    assert result.databases[0].database_name == "mydb"
    assert result.databases[0].platform == "GCP"
    assert result.databases[0].service == "BIGQUERY"
    # columns: renamed values, with "YES" coerced to a bool.
    assert isinstance(result.columns[0], ColumnRecord)
    assert result.columns[0].column_name == "c"
    assert result.columns[0].is_nullable is True
    # container fields absent from the spec fall back to empty lists.
    assert result.schemas == []
    assert result.tables == []
    assert result.references == []
    assert result.values == []
