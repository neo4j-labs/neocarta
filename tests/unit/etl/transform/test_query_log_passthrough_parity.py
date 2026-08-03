"""Parity: query_log needs no explicit-ID override (S1.4, #295).

`query_log` generates its ids in its own SQL parser and carries them on the frame rather
than taking them from a user, so the proof it owes is the **negative** one: every
structural id it emits is reproducible from the natural-key names on that same frame, and
its rows are therefore identity-agnostic. See ``docs/refactor/explicit-id-override.md``
for why that is the right framing rather than giving it an override.

Also pins the two projection traps those frames carry, and the D11 boundary.
"""

from __future__ import annotations

import pytest

from neocarta.connectors.query_log.utils import parse_sql_query
from neocarta.connectors.utils.generate_id import (
    generate_column_id,
    generate_schema_id,
    generate_table_id,
)
from neocarta.etl.metadata_normalizer.normalized_schema import (
    ColumnRecord,
    DatabaseRecord,
    SchemaRecord,
    TableRecord,
)
from neocarta.etl.transform import resolve_id

# A two-table join in the shape `connectors/query_log/extract.py` feeds the parser.
# Deliberately mixed-case and hyphenated so the `_normalize` fold inside the generated
# ids is actually exercised rather than being a no-op on already-normalized names.
QUERY = (
    "SELECT o.order_id, c.name "
    "FROM `My-Proj`.Sales.orders AS o "
    "JOIN `My-Proj`.Sales.customers AS c ON o.customer_id = c.id"
)
QUERY_ID = "qid-1"


def _parsed() -> dict[str, list[dict]]:
    """Drive the real parser — the same call `QueryLogExtractor` makes."""
    return parse_sql_query(QUERY, QUERY_ID, read="bigquery")


def _table_paths(parsed: dict[str, list[dict]]) -> dict[str, dict[str, str]]:
    """Map each generated ``table_id`` back to the raw natural key that produced it.

    The projection S4 owes: ``column_info`` carries only ``table_alias`` /
    ``table_name`` (which is the *alias*, not the table) plus the resolved
    ``table_id``, so a column's container path is recoverable only by joining back
    to ``table_info``.
    """
    return {
        row["table_id"]: {
            "database_name": row["project_name"],
            "schema_name": row["dataset_name"],
            "table_name": row["table_name"],
        }
        for row in parsed["table_info"]
    }


class TestEveryStructuralIdReproducesFromItsNaturalKey:
    """The negative proof: nothing here needs an override."""

    def test_table_ids_reproduce(self) -> None:
        for row in _parsed()["table_info"]:
            record = TableRecord.model_validate(
                {
                    "database_name": row["project_name"],
                    "schema_name": row["dataset_name"],
                    "table_name": row["table_name"],
                }
            )
            generated = generate_table_id(
                record.database_name, record.schema_name, record.table_name
            )
            assert resolve_id(record.explicit_id, generated) == row["table_id"]

    def test_schema_ids_reproduce(self) -> None:
        # `dataset_id` on the frame is a *generated schema id*, not a dataset name — see
        # TestRawFramesMustBeProjected below for why that distinction bites.
        for row in _parsed()["table_info"]:
            record = SchemaRecord.model_validate(
                {"database_name": row["project_name"], "schema_name": row["dataset_name"]}
            )
            generated = generate_schema_id(record.database_name, record.schema_name)
            assert resolve_id(record.explicit_id, generated) == row["dataset_id"]

    def test_column_ids_reproduce(self) -> None:
        parsed = _parsed()
        paths = _table_paths(parsed)
        for row in parsed["column_info"]:
            record = ColumnRecord.model_validate(
                {**paths[row["table_id"]], "column_name": row["column_name"]}
            )
            generated = generate_column_id(
                record.database_name, record.schema_name, record.table_name, record.column_name
            )
            # Production builds this from the *already generated* table_id
            # (`generate_column_id(*table_id.split("."), col)`); rebuilding from the raw names
            # agrees because `_normalize` is idempotent. That split also assumes no segment
            # contains a dot — a pre-existing parser limitation, not endorsed here.
            assert resolve_id(record.explicit_id, generated) == row["column_id"]

    def test_no_query_log_row_needs_an_override(self) -> None:
        # The headline claim as a whole-frame property across all three grains, so #305 can
        # generate these ids without changing any. `Database` is covered here rather than in its
        # own test because the frame carries no database id to compare against — an assertion
        # could only compare `generate_database_id` with itself.
        parsed = _parsed()
        paths = _table_paths(parsed)
        records = [
            *(
                DatabaseRecord.model_validate({"database_name": row["project_id"]})
                for row in parsed["table_info"]
            ),
            *(TableRecord.model_validate(path) for path in paths.values()),
            *(
                ColumnRecord.model_validate(
                    {**paths[row["table_id"]], "column_name": row["column_name"]}
                )
                for row in parsed["column_info"]
            ),
        ]
        assert records
        assert all(record.explicit_id is None for record in records)


class TestRawFramesMustBeProjected:
    """The connector projects; the contract does not absorb query-log column names."""

    def test_dataset_id_would_bind_as_a_schema_name(self) -> None:
        # `SCHEMA_NAME_SYNONYMS` absorbs `dataset_id` because in BigQuery/Dataplex frames
        # that column *is* the dataset name — but in query_log it is the generated schema
        # id, and the raw row carries neither `schema_name` nor `table_schema`, so a
        # direct validate binds "my_proj.sales" as the name and the id doubles up.
        raw = next(row for row in _parsed()["table_info"])
        assert SchemaRecord.model_validate(raw).schema_name == raw["dataset_id"]
        assert raw["dataset_id"] != raw["dataset_name"]

    def test_column_frame_table_name_is_an_alias(self) -> None:
        # `column_info.table_name` holds the SQL alias ("o"), not the table, and the frame
        # carries no container path at all — so a raw column row cannot even validate.
        parsed = _parsed()
        raw = parsed["column_info"][0]
        assert raw["table_name"] != _table_paths(parsed)[raw["table_id"]]["table_name"]
        with pytest.raises(ValueError, match="database_name"):
            ColumnRecord.model_validate(raw)
