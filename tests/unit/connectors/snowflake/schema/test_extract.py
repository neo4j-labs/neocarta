import logging
from unittest.mock import MagicMock

import pandas as pd
import pytest

from neocarta.connectors.snowflake import _errors
from neocarta.connectors.snowflake._errors import _classify, wrap_snowflake_errors
from neocarta.connectors.snowflake.schema.extract import (
    SnowflakeSchemaExtractor,
    _parse_array_cell,
    _quote_identifier,
)
from neocarta.connectors.utils.generate_id import generate_column_id, generate_value_id
from neocarta.errors import ConfigError, ExtractionError, StateError

DATABASE = "test_database"
SCHEMA = "test_schema"

# Column layout of a SHOW IMPORTED KEYS result (subset actually consumed).
_IMPORTED_KEYS_COLUMNS = [
    "pk_database_name",
    "pk_schema_name",
    "pk_table_name",
    "pk_column_name",
    "fk_database_name",
    "fk_schema_name",
    "fk_table_name",
    "fk_column_name",
    "key_sequence",
]


def _capture_connection(frame: pd.DataFrame) -> MagicMock:
    """A connection whose cursor returns ``frame`` from fetch_pandas_all."""
    connection = MagicMock()
    connection.cursor.return_value.fetch_pandas_all.return_value = frame
    return connection


def _show_connection(rows: list[tuple], columns: list[str]) -> MagicMock:
    """A connection whose cursor returns ``rows`` (SHOW output) with ``columns`` headers."""
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = rows
    cursor.description = [(col,) for col in columns]
    return connection


# --- cached-property tests ------------------------------------------------------


def test_get_database_info(snowflake_extractor_with_cache: SnowflakeSchemaExtractor):
    """database_info property returns cached data."""
    assert snowflake_extractor_with_cache.database_info.shape[0] == 1
    assert snowflake_extractor_with_cache.database_info.iloc[0]["database"] == DATABASE


def test_get_schema_info(snowflake_extractor_with_cache: SnowflakeSchemaExtractor):
    """schema_info property returns cached data."""
    assert snowflake_extractor_with_cache.schema_info.shape[0] == 1
    assert snowflake_extractor_with_cache.schema_info.iloc[0]["schema_name"] == SCHEMA


def test_get_table_info(snowflake_extractor_with_cache: SnowflakeSchemaExtractor):
    """table_info property returns cached data."""
    assert snowflake_extractor_with_cache.table_info.shape[0] == 2
    assert snowflake_extractor_with_cache.table_info.iloc[0]["table_name"] == "customers"


def test_get_column_info(snowflake_extractor_with_cache: SnowflakeSchemaExtractor):
    """column_info property returns cached data with key flags."""
    column_info = snowflake_extractor_with_cache.column_info
    assert column_info.shape[0] == 4
    assert bool(column_info.iloc[0]["is_primary_key"]) is True
    assert bool(column_info.iloc[3]["is_foreign_key"]) is True


def test_get_column_references_info(snowflake_extractor_with_cache: SnowflakeSchemaExtractor):
    """column_references_info property returns cached data."""
    assert snowflake_extractor_with_cache.column_references_info.shape[0] == 1
    assert snowflake_extractor_with_cache.column_references_info.iloc[0]["table_name"] == "orders"


def test_get_column_unique_values(snowflake_extractor_with_cache: SnowflakeSchemaExtractor):
    """column_unique_values property returns cached data."""
    assert snowflake_extractor_with_cache.column_unique_values.shape[0] == 2


# --- DB-API / cursor lifecycle --------------------------------------------------


def test_run_query_returns_dataframe():
    """_run_query executes on a cursor and returns fetch_pandas_all as pandas."""
    connection = MagicMock()
    expected = pd.DataFrame([{"a": 1}])
    connection.cursor.return_value.fetch_pandas_all.return_value = expected

    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)
    out = extractor._run_query("SELECT 1", {"x": "y"})

    assert out.equals(expected)
    connection.cursor.return_value.execute.assert_called_once_with("SELECT 1", {"x": "y"})
    connection.cursor.return_value.close.assert_called_once()


def test_run_query_closes_cursor_on_error():
    """_run_query closes the cursor even when execute raises."""
    connection = MagicMock()
    connection.cursor.return_value.execute.side_effect = RuntimeError("boom")

    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)
    with pytest.raises(RuntimeError, match="boom"):
        extractor._run_query("SELECT 1")

    connection.cursor.return_value.close.assert_called_once()


def test_run_show_builds_dataframe_with_lowercased_headers():
    """_run_show assembles fetchall rows using lower-cased description column names."""
    conn = _show_connection([("orders", "customer_id")], ["FK_TABLE_NAME", "FK_COLUMN_NAME"])
    extractor = SnowflakeSchemaExtractor(connection=conn, database=DATABASE)
    df = extractor._run_show("SHOW IMPORTED KEYS")
    assert list(df.columns) == ["fk_table_name", "fk_column_name"]
    assert df.iloc[0]["fk_table_name"] == "orders"
    conn.cursor.return_value.close.assert_called_once()


# --- identifier quoting ---------------------------------------------------------


def test_quote_identifier_wraps_in_double_quotes():
    """Identifiers are double-quoted (Snowflake quoting)."""
    assert _quote_identifier("my_database") == '"my_database"'


def test_quote_identifier_rejects_double_quote():
    """An identifier containing a double-quote is a configuration error."""
    with pytest.raises(ConfigError):
        _quote_identifier('evil"database')


def test_constructor_rejects_double_quote_database():
    """A database name containing a double-quote is rejected up front, at construction."""
    with pytest.raises(ConfigError):
        SnowflakeSchemaExtractor(connection=MagicMock(), database='evil"database')


# --- construction guards --------------------------------------------------------


def test_extractor_requires_connection():
    """A missing connection is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeSchemaExtractor(connection=None, database=DATABASE)


def test_extractor_requires_database():
    """A missing database is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeSchemaExtractor(connection=MagicMock(), database="")


# --- database scoping (regression guard) ----------------------------------------


def test_extract_schema_info_is_database_scoped():
    """The schema query filters by database and binds both database and schema."""
    conn = _capture_connection(
        pd.DataFrame([{"catalog_name": "db", "schema_name": "sch", "description": None}])
    )
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    ex.extract_schema_info("sch")
    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "INFORMATION_SCHEMA.SCHEMATA" in sql
    assert "CATALOG_NAME = %(database)s" in sql
    assert params == {"database": "db", "schema": "sch"}


def test_extract_schema_info_missing_schema_raises_config_error():
    """An empty schemata result is a config error, not a synthesized schema row."""
    conn = _capture_connection(
        pd.DataFrame({"catalog_name": [], "schema_name": [], "description": []})
    )
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    with pytest.raises(ConfigError, match="not found"):
        ex.extract_schema_info("ghost")


def test_extract_table_info_is_database_scoped():
    """The table query filters by database and binds both database and schema."""
    conn = _capture_connection(
        pd.DataFrame(
            {
                "table_catalog": [],
                "table_schema": [],
                "table_name": [],
                "table_type": [],
                "description": [],
            }
        )
    )
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    ex.extract_table_info("sch")
    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "INFORMATION_SCHEMA.TABLES" in sql
    assert "TABLE_CATALOG = %(database)s" in sql
    assert params == {"database": "db", "schema": "sch"}


def test_extract_column_info_columns_query_is_database_scoped():
    """The columns query filters by database, and SHOW ... KEYS derive the key flags."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetch_pandas_all.return_value = pd.DataFrame(
        {
            "table_catalog": ["db"],
            "table_schema": ["sch"],
            "table_name": ["t"],
            "column_name": ["a"],
            "is_nullable": ["NO"],
            "data_type": ["NUMBER"],
            "description": [None],
        }
    )
    # Both SHOW ... KEYS calls return no rows (no declared keys).
    cursor.fetchall.return_value = []
    cursor.description = [("table_name",), ("column_name",)]
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    ex.extract_column_info("sch")

    columns_sql, columns_params = cursor.execute.call_args_list[0][0]
    assert "INFORMATION_SCHEMA.COLUMNS" in columns_sql
    assert "TABLE_CATALOG = %(database)s" in columns_sql
    assert columns_params == {"database": "db", "schema": "sch"}
    show_sqls = [call[0][0] for call in cursor.execute.call_args_list[1:]]
    assert any("SHOW PRIMARY KEYS" in s for s in show_sqls)
    assert any("SHOW IMPORTED KEYS" in s for s in show_sqls)


def test_extract_key_columns_reads_show_output():
    """_extract_key_columns reads PK / FK (table, column) pairs from SHOW output."""
    ex = SnowflakeSchemaExtractor(connection=MagicMock(), database="db")
    pk_df = pd.DataFrame([{"table_name": "customers", "column_name": "customer_id"}])
    fk_df = pd.DataFrame([{"fk_table_name": "orders", "fk_column_name": "customer_id"}])
    ex._run_show = lambda sql: pk_df if "PRIMARY" in sql else fk_df
    pk, fk = ex._extract_key_columns("sch")
    assert ("customers", "customer_id") in pk
    assert ("orders", "customer_id") in fk


def test_extract_column_info_derives_key_flags():
    """extract_column_info sets is_primary_key / is_foreign_key from the SHOW-derived sets."""
    conn = _capture_connection(
        pd.DataFrame(
            {
                "table_catalog": ["db", "db"],
                "table_schema": ["sch", "sch"],
                "table_name": ["customers", "orders"],
                "column_name": ["customer_id", "customer_id"],
                "is_nullable": ["NO", "NO"],
                "data_type": ["NUMBER", "NUMBER"],
                "description": [None, None],
            }
        )
    )
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    ex._extract_key_columns = lambda _schema: (
        {("customers", "customer_id")},
        {("orders", "customer_id")},
    )
    df = ex.extract_column_info("sch")
    assert bool(df[df["table_name"] == "customers"]["is_primary_key"].iloc[0]) is True
    assert bool(df[df["table_name"] == "orders"]["is_foreign_key"].iloc[0]) is True


def test_extract_column_info_empty_schema_yields_empty_key_flags():
    """An empty columns result still produces is_primary_key / is_foreign_key columns."""
    conn = _capture_connection(
        pd.DataFrame(
            {
                "table_catalog": [],
                "table_schema": [],
                "table_name": [],
                "column_name": [],
                "is_nullable": [],
                "data_type": [],
                "description": [],
            }
        )
    )
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    df = ex.extract_column_info("sch")
    assert df.empty
    assert "is_primary_key" in df.columns
    assert "is_foreign_key" in df.columns


def test_extract_column_info_normalizes_is_nullable_to_bool():
    """The 'YES'/'NO' nullability flag is normalized to a real boolean."""
    conn = _capture_connection(
        pd.DataFrame(
            {
                "table_catalog": ["db", "db"],
                "table_schema": ["sch", "sch"],
                "table_name": ["t", "t"],
                "column_name": ["a", "b"],
                "is_nullable": ["NO", "YES"],
                "data_type": ["NUMBER", "TEXT"],
                "description": [None, None],
            }
        )
    )
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    ex._extract_key_columns = lambda _schema: (set(), set())
    df = ex.extract_column_info("sch")
    assert df["is_nullable"].tolist() == [False, True]
    assert df["is_nullable"].dtype == bool


# --- references (SHOW IMPORTED KEYS) --------------------------------------------


def test_extract_references_from_show_imported_keys():
    """The references frame is built from SHOW IMPORTED KEYS, mapped to the core shape."""
    rows = [("db", "sch", "customers", "customer_id", "db", "sch", "orders", "customer_id", 1)]
    conn = _show_connection(rows, _IMPORTED_KEYS_COLUMNS)
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    out = ex.extract_column_references_info("sch")
    assert len(out) == 1
    row = out.iloc[0]
    assert row["constraint_type"] == "FOREIGN KEY"
    assert row["table_name"] == "orders"
    assert row["column_name"] == "customer_id"
    assert row["referenced_table"] == "customers"
    assert row["referenced_column"] == "customer_id"
    sql = conn.cursor.return_value.execute.call_args[0][0]
    assert "SHOW IMPORTED KEYS" in sql


def test_extract_references_empty_when_no_foreign_keys():
    """A schema with no imported keys yields an empty, well-formed references frame."""
    conn = _show_connection([], _IMPORTED_KEYS_COLUMNS)
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    out = ex.extract_column_references_info("sch")
    assert out.empty
    assert "referenced_table" in out.columns


def test_extract_references_drops_cross_database_fk_and_warns(caplog):
    """A foreign key whose referenced table lives in another database is dropped, with a warning."""
    rows = [
        ("db", "sch", "customers", "customer_id", "db", "sch", "orders", "customer_id", 1),
        ("OTHERDB", "sch", "external", "id", "db", "sch", "orders", "ext_id", 1),
    ]
    conn = _show_connection(rows, _IMPORTED_KEYS_COLUMNS)
    ex = SnowflakeSchemaExtractor(connection=conn, database="db")
    with caplog.at_level(logging.WARNING):
        out = ex.extract_column_references_info("sch")
    assert len(out) == 1
    assert out.iloc[0]["referenced_table"] == "customers"
    assert any(
        "cross-database" in r.message or "outside database" in r.message for r in caplog.records
    )


@pytest.mark.parametrize("bad", [-1, True, 2.5])
def test_extractor_rejects_invalid_value_sample_limit(bad):
    """A non-(plain-int) / negative value_sample_limit is rejected at construction."""
    with pytest.raises(ConfigError):
        SnowflakeSchemaExtractor(connection=MagicMock(), database="db", value_sample_limit=bad)


# --- value sampling -------------------------------------------------------------


def test_value_sampling_parses_json_array_and_uses_generate_value_id():
    """Sampled JSON-array cells are parsed and value ids come from generate_value_id."""
    connection = _capture_connection(pd.DataFrame({"customer_id": ['["1", "2"]']}))
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)

    result = extractor.extract_column_unique_values_for_table(
        "customers", ["customer_id"], SCHEMA, cache=False
    )

    assert list(result["unique_value"]) == ["1", "2"]
    assert result.iloc[0]["column_id"] == generate_column_id(
        DATABASE, SCHEMA, "customers", "customer_id"
    )
    assert result.iloc[0]["value_id"] == generate_value_id(
        DATABASE, SCHEMA, "customers", "customer_id", "1"
    )


def test_value_sampling_uses_array_agg_and_skips_complex_types():
    """VARIANT/OBJECT/ARRAY columns are excluded from the ARRAY_AGG sampling query."""
    connection = _capture_connection(pd.DataFrame({"customer_id": ['["1"]']}))
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)
    column_info = pd.DataFrame(
        [
            {"table_name": "customers", "column_name": "customer_id", "data_type": "NUMBER"},
            {"table_name": "customers", "column_name": "attrs", "data_type": "VARIANT"},
        ]
    )

    extractor.extract_column_unique_values_for_table(
        "customers", ["customer_id", "attrs"], SCHEMA, cache=False, column_info=column_info
    )

    executed_sql = connection.cursor.return_value.execute.call_args[0][0]
    assert "ARRAY_AGG" in executed_sql
    assert '"customer_id"' in executed_sql
    assert '"attrs"' not in executed_sql


def test_value_sampling_skips_vector_and_structured_types():
    """VECTOR / MAP / OBJECT / GEOGRAPHY columns are excluded from the ARRAY_AGG query.

    Regression for a live-confirmed bug: a Snowflake VECTOR column (embeddings) is
    non-groupable, so ``ARRAY_AGG(DISTINCT <vector>)`` aborts the whole query with an
    internal 300010 error — which would poison value sampling for the entire table.
    Only the sampleable scalar column must appear in the generated SELECT.
    """
    connection = _capture_connection(pd.DataFrame({"nodeid": ['["1", "2"]']}))
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)
    column_info = pd.DataFrame(
        [
            {"table_name": "embeddings", "column_name": "nodeid", "data_type": "NUMBER"},
            {"table_name": "embeddings", "column_name": "vec", "data_type": "VECTOR"},
            {"table_name": "embeddings", "column_name": "attrs", "data_type": "OBJECT"},
            {"table_name": "embeddings", "column_name": "tags", "data_type": "MAP"},
            {"table_name": "embeddings", "column_name": "geo", "data_type": "GEOGRAPHY"},
        ]
    )
    extractor.extract_column_unique_values_for_table(
        "embeddings",
        ["nodeid", "vec", "attrs", "tags", "geo"],
        SCHEMA,
        cache=False,
        column_info=column_info,
    )
    sql = connection.cursor.return_value.execute.call_args[0][0]
    assert '"nodeid"' in sql  # sampleable scalar still sampled
    for skipped in ('"vec"', '"attrs"', '"tags"', '"geo"'):
        assert skipped not in sql, f"{skipped} (non-groupable) must be skipped"


def test_value_sampling_disabled_skips_query():
    """value_sample_limit=0 returns an empty frame and runs no query."""
    connection = MagicMock()
    extractor = SnowflakeSchemaExtractor(
        connection=connection, database=DATABASE, value_sample_limit=0
    )

    result = extractor.extract_column_unique_values_for_table(
        "customers", ["customer_id"], SCHEMA, cache=False
    )

    assert result.empty
    connection.cursor.assert_not_called()


@pytest.mark.parametrize("bad_limit", [-1, 2.5, "5", True])
def test_value_sampling_rejects_invalid_limit(bad_limit):
    """A non-(plain-int) / negative limit is rejected before it reaches the SQL."""
    connection = MagicMock()
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)
    with pytest.raises(ConfigError):
        extractor.extract_column_unique_values_for_table(
            "customers", ["customer_id"], SCHEMA, limit=bad_limit, cache=False
        )
    connection.cursor.assert_not_called()


def test_value_sampling_for_all_tables_requires_extracted_state():
    """Sampling all tables before column/table extraction raises StateError."""
    extractor = SnowflakeSchemaExtractor(connection=MagicMock(), database=DATABASE)
    with pytest.raises(StateError):
        extractor.extract_column_unique_values_for_all_tables(SCHEMA)


def test_value_sampling_cache_dedupes_on_repeated_calls():
    """Re-sampling the same table with cache=True must not accumulate duplicate values."""
    connection = _capture_connection(pd.DataFrame({"customer_id": ['["1", "2"]']}))
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)

    extractor.extract_column_unique_values_for_table("customers", ["customer_id"], SCHEMA)
    extractor.extract_column_unique_values_for_table("customers", ["customer_id"], SCHEMA)

    cached = extractor.column_unique_values
    assert len(cached) == 2  # two distinct values, not four
    assert cached["value_id"].is_unique


def test_value_sampling_warns_when_no_column_metadata(caplog):
    """Sampling without column metadata warns that complex types can't be skipped."""
    connection = _capture_connection(pd.DataFrame({"customer_id": ['["1"]']}))
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)

    with caplog.at_level(logging.WARNING):
        extractor.extract_column_unique_values_for_table(
            "customers", ["customer_id"], SCHEMA, cache=False
        )

    assert any("No column metadata for table" in rec.message for rec in caplog.records)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ('["1", "2"]', ["1", "2"]),  # JSON-array string (the Snowflake fetch shape)
        ('["a", null, "b"]', ["a", None, "b"]),  # JSON null preserved (dropna handles it later)
        (["x", "y"], ["x", "y"]),  # already a Python list
        (None, []),  # NULL cell
        (123, []),  # unexpected scalar -> empty
        ("not json", []),  # unparseable -> empty (no raise)
        ("{}", []),  # valid JSON but not a list -> empty
    ],
)
def test_parse_array_cell(cell, expected):
    """_parse_array_cell normalizes Snowflake ARRAY_AGG cells (str/list/None/junk) to a list."""
    assert _parse_array_cell(cell) == expected


def test_value_sampling_drops_null_array_elements():
    """A JSON array containing null yields only the non-null values as Value rows."""
    connection = _capture_connection(pd.DataFrame({"customer_id": ['["1", null, "2"]']}))
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)
    result = extractor.extract_column_unique_values_for_table(
        "customers", ["customer_id"], SCHEMA, cache=False
    )
    assert list(result["unique_value"]) == ["1", "2"]  # the null element is dropped


def test_value_sampling_all_complex_columns_issues_no_query():
    """When every candidate column is non-sampleable, no ARRAY_AGG query is issued."""
    connection = MagicMock()
    extractor = SnowflakeSchemaExtractor(connection=connection, database=DATABASE)
    column_info = pd.DataFrame(
        [
            {"table_name": "events", "column_name": "payload", "data_type": "VARIANT"},
            {"table_name": "events", "column_name": "geo", "data_type": "GEOGRAPHY"},
        ]
    )
    result = extractor.extract_column_unique_values_for_table(
        "events", ["payload", "geo"], SCHEMA, cache=False, column_info=column_info
    )
    assert result.empty
    connection.cursor.assert_not_called()


# --- error mapping --------------------------------------------------------------
#
# `_classify` is tested directly (no dependency on whether the optional extra is
# installed). Classification is by exception CLASS only — never message text — so
# the dummy classes are named to match the PEP-249 / snowflake.connector hierarchy.


class ProgrammingError(Exception):
    """Stand-in for snowflake.connector.errors.ProgrammingError."""


class OperationalError(Exception):
    """Stand-in for snowflake.connector.errors.OperationalError."""


class InternalError(Exception):
    """Stand-in for snowflake.connector.errors.InternalError."""


class Error(Exception):
    """Stand-in for the snowflake.connector.errors.Error base."""


def test_classify_programming_error_is_config():
    """A ProgrammingError (invalid SQL/request) classifies as ConfigError."""
    assert isinstance(_classify(ProgrammingError("syntax error near FROM"), "op"), ConfigError)


@pytest.mark.parametrize("exc_cls", [OperationalError, InternalError])
def test_classify_transient_is_retryable_extraction(exc_cls):
    """Operational/internal errors classify as a retryable ExtractionError."""
    mapped = _classify(exc_cls("boom"), "op")
    assert isinstance(mapped, ExtractionError)
    assert mapped.retryable is True


def test_classify_generic_error_not_retryable():
    """A plain Error classifies as a non-retryable ExtractionError."""
    mapped = _classify(Error("boom"), "op")
    assert isinstance(mapped, ExtractionError)
    assert mapped.retryable is False


def test_classify_ignores_message_wording():
    """Classification uses the class, NOT message text (guards against wording changes)."""
    noisy = OperationalError("PERMISSION_DENIED 403 not found 429 timed out")
    mapped = _classify(noisy, "op")
    assert isinstance(mapped, ExtractionError)
    assert mapped.retryable is True
    assert mapped.details["error_type"] == "OperationalError"
    assert mapped.details["connector"] == "snowflake"


def test_wrapper_passes_through_neocarta_error():
    """A NeocartaError raised inside the wrapped function is re-raised unchanged."""

    @wrap_snowflake_errors
    def fn():
        raise ConfigError("already typed")

    with pytest.raises(ConfigError, match="already typed"):
        fn()


def test_wrapper_classifies_snowflake_error(monkeypatch):
    """With the extra treated as present, a snowflake-like error is classified."""
    monkeypatch.setattr(_errors, "_snowflake_error_base", lambda: ProgrammingError)

    @wrap_snowflake_errors
    def fn():
        raise ProgrammingError("bad sql")

    with pytest.raises(ConfigError):
        fn()


def test_wrapper_does_not_mask_foreign_exception(monkeypatch):
    """An exception that is not a snowflake.connector error propagates untouched."""

    class _BaseError(Exception):
        pass

    monkeypatch.setattr(_errors, "_snowflake_error_base", lambda: _BaseError)

    @wrap_snowflake_errors
    def fn():
        raise KeyError("bug")

    with pytest.raises(KeyError):
        fn()
