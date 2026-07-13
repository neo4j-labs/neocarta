"""Snowflake schema extractor.

Reads structural metadata from a database's ``<database>.INFORMATION_SCHEMA.*``
views over a ``snowflake.connector`` (DB-API 2.0) connection. Each stage runs a
``SELECT`` and materialises a pandas DataFrame (via ``cursor.fetch_pandas_all()``),
mirroring the BigQuery / Databricks schema extractors; the DataFrame column names
match what :class:`SnowflakeSchemaTransformer` consumes.

Snowflake's ``INFORMATION_SCHEMA`` has no ``KEY_COLUMN_USAGE`` view, so primary /
foreign keys come from ``SHOW PRIMARY KEYS`` / ``SHOW IMPORTED KEYS`` instead of a
constraint-view join.

Caller-supplied ``database`` / ``schema`` names are resolved to Snowflake's stored case via
:func:`~neocarta.connectors.snowflake._identifiers.normalize_identifier` (unquoted -> upper-case,
``"quoted"`` preserved). Table / column names come back from the catalog already in stored case.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pandas as pd

from ...._logging import log_stage
from ....errors import ConfigError, StateError
from ...utils.generate_id import generate_column_id, generate_value_id
from .._errors import wrap_snowflake_errors
from .._identifiers import normalize_identifier, quote_identifier
from .models import SchemaExtractorCache

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection

logger = logging.getLogger(__name__)

# Snowflake column types that cannot be sampled with ``SELECT DISTINCT`` (semi-structured,
# structured, geospatial, and vector types are non-groupable — Snowflake aborts a DISTINCT
# over them). ``VECTOR`` in particular (used for embeddings) fails with an internal 300010
# error, so it must be skipped or it fails that column's sampling query. Compared against an
# upper-cased ``data_type``.
_NON_SAMPLEABLE_TYPES = ("VARIANT", "OBJECT", "ARRAY", "MAP", "GEOGRAPHY", "GEOMETRY", "VECTOR")

# Default number of per-column value-sampling subqueries to UNION ALL into a single statement,
# so a wide table costs a handful of round trips instead of one per column. Configurable via the
# ``value_sample_query_batch_size`` constructor argument.
_VALUE_SAMPLE_BATCH_SIZE = 50

# Column layout of the (possibly empty) column-unique-values frame.
_VALUE_COLUMNS = ["column_name", "unique_value", "column_id", "value_id"]

# Column layout of the (possibly empty) column-references frame.
_REFERENCE_COLUMNS = [
    "constraint_type",
    "table_catalog",
    "table_schema",
    "table_name",
    "column_name",
    "referenced_catalog",
    "referenced_schema",
    "referenced_table",
    "referenced_column",
]


def _empty_value_frame() -> pd.DataFrame:
    """Return an empty column-unique-values frame with the expected columns."""
    return pd.DataFrame(columns=_VALUE_COLUMNS)


def _string_literal(value: str) -> str:
    r"""Return ``value`` as a single-quoted SQL string literal.

    Doubles backslashes *and* apostrophes: Snowflake interprets backslash escape
    sequences (e.g. ``\n``, ``\'``) inside single-quoted strings, so an un-escaped
    backslash in a (quoted) column name would render a different literal — or, if
    trailing, break out of the quote. Escape backslashes before quotes.
    """
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


class SnowflakeSchemaExtractor:
    """Extractor for Snowflake schema metadata.

    Operates on an injected ``snowflake.connector`` connection — it neither builds
    nor closes the connection (the caller owns it, mirroring how the BigQuery
    extractor takes a ``bigquery.Client``). Internal cached state is *not* part of
    the public API; callers read results through the ``*_info`` /
    ``column_unique_values`` properties.

    Parameters
    ----------
    connection : snowflake.connector.SnowflakeConnection
        An open ``snowflake.connector`` connection.
    database : str
        The Snowflake database to read (the ``:Database``). Each database has its
        own ``INFORMATION_SCHEMA``.
    value_sample_limit : int, default 10
        Number of distinct sample values to read per groupable column. ``0``
        disables value sampling entirely (no table-data reads, so no ``:Value``
        nodes / ``HAS_VALUE`` edges).
    value_sample_query_batch_size : int, default 50
        Number of per-column value-sampling subqueries to UNION ALL into a single
        statement, bounding round trips on wide tables.
    """

    def __init__(
        self,
        connection: SnowflakeConnection,
        database: str,
        *,
        value_sample_limit: int = 10,
        value_sample_query_batch_size: int = _VALUE_SAMPLE_BATCH_SIZE,
    ) -> None:
        """Initialize the extractor with an injected connection and target database."""
        if connection is None:
            raise ConfigError(
                "connection is required for the Snowflake schema extractor.",
                suggestion="Pass connection=snowflake.connector.connect(...).",
            )
        if not database:
            raise ConfigError(
                "database is required for the Snowflake schema extractor.",
                suggestion="Pass database=... (the Snowflake database name).",
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
        if (
            not isinstance(value_sample_query_batch_size, int)
            or isinstance(value_sample_query_batch_size, bool)
            or value_sample_query_batch_size < 1
        ):
            raise ConfigError(
                "value_sample_query_batch_size must be a positive integer.",
                suggestion="Pass value_sample_query_batch_size>=1 (columns sampled per query).",
            )
        self.connection = connection
        # Resolve to stored case up front; also validates, raising ConfigError on a malformed
        # name so it fails fast at construction.
        self.database = normalize_identifier(database)
        self.value_sample_limit = value_sample_limit
        self.value_sample_query_batch_size = value_sample_query_batch_size
        self._cache: SchemaExtractorCache = SchemaExtractorCache()
        # ``SHOW IMPORTED KEYS`` memo, scoped to one extraction pass (cleared at the start of
        # extract_column_info) and reused by the two key stages within it (see _imported_keys).
        self._imported_keys_cache: dict[str, pd.DataFrame] = {}

    @property
    def database_info(self) -> pd.DataFrame:
        """Get the database information."""
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
        """Return the double-quoted ``<database>.INFORMATION_SCHEMA`` prefix."""
        return f"{quote_identifier(self.database)}.INFORMATION_SCHEMA"

    def _qualified_schema(self, schema: str) -> str:
        """Return the double-quoted ``<database>.<schema>`` reference.

        ``schema`` is expected already resolved to stored case (the connector calls
        :func:`normalize_identifier` before handing it to the extractor).
        """
        return f"{quote_identifier(self.database)}.{quote_identifier(schema)}"

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
            return cursor.fetch_pandas_all()
        finally:
            cursor.close()

    def _run_show(self, sql: str) -> pd.DataFrame:
        """Execute a ``SHOW`` command and return its result as a pandas DataFrame.

        ``SHOW`` output is not an Arrow result set, so it is fetched row-wise and
        assembled with the column names from ``cursor.description`` (lower-cased so
        the ``pk_*`` / ``fk_*`` columns are accessed consistently). One cursor per
        command, always closed.
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            columns = [str(col[0]).lower() for col in cursor.description]
        finally:
            cursor.close()
        return pd.DataFrame(rows, columns=columns)

    @log_stage
    def extract_database_info(self, cache: bool = True) -> pd.DataFrame:
        """Build the database information frame.

        The database name *is* the ``:Database`` (analog of the BigQuery project),
        so no query is needed.

        Parameters
        ----------
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            A one-row frame with a ``database`` column.
        """
        df = pd.DataFrame([{"database": self.database}])
        if cache:
            self._cache["database_info"] = df
        return df

    @wrap_snowflake_errors
    @log_stage
    def extract_schema_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract schema information.

        Parameters
        ----------
        schema : str
            The schema name within the database.
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
    CATALOG_NAME AS "catalog_name",
    SCHEMA_NAME AS "schema_name",
    COMMENT AS "description"
FROM {self._qualify()}.SCHEMATA
WHERE CATALOG_NAME = %(database)s
    AND SCHEMA_NAME = %(schema)s
""",
            {"database": self.database, "schema": schema},
        )

        if df.empty:
            raise ConfigError(
                f"Schema {schema!r} was not found in database {self.database!r}.",
                suggestion=(
                    "Verify the database/schema names (Snowflake stores unquoted names "
                    "upper-cased, so pass upper-case) and that the role/warehouse can read "
                    "information_schema."
                ),
            )

        if cache:
            self._cache["schema_info"] = df
        return df

    @wrap_snowflake_errors
    @log_stage
    def extract_table_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract table information for one schema.

        Includes base tables and views; views fold into the ``:Table`` label.

        Parameters
        ----------
        schema : str
            The schema name within the database.
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
    TABLE_CATALOG AS "table_catalog",
    TABLE_SCHEMA AS "table_schema",
    TABLE_NAME AS "table_name",
    TABLE_TYPE AS "table_type",
    COMMENT AS "description"
FROM {self._qualify()}.TABLES
WHERE TABLE_CATALOG = %(database)s
    AND TABLE_SCHEMA = %(schema)s
ORDER BY TABLE_NAME
""",
            {"database": self.database, "schema": schema},
        )
        if cache:
            self._cache["table_info"] = df
        return df

    @wrap_snowflake_errors
    @log_stage
    def extract_column_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract column information for one schema, with PK/FK flags.

        Reads ``information_schema.columns`` and derives ``is_primary_key`` /
        ``is_foreign_key`` per column from ``SHOW PRIMARY KEYS`` / ``SHOW IMPORTED
        KEYS`` (Snowflake's ``information_schema`` has no ``key_column_usage``).
        Snowflake keys are informational (not enforced) and present only when
        declared.

        Parameters
        ----------
        schema : str
            The schema name within the database.
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            Columns ``table_catalog``, ``table_schema``, ``table_name``,
            ``column_name``, ``is_nullable``, ``data_type``, ``description``,
            ``is_primary_key``, ``is_foreign_key``.
        """
        # Scope the imported-keys memo to this extraction pass: clear it here (the first key
        # stage) so a re-ingest picks up changed constraints, while extract_column_references_info
        # — which runs next in the same pass — still reuses the frame this call fetches.
        self._imported_keys_cache.clear()
        df = self._run_query(
            f"""
SELECT
    TABLE_CATALOG AS "table_catalog",
    TABLE_SCHEMA AS "table_schema",
    TABLE_NAME AS "table_name",
    COLUMN_NAME AS "column_name",
    IS_NULLABLE AS "is_nullable",
    DATA_TYPE AS "data_type",
    COMMENT AS "description"
FROM {self._qualify()}.COLUMNS
WHERE TABLE_CATALOG = %(database)s
    AND TABLE_SCHEMA = %(schema)s
ORDER BY TABLE_NAME, ORDINAL_POSITION
""",
            {"database": self.database, "schema": schema},
        )

        if df.empty:
            # No columns in the schema: return a well-formed empty frame carrying the
            # derived flag columns so downstream transforms iterate zero rows cleanly
            # (and skip the SHOW ... KEYS calls, which would return nothing anyway).
            df["is_nullable"] = pd.Series(dtype=bool)
            df["is_primary_key"] = pd.Series(dtype=bool)
            df["is_foreign_key"] = pd.Series(dtype=bool)
            if cache:
                self._cache["column_info"] = df
            return df

        # information_schema reports nullability as the string 'YES'/'NO'; normalize to a real
        # boolean so the cache and the Column model carry a bool, not a string. Treat only an
        # explicit 'NO' as not-nullable; anything unexpected/NULL defaults to True (nullable —
        # the Column model default) rather than silently asserting the column is NOT NULL.
        df["is_nullable"] = df["is_nullable"].astype(str).str.strip().str.upper().ne("NO")

        pk_columns, fk_columns = self._extract_key_columns(schema)
        pairs = list(zip(df["table_name"], df["column_name"], strict=True))
        df["is_primary_key"] = [pair in pk_columns for pair in pairs]
        df["is_foreign_key"] = [pair in fk_columns for pair in pairs]

        if cache:
            self._cache["column_info"] = df
        return df

    def _imported_keys(self, schema: str) -> pd.DataFrame:
        """Return the raw ``SHOW IMPORTED KEYS`` frame for ``schema``, fetched once per pass.

        Both the foreign-key column flags (:meth:`extract_column_info`) and the
        references frame (:meth:`extract_column_references_info`) derive from the same
        imported-keys listing, so it is memoised to issue the ``SHOW`` once per extraction
        pass. The memo is cleared at the start of :meth:`extract_column_info`, so a re-ingest
        re-reads current constraints rather than serving stale keys.
        """
        cached = self._imported_keys_cache.get(schema)
        if cached is None:
            cached = self._run_show(
                f"SHOW IMPORTED KEYS IN SCHEMA {self._qualified_schema(schema)}"
            )
            self._imported_keys_cache[schema] = cached
        return cached

    def _extract_key_columns(
        self, schema: str
    ) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        """Return the (table, column) pairs that are primary keys and foreign keys.

        Snowflake exposes key columns only through ``SHOW PRIMARY KEYS`` / ``SHOW
        IMPORTED KEYS`` (there is no ``key_column_usage`` view), so this reads primary
        keys directly and the foreign-key side from the shared imported-keys frame
        (``fk_table_name`` / ``fk_column_name``).
        """
        pk_df = self._run_show(f"SHOW PRIMARY KEYS IN SCHEMA {self._qualified_schema(schema)}")
        fk_df = self._imported_keys(schema)
        pk = (
            {(row.table_name, row.column_name) for row in pk_df.itertuples()}
            if not pk_df.empty
            else set()
        )
        fk = (
            {(row.fk_table_name, row.fk_column_name) for row in fk_df.itertuples()}
            if not fk_df.empty
            else set()
        )
        return pk, fk

    @wrap_snowflake_errors
    @log_stage
    def extract_column_references_info(self, schema: str, cache: bool = True) -> pd.DataFrame:
        """Extract foreign-key references for one schema via ``SHOW IMPORTED KEYS``.

        Maps each imported (foreign) key to the core references shape, normalising
        the ``fk_*`` / ``pk_*`` columns to ``table_*`` / ``referenced_*``.

        Parameters
        ----------
        schema : str
            The schema name within the database.
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        pd.DataFrame
            Columns ``constraint_type``, ``table_catalog``, ``table_schema``,
            ``table_name``, ``column_name``, ``referenced_catalog``,
            ``referenced_schema``, ``referenced_table``, ``referenced_column``. The
            ``referenced_*`` fields describe the table the foreign key points at.
        """
        show_df = self._imported_keys(schema)

        if show_df.empty:
            df = pd.DataFrame(columns=_REFERENCE_COLUMNS)
            if cache:
                self._cache["column_references_info"] = df
            return df

        df = pd.DataFrame(
            {
                "constraint_type": "FOREIGN KEY",
                "table_catalog": show_df["fk_database_name"],
                "table_schema": show_df["fk_schema_name"],
                "table_name": show_df["fk_table_name"],
                "column_name": show_df["fk_column_name"],
                "referenced_catalog": show_df["pk_database_name"],
                "referenced_schema": show_df["pk_schema_name"],
                "referenced_table": show_df["pk_table_name"],
                "referenced_column": show_df["pk_column_name"],
            }
        )

        # A foreign key whose referenced (PK) table lives in a *different database* points at
        # a column node that is not part of this single-database ingest, so the edge would
        # dangle. Drop such rows (with a warning) rather than emit references to absent nodes.
        resolved = df[df["referenced_catalog"].str.casefold() == self.database.casefold()]
        skipped = len(df) - len(resolved)
        if skipped:
            logger.warning(
                "Skipped %d foreign-key column reference(s) in schema %r whose referenced "
                "table is outside database %r; cross-database foreign keys are not modelled "
                "in a single-database ingest.",
                skipped,
                schema,
                self.database,
            )
        df = resolved.reset_index(drop=True)

        if cache:
            self._cache["column_references_info"] = df
        return df

    @wrap_snowflake_errors
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

        Skips complex / non-groupable column types (VARIANT/OBJECT/ARRAY/MAP/
        GEOGRAPHY/GEOMETRY/VECTOR). Returns an empty frame when the effective limit
        is ``<= 0``.

        Parameters
        ----------
        table_name : str
            The table to sample.
        column_names : list[str]
            Candidate columns to sample.
        schema : str
            The schema name within the database.
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
        # ``limit`` is interpolated into the SQL (``LIMIT {limit}``), so it must be a plain
        # non-negative int — never a bool or arbitrary value that could break the query / inject.
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ConfigError(
                "limit must be a non-negative integer.",
                suggestion="Pass limit=0 to disable value sampling for this call.",
            )
        if limit <= 0:
            return _empty_value_frame()

        column_info = column_info if column_info is not None else self._cache.get("column_info")
        have_types = column_info is not None and not column_info.empty
        if not have_types:
            # Without column metadata the complex/non-sampleable types cannot be detected, so a
            # complex column (VARIANT/OBJECT/ARRAY/MAP/GEOGRAPHY/GEOMETRY/VECTOR) would be pushed
            # into a DISTINCT query and fail on that column. Warn rather than sample blindly; the
            # normal pipeline always supplies column_info (extract_column_info runs first).
            logger.warning(
                "No column metadata for table %r; cannot skip non-sampleable types (%s) — the "
                "sampling query may fail on complex columns. Call extract_column_info(schema=...) "
                "first (or pass column_info=) to enable type-based skipping.",
                table_name,
                ", ".join(_NON_SAMPLEABLE_TYPES),
            )

        sampleable = []
        for col in column_names:
            if have_types:
                col_data_type = column_info[
                    (column_info["table_name"] == table_name) & (column_info["column_name"] == col)
                ]["data_type"]
                if not col_data_type.empty:
                    # DATA_TYPE may carry parameters (``VECTOR(FLOAT, 256)``, ``NUMBER(38,0)``);
                    # strip them and match the base type by exact membership (exact avoids a prefix
                    # collision with a future groupable type; stripping still catches VECTOR).
                    base_type = str(col_data_type.iloc[0]).split("(", 1)[0].strip().upper()
                    if base_type in _NON_SAMPLEABLE_TYPES:
                        continue
            sampleable.append(col)

        if not sampleable:
            return _empty_value_frame()

        relation = f"{self._qualified_schema(schema)}.{quote_identifier(table_name)}"
        # Each column is sampled by a bounded ``DISTINCT ... ORDER BY ... LIMIT`` subquery: the cap
        # is pushed into the scan (vs materialising the full distinct set an ARRAY_AGG(DISTINCT)
        # would), and ORDER BY makes the subset deterministic so a re-sample under cache=True stays
        # capped at ``limit`` and the value-id dedup below collapses repeats. TO_VARCHAR renders
        # server-side for exact text (full NUMBER precision — an Arrow float64 would round/collapse
        # — preserved scale, no fetch_pandas_all overflow on out-of-range TIMESTAMP).
        #
        # The per-column subqueries are UNION ALL-ed in batches of ``value_sample_query_batch_size``
        # so a wide table costs a few round trips, not one per column. Each branch tags its rows
        # with a column-name literal and keeps its own LIMIT.
        frames = []
        batch_size = self.value_sample_query_batch_size
        for start in range(0, len(sampleable), batch_size):
            selects = [
                f'SELECT {_string_literal(col)} AS "column_name", "unique_value" FROM '
                f'(SELECT DISTINCT TO_VARCHAR({quote_identifier(col)}) AS "unique_value" '
                f"FROM {relation} WHERE {quote_identifier(col)} IS NOT NULL "
                f'ORDER BY "unique_value" LIMIT {limit})'
                for col in sampleable[start : start + batch_size]
            ]
            chunk = self._run_query("\nUNION ALL\n".join(selects))
            if not chunk.empty:
                frames.append(chunk[["column_name", "unique_value"]])

        if not frames:
            return _empty_value_frame()

        result = pd.concat(frames, ignore_index=True)
        result = result.dropna(subset=["unique_value"]).reset_index(drop=True)
        result["unique_value"] = result["unique_value"].astype(str)
        result["column_id"] = result["column_name"].apply(
            lambda col: generate_column_id(self.database, schema, table_name, col)
        )
        if result.empty:
            result["value_id"] = pd.Series(dtype=str)
        else:
            result["value_id"] = result.apply(
                lambda row: generate_value_id(
                    self.database, schema, table_name, row["column_name"], row["unique_value"]
                ),
                axis=1,
            )

        if cache:
            # Append to the running cache, then drop rows that repeat a ``value_id`` — a
            # value id fully identifies (database, schema, table, column, value), so a repeat
            # is the *same* value re-sampled (e.g. this method called twice for one table),
            # not a distinct one. Without this, a re-run would accumulate duplicate :Value
            # nodes / HAS_VALUE edges.
            combined = pd.concat(
                [self._cache.get("column_unique_values", pd.DataFrame()), result],
                ignore_index=True,
            )
            self._cache["column_unique_values"] = combined.drop_duplicates(
                subset="value_id", ignore_index=True
            )
        return result

    @wrap_snowflake_errors
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
            The schema name within the database.
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

        # Collect each table's values, then concat ONCE (concatenating inside the loop is
        # quadratic — it recopies the growing frame on every iteration).
        per_table = [
            self.extract_column_unique_values_for_table(
                table_name,
                list(column_info[column_info["table_name"] == table_name]["column_name"].unique()),
                schema,
                column_info=column_info,
                cache=False,
            )
            for table_name in table_info["table_name"].unique()
        ]
        value_info = pd.concat(per_table, ignore_index=True) if per_table else _empty_value_frame()

        if cache:
            self._cache["column_unique_values"] = value_info
        return value_info
