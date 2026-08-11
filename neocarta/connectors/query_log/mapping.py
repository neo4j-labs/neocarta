"""The query-log connector's normalized-schema mapping declaration.

The one connector whose rows are **fabricated by a SQL parser** rather than read from a catalog,
and therefore the one where the raw frames are furthest from the contract's vocabulary. It needs
four ``pre_fold`` projections — more than any other connector — and every one of them is exactly a
projection ``normalized_schema/README.md`` already says this connector owes.

**Two traps the vocabulary cannot save you from**, both pinned by
``tests/unit/etl/transform/test_query_log_passthrough_parity.py``:

1. ``dataset_id`` here is the *generated schema id* (``my_proj.sales``), **not** a dataset name —
   yet ``dataset_id`` is a ratified ``schema_name`` synonym, because in BigQuery and Dataplex
   frames that column really is the name. A raw row carries neither ``schema_name`` nor
   ``table_schema``, so without a projection it would bind the id as the name. The fix relies on
   the vocabulary's canonical-first rule: an injected ``schema_name`` wins over a present
   ``dataset_id``.
2. ``column_info.table_name`` is the SQL **alias** (``o``, ``c``), not the table. The frame
   carries no container path at all, so the path is recovered from ``column_id``.

Splitting a generated id and regenerating from the parts round-trips exactly, because
``generate_id``'s ``_normalize`` is idempotent. Verified end-to-end against real parser output.

**Documented exclusion (D11).** Five of this connector's 13 families — the query surface — have no
normalized table, exactly as CSV's do. 8 of 13 are covered here.
"""

from typing import Any

from neocarta.etl.metadata_normalizer import (
    ConnectorMapping,
    SourceTable,
    container_path_from,
    static_scope,
)
from neocarta.etl.metadata_normalizer.normalized_schema import (
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    SchemaRecord,
    TableRecord,
)


def _schema_name_from_dataset_name(row: dict[str, Any]) -> dict[str, Any]:
    """Bind the schema's real name, not its generated id.

    ``schema_info`` carries both ``dataset_id`` (the generated ``project.dataset`` id) and
    ``dataset_name`` (the name). Only the id is a ratified synonym, so the name has to be
    projected onto the canonical token to win.
    """
    return {**row, "schema_name": row["dataset_name"]}


#: ``table_info`` has no ``dataset_name`` column, so the schema name comes from the id's leaf. Its
#: ``project_id`` is a real name, though, so that segment is skipped and binds naturally.
_TABLE_CONTAINER_PATH = container_path_from("dataset_id", (None, "schema_name"))

#: ``column_info``'s ``table_name`` is a SQL alias, so the whole path comes from ``column_id`` —
#: whose fourth segment is the column itself, which the row already carries under its real name.
_COLUMN_CONTAINER_PATH = container_path_from(
    "column_id", ("database_name", "schema_name", "table_name"), id_segments=4
)

_SOURCE_ENDPOINT = container_path_from(
    "left_column_id",
    ("source_database_name", "source_schema_name", "source_table_name", "source_column_name"),
)
_TARGET_ENDPOINT = container_path_from(
    "right_column_id",
    ("target_database_name", "target_schema_name", "target_table_name", "target_column_name"),
)


def _foreign_key_endpoints(row: dict[str, Any]) -> dict[str, Any]:
    """Recover both endpoint paths from their ids.

    The reference frame names its endpoints ``left_*`` / ``right_*``, which are deliberately not
    absorbed as aliases — the query paradigm is a separate surface (**D11**) — so both paths are
    projected here, in one countable hatch use.
    """
    return _TARGET_ENDPOINT(_SOURCE_ENDPOINT(row))


QUERY_LOG = ConnectorMapping(
    tables={
        "databases": SourceTable(record=DatabaseRecord, source="database_info"),
        "schemas": SourceTable(
            record=SchemaRecord, source="schema_info", project=_schema_name_from_dataset_name
        ),
        "tables": SourceTable(
            record=TableRecord, source="table_info", project=_TABLE_CONTAINER_PATH
        ),
        "columns": SourceTable(
            record=ColumnRecord, source="column_info", project=_COLUMN_CONTAINER_PATH
        ),
        "foreign_keys": SourceTable(
            record=ForeignKeyRecord,
            source="column_references_info",
            project=_foreign_key_endpoints,
        ),
    },
    # Self-joins are already dropped upstream by the parser, so the hatch is not needed here.
    property_scope=static_scope(
        {
            "database_nodes": ["name", "service", "platform"],
            "schema_nodes": ["name"],
            "table_nodes": ["name"],
            "column_nodes": ["name"],
        }
    ),
)
