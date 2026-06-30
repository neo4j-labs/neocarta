from unittest.mock import MagicMock

import pandas as pd
import pytest

from neocarta.connectors.databricks import _errors
from neocarta.connectors.databricks._errors import _classify, wrap_databricks_errors
from neocarta.connectors.databricks.schema.extract import (
    DatabricksSchemaExtractor,
    _quote_identifier,
)
from neocarta.connectors.utils.generate_id import generate_column_id, generate_value_id
from neocarta.errors import (
    AuthError,
    ConfigError,
    ExtractionError,
    OperationTimeoutError,
    RateLimitError,
)

CATALOG = "test_catalog"
SCHEMA = "test_schema"


# --- cached-property tests (mirror the BigQuery schema extractor tests) ---------


def test_get_database_info(databricks_extractor_with_cache: DatabricksSchemaExtractor):
    """database_info property returns cached data."""
    assert databricks_extractor_with_cache.database_info.shape[0] == 1
    assert databricks_extractor_with_cache.database_info.iloc[0]["catalog"] == CATALOG


def test_get_schema_info(databricks_extractor_with_cache: DatabricksSchemaExtractor):
    """schema_info property returns cached data."""
    assert databricks_extractor_with_cache.schema_info.shape[0] == 1
    assert databricks_extractor_with_cache.schema_info.iloc[0]["schema_name"] == SCHEMA


def test_get_table_info(databricks_extractor_with_cache: DatabricksSchemaExtractor):
    """table_info property returns cached data."""
    assert databricks_extractor_with_cache.table_info.shape[0] == 2
    assert databricks_extractor_with_cache.table_info.iloc[0]["table_name"] == "customers"
    assert databricks_extractor_with_cache.table_info.iloc[1]["table_name"] == "orders"


def test_get_column_info(databricks_extractor_with_cache: DatabricksSchemaExtractor):
    """column_info property returns cached data with key flags."""
    column_info = databricks_extractor_with_cache.column_info
    assert column_info.shape[0] == 4
    assert column_info.iloc[0]["column_name"] == "customer_id"
    assert bool(column_info.iloc[0]["is_primary_key"]) is True
    assert bool(column_info.iloc[3]["is_foreign_key"]) is True


def test_get_column_references_info(databricks_extractor_with_cache: DatabricksSchemaExtractor):
    """column_references_info property returns cached data."""
    assert databricks_extractor_with_cache.column_references_info.shape[0] == 1
    assert databricks_extractor_with_cache.column_references_info.iloc[0]["table_name"] == "orders"


def test_get_column_unique_values(databricks_extractor_with_cache: DatabricksSchemaExtractor):
    """column_unique_values property returns cached data."""
    assert databricks_extractor_with_cache.column_unique_values.shape[0] == 2
    assert (
        databricks_extractor_with_cache.column_unique_values.iloc[0]["column_name"] == "customer_id"
    )


# --- DB-API / cursor lifecycle --------------------------------------------------


def test_run_query_returns_dataframe():
    """_run_query executes on a cursor and returns the Arrow frame as pandas."""
    connection = MagicMock()
    expected = pd.DataFrame([{"a": 1}])
    connection.cursor.return_value.fetchall_arrow.return_value.to_pandas.return_value = expected

    extractor = DatabricksSchemaExtractor(connection=connection, catalog=CATALOG)
    out = extractor._run_query("SELECT 1", {"x": "y"})

    assert out.equals(expected)
    connection.cursor.return_value.execute.assert_called_once_with("SELECT 1", {"x": "y"})
    connection.cursor.return_value.close.assert_called_once()


def test_run_query_closes_cursor_on_error():
    """_run_query closes the cursor even when execute raises."""
    connection = MagicMock()
    connection.cursor.return_value.execute.side_effect = RuntimeError("boom")

    extractor = DatabricksSchemaExtractor(connection=connection, catalog=CATALOG)
    with pytest.raises(RuntimeError, match="boom"):
        extractor._run_query("SELECT 1")

    connection.cursor.return_value.close.assert_called_once()


# --- identifier quoting ---------------------------------------------------------


def test_quote_identifier_wraps_in_backticks():
    """Identifiers are backtick-quoted."""
    assert _quote_identifier("my_catalog") == "`my_catalog`"


def test_quote_identifier_rejects_backtick():
    """An identifier containing a backtick is a configuration error."""
    with pytest.raises(ConfigError):
        _quote_identifier("evil`catalog")


def test_qualify_rejects_backtick_catalog():
    """_qualify rejects a catalog name containing a backtick."""
    extractor = DatabricksSchemaExtractor(connection=MagicMock(), catalog="evil`catalog")
    with pytest.raises(ConfigError):
        extractor._qualify()


# --- construction guards --------------------------------------------------------


def test_extractor_requires_connection():
    """A missing connection is a configuration error."""
    with pytest.raises(ConfigError):
        DatabricksSchemaExtractor(connection=None, catalog=CATALOG)


def test_extractor_requires_catalog():
    """A missing catalog is a configuration error."""
    with pytest.raises(ConfigError):
        DatabricksSchemaExtractor(connection=MagicMock(), catalog="")


# --- catalog scoping (regression guard) -----------------------------------------
#
# Unity Catalog's `system` catalog exposes an ACCOUNT-WIDE information_schema whose
# rows carry other catalogs' `table_catalog`. Every query must filter by catalog so
# the connector only ever produces nodes for `self.catalog` (consistent Database id,
# no cross-catalog leak). Verified live; guarded here.


def _capture_connection(frame: pd.DataFrame) -> MagicMock:
    connection = MagicMock()
    connection.cursor.return_value.fetchall_arrow.return_value.to_pandas.return_value = frame
    return connection


def test_extract_schema_info_is_catalog_scoped():
    """The schema query filters by catalog and binds both catalog and schema."""
    conn = _capture_connection(
        pd.DataFrame([{"catalog_name": "cat", "schema_name": "sch", "description": None}])
    )
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    ex.extract_schema_info("sch")
    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "catalog_name = %(catalog)s" in sql
    assert params == {"catalog": "cat", "schema": "sch"}


def test_extract_schema_info_missing_schema_raises_config_error():
    """An empty schemata result is a config error, not a synthesized schema row."""
    conn = _capture_connection(
        pd.DataFrame({"catalog_name": [], "schema_name": [], "description": []})
    )
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    with pytest.raises(ConfigError, match="not found"):
        ex.extract_schema_info("ghost")


def test_extract_table_info_is_catalog_scoped():
    """The table query filters by catalog and binds both catalog and schema."""
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
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    ex.extract_table_info("sch")
    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "table_catalog = %(catalog)s" in sql
    assert params == {"catalog": "cat", "schema": "sch"}


def test_extract_column_info_queries_are_catalog_scoped():
    """Both the columns query and the constraint query filter by catalog."""
    conn = MagicMock()
    conn.cursor.return_value.fetchall_arrow.return_value.to_pandas.side_effect = [
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
        ),
        pd.DataFrame(
            {
                "table_name": [],
                "column_name": [],
                "constraint_type": [],
            }
        ),
    ]
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    ex.extract_column_info("sch")
    calls = conn.cursor.return_value.execute.call_args_list
    columns_sql, columns_params = calls[0][0]
    constraints_sql, constraints_params = calls[1][0]
    assert "information_schema.columns" in columns_sql
    assert "table_catalog = %(catalog)s" in columns_sql
    assert columns_params == {"catalog": "cat", "schema": "sch"}
    assert "table_constraints" in constraints_sql
    assert "kcu.table_catalog = %(catalog)s" in constraints_sql
    assert constraints_params == {"catalog": "cat", "schema": "sch"}


def test_extract_references_info_is_catalog_scoped():
    """The references query filters the foreign-key side by catalog."""
    conn = _capture_connection(
        pd.DataFrame(
            {
                "constraint_catalog": [],
                "constraint_schema": [],
                "constraint_name": [],
                "constraint_type": [],
                "table_name": [],
                "column_name": [],
                "ordinal_position": [],
                "referenced_table": [],
                "referenced_column": [],
            }
        )
    )
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    ex.extract_column_references_info("sch")
    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "referential_constraints" in sql
    assert "fk.table_catalog = %(catalog)s" in sql
    # FK columns must pair to referenced PK columns by position_in_unique_constraint
    # (order-independent), NOT by the FK column's own ordinal_position.
    assert "fk.position_in_unique_constraint" in sql
    assert params == {"catalog": "cat", "schema": "sch"}


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
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    df = ex.extract_column_info("sch")
    assert df.empty
    assert "is_primary_key" in df.columns
    assert "is_foreign_key" in df.columns


def test_extract_column_info_normalizes_is_nullable_to_bool():
    """The 'YES'/'NO' nullability flag is normalized to a real boolean."""
    conn = MagicMock()
    conn.cursor.return_value.fetchall_arrow.return_value.to_pandas.side_effect = [
        pd.DataFrame(
            {
                "table_catalog": ["cat", "cat"],
                "table_schema": ["sch", "sch"],
                "table_name": ["t", "t"],
                "column_name": ["a", "b"],
                "is_nullable": ["NO", "YES"],
                "data_type": ["INT", "STRING"],
                "description": [None, None],
            }
        ),
        pd.DataFrame({"table_name": [], "column_name": [], "constraint_type": []}),
    ]
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    df = ex.extract_column_info("sch")
    assert df["is_nullable"].tolist() == [False, True]
    assert df["is_nullable"].dtype == bool


def test_extract_column_info_unknown_nullable_defaults_to_true():
    """An unexpected/NULL is_nullable defaults to True (nullable), not False (NOT NULL)."""
    conn = MagicMock()
    conn.cursor.return_value.fetchall_arrow.return_value.to_pandas.side_effect = [
        pd.DataFrame(
            {
                "table_catalog": ["cat"],
                "table_schema": ["sch"],
                "table_name": ["t"],
                "column_name": ["a"],
                "is_nullable": [None],
                "data_type": ["INT"],
                "description": [None],
            }
        ),
        pd.DataFrame({"table_name": [], "column_name": [], "constraint_type": []}),
    ]
    ex = DatabricksSchemaExtractor(connection=conn, catalog="cat")
    df = ex.extract_column_info("sch")
    assert df["is_nullable"].tolist() == [True]


@pytest.mark.parametrize("bad", [-1, True, 2.5])
def test_extractor_rejects_invalid_value_sample_limit(bad):
    """A non-(plain-int) / negative value_sample_limit is rejected at construction."""
    with pytest.raises(ConfigError):
        DatabricksSchemaExtractor(connection=MagicMock(), catalog="cat", value_sample_limit=bad)


# --- value sampling -------------------------------------------------------------


def _value_query_connection(wide_frame: pd.DataFrame) -> MagicMock:
    connection = MagicMock()
    connection.cursor.return_value.fetchall_arrow.return_value.to_pandas.return_value = wide_frame
    return connection


def test_value_sampling_uses_generate_value_id():
    """Sampled value ids must be produced by generate_value_id (no inline hashing)."""
    connection = _value_query_connection(pd.DataFrame({"customer_id": [[1, 2]]}))
    extractor = DatabricksSchemaExtractor(connection=connection, catalog=CATALOG)

    result = extractor.extract_column_unique_values_for_table(
        "customers", ["customer_id"], SCHEMA, cache=False
    )

    assert list(result["unique_value"]) == ["1", "2"]
    assert result.iloc[0]["column_id"] == generate_column_id(
        CATALOG, SCHEMA, "customers", "customer_id"
    )
    assert result.iloc[0]["value_id"] == generate_value_id(
        CATALOG, SCHEMA, "customers", "customer_id", "1"
    )


def test_value_sampling_skips_complex_types():
    """ARRAY/MAP/STRUCT columns are excluded from the sampling query."""
    connection = _value_query_connection(pd.DataFrame({"customer_id": [[1]]}))
    extractor = DatabricksSchemaExtractor(connection=connection, catalog=CATALOG)
    column_info = pd.DataFrame(
        [
            {"table_name": "customers", "column_name": "customer_id", "data_type": "INT"},
            {"table_name": "customers", "column_name": "tags", "data_type": "ARRAY<STRING>"},
        ]
    )

    extractor.extract_column_unique_values_for_table(
        "customers", ["customer_id", "tags"], SCHEMA, cache=False, column_info=column_info
    )

    executed_sql = connection.cursor.return_value.execute.call_args[0][0]
    assert "`customer_id`" in executed_sql
    assert "`tags`" not in executed_sql


def test_value_sampling_disabled_skips_query():
    """value_sample_limit=0 returns an empty frame and runs no query."""
    connection = MagicMock()
    extractor = DatabricksSchemaExtractor(
        connection=connection, catalog=CATALOG, value_sample_limit=0
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
    extractor = DatabricksSchemaExtractor(connection=connection, catalog=CATALOG)
    with pytest.raises(ConfigError):
        extractor.extract_column_unique_values_for_table(
            "customers", ["customer_id"], SCHEMA, limit=bad_limit, cache=False
        )
    connection.cursor.assert_not_called()


def test_value_sampling_for_all_tables_requires_extracted_state():
    """Sampling all tables before column/table extraction raises StateError."""
    from neocarta.errors import StateError

    extractor = DatabricksSchemaExtractor(connection=MagicMock(), catalog=CATALOG)
    with pytest.raises(StateError):
        extractor.extract_column_unique_values_for_all_tables(SCHEMA)


# --- error mapping --------------------------------------------------------------
#
# `_classify` is tested directly (it has no dependency on whether the optional
# extra is installed): dummy classes named to match the PEP-249 hierarchy exercise
# the MRO-name + message-token classification. The wrapper's base-guard and
# NeocartaError passthrough are tested separately.


class ProgrammingError(Exception):
    """Stand-in for databricks.sql.exc.ProgrammingError."""


class OperationalError(Exception):
    """Stand-in for databricks.sql.exc.OperationalError."""


def test_classify_auth():
    """A permission/credential signal classifies as AuthError."""
    assert isinstance(_classify(OperationalError("PERMISSION_DENIED: token"), "op"), AuthError)


def test_classify_config_programming_error():
    """A ProgrammingError classifies as ConfigError."""
    assert isinstance(_classify(ProgrammingError("syntax error near FROM"), "op"), ConfigError)


def test_classify_config_not_found():
    """A not-found signal classifies as ConfigError."""
    assert isinstance(_classify(Exception("Catalog 'nope' not found"), "op"), ConfigError)


def test_classify_rate_limit():
    """A rate-limit signal classifies as RateLimitError."""
    assert isinstance(_classify(Exception("429 Too Many Requests"), "op"), RateLimitError)


def test_classify_timeout():
    """A timeout signal classifies as OperationTimeoutError."""
    assert isinstance(_classify(Exception("query timed out"), "op"), OperationTimeoutError)


def test_classify_generic_extraction_is_retryable():
    """An OperationalError without a more specific signal is a retryable ExtractionError."""
    mapped = _classify(OperationalError("unexpected server hiccup"), "op")
    assert isinstance(mapped, ExtractionError)
    assert mapped.retryable is True


def test_wrapper_passes_through_neocarta_error():
    """A NeocartaError raised inside the wrapped function is re-raised unchanged."""

    @wrap_databricks_errors
    def fn():
        raise ConfigError("already typed")

    with pytest.raises(ConfigError, match="already typed"):
        fn()


def test_wrapper_classifies_databricks_error(monkeypatch):
    """With the extra treated as present, a databricks-like error is classified."""
    # Force the base to a type the raised exception IS an instance of, so the
    # wrapper takes the classify path regardless of whether the extra is installed.
    monkeypatch.setattr(_errors, "_databricks_error_base", lambda: OperationalError)

    @wrap_databricks_errors
    def fn():
        raise OperationalError("403 PERMISSION_DENIED")

    with pytest.raises(AuthError):
        fn()


def test_wrapper_does_not_mask_foreign_exception(monkeypatch):
    """An exception that is not a databricks.sql error propagates untouched."""

    class _BaseError(Exception):
        pass

    monkeypatch.setattr(_errors, "_databricks_error_base", lambda: _BaseError)

    @wrap_databricks_errors
    def fn():
        raise KeyError("bug")

    with pytest.raises(KeyError):
        fn()
