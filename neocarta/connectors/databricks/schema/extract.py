"""Databricks Unity Catalog schema extractor.

Reads structural metadata from a catalog's ``<catalog>.information_schema.*``
views over a Databricks SQL warehouse using the injected ``databricks.sql``
(DB-API 2.0) connection — no Spark, no JDBC. Each stage runs a ``SELECT`` and
materialises a pandas DataFrame, mirroring the BigQuery schema extractor; the
DataFrame column names match what :class:`DatabricksSchemaTransformer` consumes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from ...._logging import log_stage
from ....errors import ConfigError, StateError
from ...utils.generate_id import generate_column_id, generate_value_id
from .._errors import wrap_databricks_errors
from .models import SchemaExtractorCache

if TYPE_CHECKING:
    from databricks.sql.client import Connection

# Unity Catalog column types that cannot be passed to ``collect_set`` / sampled
# with a distinct aggregate (complex / non-groupable types). Compared against an
# upper-cased ``data_type``.
_NON_SAMPLEABLE_TYPES = ("ARRAY", "MAP", "STRUCT", "BINARY", "VARIANT")

# Column layout of the (possibly empty) column-unique-values frame.
_VALUE_COLUMNS = ["column_name", "unique_value", "column_id", "value_id"]


def _quote_identifier(identifier: str) -> str:
    """Backtick-quote a SQL identifier, rejecting embedded backticks.

    Identifiers (catalog / schema / table / column names) cannot be passed as
    bound parameters, so they are interpolated into the query — backtick-quoted
    after rejecting any name that itself contains a backtick (which could break
    out of the quoting). Value literals use bound parameters instead.

    Parameters
    ----------
    identifier : str
        The identifier to quote.

    Returns:
    -------
    str
        The backtick-quoted identifier.

    Raises:
    ------
    ConfigError
        If ``identifier`` contains a backtick.
    """
    if "`" in identifier:
        raise ConfigError(
            f"Invalid Databricks identifier {identifier!r}: backticks are not allowed.",
            suggestion="Pass a catalog/schema name without backtick characters.",
        )
    return f"`{identifier}`"


def _empty_value_frame() -> pd.DataFrame:
    """Return an empty column-unique-values frame with the expected columns."""
    return pd.DataFrame(columns=_VALUE_COLUMNS)


class DatabricksSchemaExtractor:
    """Extractor for Databricks Unity Catalog schema metadata.

    Operates on an injected ``databricks.sql`` connection — it neither builds nor
    closes the connection (the caller owns it, mirroring how the BigQuery
    extractor takes a ``bigquery.Client``). Internal cached state is *not* part of
    the public API; callers read results through the ``*_info`` /
    ``column_unique_values`` properties.

    Parameters
    ----------
    connection : databricks.sql.client.Connection
        An open ``databricks.sql`` connection to a SQL warehouse.
    catalog : str
        The Unity Catalog catalog to read (the ``:Database``). Each catalog has
        its own ``information_schema``.
    value_sample_limit : int, default 10
        Number of distinct sample values to read per groupable column. ``0``
        disables value sampling entirely (no table-data reads, so no ``:Value``
        nodes / ``HAS_VALUE`` edges).
    """

    def __init__(
        self,
        connection: Connection,
        catalog: str,
        *,
        value_sample_limit: int = 10,
    ) -> None:
        """Initialize the extractor with an injected connection and target catalog."""
        if connection is None:
            raise ConfigError(
                "connection is required for the Databricks schema extractor.",
                suggestion="Pass connection=databricks.sql.connect(...).",
            )
        if not catalog:
            raise ConfigError(
                "catalog is required for the Databricks schema extractor.",
                suggestion="Pass catalog=... (the Unity Catalog catalog name).",
            )
        if (
            not isinstance(value_sample_limit, int)
            or isinstance(value_sample_limit, bool)
            or value_sample_limit < 0
        ):
            raise ConfigError(
                "value_sample_limit must be a non-negative integer.",
                suggestion="Pass value_sample_limit=0 to disable value sampling.",
            )
        self.connection = connection
        self.catalog = catalog
        self.value_sample_limit = value_sample_limit
        self._cache: SchemaExtractorCache = SchemaExtractorCache()

    @property
    def database_info(self) -> pd.DataFrame:
        """Get the database (catalog) information."""
        return self._cache.get("database_info", pd.DataFrame())

    @property
    def schema_info(self) -> pd.DataFrame:
        """Get the schema information."""
        return self._cache.get("schema_info", pd.DataFrame())

    @property
    def table_info(self) -> pd.DataFrame:
        """Get the table information."""
        return self._cache.get("table_info", pd.DataFrame())

    @property
    def column_info(self) -> pd.DataFrame:
        """Get the column information."""
        return self._cache.get("column_info", pd.DataFrame())

    @property
    def column_references_info(self) -> pd.DataFrame:
        """Get the column references (foreign-key) information."""
        return self._cache.get("column_references_info", pd.DataFrame())

    @property
    def column_unique_values(self) -> pd.DataFrame:
        """Get the column unique values."""
        return self._cache.get("column_unique_values", pd.DataFrame())

    def _qualify(self) -> str:
        """Return the backtick-quoted ``<catalog>.information_schema`` prefix."""
        return f"{_quote_identifier(self.catalog)}.information_schema"

    def _run_query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Execute a read query on a fresh cursor and return a pandas DataFrame.

        One cursor per query, always closed (even when ``execute`` raises). Value
        literals are passed as bound ``params`` (pyformat ``%(name)s``); SQL text
        and parameters are never logged.

        Parameters
        ----------
        sql : str
            The query to run.
        params : dict, optional
            Bound parameters for the query.

        Returns:
        -------
        pd.DataFrame
            The query result as a DataFrame (native Arrow → pandas).
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchall_arrow().to_pandas()
        finally:
            cursor.close()

    @log_stage
    def extract_database_info(self, cache: bool = True) -> pd.DataFrame:
        """Build the database (catalog) information frame.

        The catalog name *is* the ``:Database`` (analog of the BigQuery project),
        so no query is needed.

        Parameters
        ----------
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            A one-row frame with a ``catalog`` column.
        """
        df = pd.DataFrame([{"catalog": self.catalog}])
        if cache:
            self._cache["database_info"] = df
        return df

    @wrap_databricks_errors
    @log_stage
    def extract_schema_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract schema (Unity Catalog schema) information.

        Parameters
        ----------
        schema : str
            The schema name within the catalog.
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            Columns ``catalog_name``, ``schema_name``, ``description``.
        """
        df = self._run_query(
            f"""
SELECT
    catalog_name,
    schema_name,
    comment AS description
FROM {self._qualify()}.schemata
WHERE catalog_name = %(catalog)s
    AND schema_name = %(schema)s
""",
            {"catalog": self.catalog, "schema": schema},
        )

        if df.empty:
            raise ConfigError(
                f"Schema {schema!r} was not found in catalog {self.catalog!r}.",
                suggestion=(
                    "Verify the catalog/schema names and that the warehouse can read "
                    "information_schema."
                ),
            )

        if cache:
            self._cache["schema_info"] = df
        return df

    @wrap_databricks_errors
    @log_stage
    def extract_table_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract table information for one schema.

        Includes base tables and views; views fold into the ``:Table`` label
        (matching the Unity Catalog REST connector).

        Parameters
        ----------
        schema : str
            The schema name within the catalog.
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            Columns ``table_catalog``, ``table_schema``, ``table_name``,
            ``table_type``, ``description``.
        """
        df = self._run_query(
            f"""
SELECT
    table_catalog,
    table_schema,
    table_name,
    table_type,
    comment AS description
FROM {self._qualify()}.tables
WHERE table_catalog = %(catalog)s
    AND table_schema = %(schema)s
ORDER BY table_name
""",
            {"catalog": self.catalog, "schema": schema},
        )
        if cache:
            self._cache["table_info"] = df
        return df

    @wrap_databricks_errors
    @log_stage
    def extract_column_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract column information for one schema, with PK/FK flags.

        Reads ``information_schema.columns`` and derives ``is_primary_key`` /
        ``is_foreign_key`` per column from the constraint views
        (``table_constraints`` + ``key_column_usage``). Unity Catalog keys are
        informational (not enforced) and present only when declared.

        Parameters
        ----------
        schema : str
            The schema name within the catalog.
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            Columns ``table_catalog``, ``table_schema``, ``table_name``,
            ``column_name``, ``is_nullable``, ``data_type``, ``description``,
            ``is_primary_key``, ``is_foreign_key``.
        """
        df = self._run_query(
            f"""
SELECT
    table_catalog,
    table_schema,
    table_name,
    column_name,
    is_nullable,
    data_type,
    comment AS description
FROM {self._qualify()}.columns
WHERE table_catalog = %(catalog)s
    AND table_schema = %(schema)s
ORDER BY table_name, ordinal_position
""",
            {"catalog": self.catalog, "schema": schema},
        )

        # information_schema reports nullability as the string 'YES'/'NO'; normalize to a real
        # boolean so the cache and the Column model carry a bool, not a string. Treat only an
        # explicit 'NO' as not-nullable; anything unexpected/NULL defaults to True (nullable —
        # the Column model default) rather than silently asserting the column is NOT NULL.
        df["is_nullable"] = df["is_nullable"].astype(str).str.strip().str.upper().ne("NO")

        pk_columns, fk_columns = self._extract_key_columns(schema)
        if df.empty:
            df["is_primary_key"] = pd.Series(dtype=bool)
            df["is_foreign_key"] = pd.Series(dtype=bool)
        else:
            pairs = list(zip(df["table_name"], df["column_name"], strict=True))
            df["is_primary_key"] = [pair in pk_columns for pair in pairs]
            df["is_foreign_key"] = [pair in fk_columns for pair in pairs]

        if cache:
            self._cache["column_info"] = df
        return df

    def _extract_key_columns(
        self, schema: str
    ) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        """Return the (table, column) pairs that are primary keys and foreign keys.

        Joins ``key_column_usage`` to ``table_constraints`` to label each
        constrained column by constraint type.
        """
        df = self._run_query(
            f"""
SELECT
    kcu.table_name AS table_name,
    kcu.column_name AS column_name,
    tc.constraint_type AS constraint_type
FROM {self._qualify()}.key_column_usage kcu
JOIN {self._qualify()}.table_constraints tc
    ON kcu.constraint_catalog = tc.constraint_catalog
    AND kcu.constraint_schema = tc.constraint_schema
    AND kcu.constraint_name = tc.constraint_name
WHERE kcu.table_catalog = %(catalog)s
    AND kcu.table_schema = %(schema)s
    AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
""",
            {"catalog": self.catalog, "schema": schema},
        )
        if df.empty:
            return set(), set()
        pk = {
            (row.table_name, row.column_name)
            for row in df.itertuples()
            if row.constraint_type == "PRIMARY KEY"
        }
        fk = {
            (row.table_name, row.column_name)
            for row in df.itertuples()
            if row.constraint_type == "FOREIGN KEY"
        }
        return pk, fk

    @wrap_databricks_errors
    @log_stage
    def extract_column_references_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract foreign-key references for one schema.

        Resolves each foreign key to its referenced primary-key columns by
        pairing ``key_column_usage`` rows on both sides of
        ``referential_constraints`` by ordinal position.

        Parameters
        ----------
        schema : str
            The schema name within the catalog.
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            Columns ``constraint_type``, ``table_catalog``, ``table_schema``,
            ``table_name``, ``column_name``, ``ordinal_position``,
            ``referenced_catalog``, ``referenced_schema``, ``referenced_table``,
            ``referenced_column``. The ``referenced_*`` fields describe the table the
            foreign key points at (which may live in a different schema/catalog).
        """
        df = self._run_query(
            f"""
SELECT
    'FOREIGN KEY' AS constraint_type,
    fk.table_catalog AS table_catalog,
    fk.table_schema AS table_schema,
    fk.table_name AS table_name,
    fk.column_name AS column_name,
    fk.ordinal_position AS ordinal_position,
    pk.table_catalog AS referenced_catalog,
    pk.table_schema AS referenced_schema,
    pk.table_name AS referenced_table,
    pk.column_name AS referenced_column
FROM {self._qualify()}.referential_constraints rc
JOIN {self._qualify()}.key_column_usage fk
    ON fk.constraint_catalog = rc.constraint_catalog
    AND fk.constraint_schema = rc.constraint_schema
    AND fk.constraint_name = rc.constraint_name
JOIN {self._qualify()}.key_column_usage pk
    ON pk.constraint_catalog = rc.unique_constraint_catalog
    AND pk.constraint_schema = rc.unique_constraint_schema
    AND pk.constraint_name = rc.unique_constraint_name
    AND pk.ordinal_position = fk.position_in_unique_constraint
WHERE fk.table_catalog = %(catalog)s
    AND fk.table_schema = %(schema)s
ORDER BY fk.table_name, fk.constraint_name, fk.ordinal_position
""",
            {"catalog": self.catalog, "schema": schema},
        )
        if cache:
            self._cache["column_references_info"] = df
        return df

    @wrap_databricks_errors
    def extract_column_unique_values_for_table(
        self,
        table_name: str,
        column_names: list[str],
        schema: str,
        limit: int | None = None,
        cache: bool = True,
        column_info: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Extract up to ``limit`` distinct sample values for one table's columns.

        Skips complex / non-groupable column types (ARRAY/MAP/STRUCT/BINARY/
        VARIANT). Returns an empty frame when the effective limit is ``<= 0``.

        Parameters
        ----------
        table_name : str
            The table to sample.
        column_names : list[str]
            Candidate columns to sample.
        schema : str
            The schema name within the catalog.
        limit : int, optional
            Distinct values per column. Defaults to the extractor's
            ``value_sample_limit``.
        cache : bool, default True
            Whether to append the result to the cached values frame.
        column_info : pd.DataFrame, optional
            Column metadata used to skip non-sampleable types; falls back to the
            cached ``column_info``.

        Returns:
        -------
        pd.DataFrame
            Columns ``column_name``, ``unique_value``, ``column_id``, ``value_id``.
        """
        limit = self.value_sample_limit if limit is None else limit
        # ``limit`` is interpolated into the SQL (slice(..., 1, {limit})), so it must be a
        # plain non-negative int — never a bool or arbitrary value that could break/inject.
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ConfigError(
                "limit must be a non-negative integer.",
                suggestion="Pass limit=0 to disable value sampling for this call.",
            )
        if limit <= 0:
            return _empty_value_frame()

        column_info = column_info if column_info is not None else self._cache.get("column_info")

        select_clauses = []
        for col in column_names:
            if column_info is not None and not column_info.empty:
                col_data_type = column_info[
                    (column_info["table_name"] == table_name) & (column_info["column_name"] == col)
                ]["data_type"]
                if not col_data_type.empty:
                    data_type = str(col_data_type.iloc[0]).upper()
                    if data_type.startswith(_NON_SAMPLEABLE_TYPES):
                        continue
            quoted = _quote_identifier(col)
            select_clauses.append(f"slice(collect_set({quoted}), 1, {limit}) AS {quoted}")

        if not select_clauses:
            return _empty_value_frame()

        relation = (
            f"{_quote_identifier(self.catalog)}."
            f"{_quote_identifier(schema)}.{_quote_identifier(table_name)}"
        )
        df = self._run_query(f"SELECT {', '.join(select_clauses)} FROM {relation}")

        result = df.melt(var_name="column_name", value_name="unique_value")
        result = result.explode("unique_value").dropna().reset_index(drop=True)
        result["unique_value"] = result["unique_value"].astype(str)
        result["column_id"] = result["column_name"].apply(
            lambda col: generate_column_id(self.catalog, schema, table_name, col)
        )
        if result.empty:
            result["value_id"] = pd.Series(dtype=str)
        else:
            result["value_id"] = result.apply(
                lambda row: generate_value_id(
                    self.catalog, schema, table_name, row["column_name"], row["unique_value"]
                ),
                axis=1,
            )

        if cache:
            self._cache["column_unique_values"] = pd.concat(
                [self._cache.get("column_unique_values", pd.DataFrame()), result],
                ignore_index=True,
            )
        return result

    @wrap_databricks_errors
    @log_stage
    def extract_column_unique_values_for_all_tables(
        self,
        schema: str,
        table_info: pd.DataFrame | None = None,
        column_info: pd.DataFrame | None = None,
        cache: bool = True,
    ) -> pd.DataFrame:
        """Extract distinct sample values for every table in the schema.

        Returns an empty frame (no table-data reads) when ``value_sample_limit``
        is ``0``.

        Parameters
        ----------
        schema : str
            The schema name within the catalog.
        table_info : pd.DataFrame, optional
            Table metadata; falls back to the cached ``table_info``.
        column_info : pd.DataFrame, optional
            Column metadata; falls back to the cached ``column_info``.
        cache : bool, default True
            Whether to cache the combined values frame.

        Returns:
        -------
        pd.DataFrame
            The combined column-unique-values frame.

        Raises:
        ------
        StateError
            If column or table information has not been extracted/cached.
        """
        column_info = column_info if column_info is not None else self._cache.get("column_info")
        if column_info is None:
            raise StateError(
                "Column information is required to extract column unique values. "
                "Call extract_column_info(schema=...) first (with cache=True).",
                suggestion="Run connector.extract(schema=...), which orders the stages.",
            )
        table_info = table_info if table_info is not None else self._cache.get("table_info")
        if table_info is None:
            raise StateError(
                "Table information is required to extract column unique values. "
                "Call extract_table_info(schema=...) first (with cache=True).",
                suggestion="Run connector.extract(schema=...), which orders the stages.",
            )

        if self.value_sample_limit <= 0:
            empty = _empty_value_frame()
            if cache:
                self._cache["column_unique_values"] = empty
            return empty

        value_info = pd.DataFrame()
        for table_name in table_info["table_name"].unique():
            column_names = column_info[column_info["table_name"] == table_name][
                "column_name"
            ].unique()
            value_info = pd.concat(
                [
                    value_info,
                    self.extract_column_unique_values_for_table(
                        table_name,
                        list(column_names),
                        schema,
                        column_info=column_info,
                        cache=False,
                    ),
                ],
                ignore_index=True,
            )

        if cache:
            self._cache["column_unique_values"] = value_info
        return value_info
