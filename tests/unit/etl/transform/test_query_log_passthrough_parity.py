"""Parity: query_log needs no explicit-ID override, and why (S1.4, #295).

The ticket pairs `query_log` with `csv` as an "ID-passthrough" connector, but the two
are not the same thing and only one of them is an *override* case. `csv` passes through
ids **a user supplied**; `query_log` computes its own inside its SQL parser
(`connectors/query_log/utils.py`) with the very same `generate_*_id` functions and then
carries them on the frame, so `transform.py` reads `Table(id=row.table_id)` rather than
regenerating. That is generate-early-pass-later, not passthrough.

So the proof this file owes is the **negative** one: every structural id `query_log`
emits is exactly reproducible from the natural-key names on the same frame, so its rows
are identity-agnostic (`explicit_id is None`) and centralizing generation in #305 cannot
change a single id. Giving it an override would defeat the centralization D6 exists for.

Two boundaries this also pins: the raw frames must be **projected**, not validated
directly (the `dataset_id` / alias traps below), and the query paradigm's own ids are a
separate normalized surface (GUIDE D11) this contract deliberately does not model.
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
            # Production builds this id from the *already generated* table_id
            # (`generate_column_id(*table_id.split("."), col)`); rebuilding it from the
            # raw names agrees because `_normalize` is idempotent. Note that split also
            # assumes no key segment contains a dot — a pre-existing limitation of the
            # query-log parser, out of scope here and not endorsed by this test.
            assert resolve_id(record.explicit_id, generated) == row["column_id"]

    def test_no_query_log_row_needs_an_override(self) -> None:
        # The headline claim, stated once as a whole-frame property across all three grains:
        # every structural row the parser emits validates as an identity-agnostic record. So
        # `query_log` is not an override case, and #305 can generate its ids without changing
        # any of them. (`Database` has no id on the frame to compare against — its transform
        # already regenerates from `project_id` — so it is covered here rather than by an
        # assertion that could only compare `generate_database_id` with itself.)
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
