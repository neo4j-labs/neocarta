"""Snowflake query log extractor.

Reads query history from ``SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`` over the
injected ``snowflake.connector`` (DB-API 2.0) connection and parses each
statement (via the shared ``parse_sql_query``) into the table/column/CTE usage
graph, mirroring the BigQuery logs extractor. ``ACCOUNT_USAGE`` requires access
to the ``SNOWFLAKE`` shared database (``IMPORTED PRIVILEGES``) and has up to ~45
minutes of ingest latency; ``INFORMATION_SCHEMA.QUERY_HISTORY()`` is a
lower-privilege, lower-latency (last 7 days) fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from ...._logging import log_stage
from ....errors import ConfigError
from ...query_log.utils import create_query_id, parse_sql_query
from .._errors import wrap_snowflake_errors
from .._identifiers import normalize_identifier
from .models import LogsExtractorCache

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection

# Snowflake query types that carry table/column lineage worth parsing.
_LINEAGE_QUERY_TYPES = (
    "SELECT",
    "CREATE_TABLE_AS_SELECT",
    "INSERT",
    "MERGE",
    "UPDATE",
    "DELETE",
)


class SnowflakeLogsExtractor:
    """
    Extractor class for Snowflake query logs.
    Extracts and parses query history from ``SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY``.
    """

    def __init__(self, connection: SnowflakeConnection, database: str) -> None:
        """
        Initialize the Snowflake logs extractor.

        Parameters
        ----------
        connection: snowflake.connector.SnowflakeConnection
            An open ``snowflake.connector`` connection with access to
            ``SNOWFLAKE.ACCOUNT_USAGE``.
        database: str
            The Snowflake database whose queries to read (used both to filter
            ``QUERY_HISTORY`` and as the default project when resolving table names).
        """
        self.connection = connection
        # Resolve to Snowflake's stored case so the QUERY_HISTORY.DATABASE_NAME filter matches
        # (unquoted names are upper-cased; wrap a case-sensitive name in double-quotes).
        self.database = normalize_identifier(database)
        self._cache: LogsExtractorCache = LogsExtractorCache()

    @property
    def database_info(self) -> pd.DataFrame:
        """Get the database information derived from query logs."""
        table_info = self._cache.get("table_info", pd.DataFrame())
        if table_info.empty:
            return pd.DataFrame()
        return table_info[["project_id", "project_name", "platform", "service"]].drop_duplicates()

    @property
    def schema_info(self) -> pd.DataFrame:
        """Get the schema information derived from query logs."""
        table_info = self._cache.get("table_info", pd.DataFrame())
        if table_info.empty:
            return pd.DataFrame()
        return table_info[["project_id", "dataset_id", "dataset_name"]].drop_duplicates()

    @property
    def table_info(self) -> pd.DataFrame:
        """Get the table information derived from query logs."""
        table_info = self._cache.get("table_info", pd.DataFrame())
        if table_info.empty:
            return pd.DataFrame()
        return table_info[["project_id", "dataset_id", "table_id", "table_name"]].drop_duplicates()

    @property
    def column_info(self) -> pd.DataFrame:
        """Get the column information derived from query logs."""
        column_info = self._cache.get("column_info", pd.DataFrame())
        if column_info.empty:
            return pd.DataFrame()
        return column_info[
            ["query_id", "table_id", "table_name", "column_id", "column_name"]
        ].drop_duplicates()

    @property
    def column_references_info(self) -> pd.DataFrame:
        """Get the column references information derived from query logs."""
        refs = self._cache.get("column_references_info", pd.DataFrame())
        if refs.empty:
            return pd.DataFrame()
        return refs[
            [
                "left_table_id",
                "left_table_name",
                "left_column_id",
                "left_column_name",
                "right_table_id",
                "right_table_name",
                "right_column_id",
                "right_column_name",
                "criteria",
            ]
        ].drop_duplicates()

    @property
    def query_info(self) -> pd.DataFrame:
        """Get the query information."""
        return self._cache.get("query_info", pd.DataFrame())

    @property
    def cte_info(self) -> pd.DataFrame:
        """Get the CTE information derived from query logs."""
        return self._cache.get("cte_info", pd.DataFrame())

    @property
    def query_table_info(self) -> pd.DataFrame:
        """Get the query-to-table relationship information."""
        table_info = self._cache.get("table_info", pd.DataFrame())
        if table_info.empty:
            return pd.DataFrame()
        return table_info[["query_id", "table_id"]].drop_duplicates()

    @property
    def query_column_info(self) -> pd.DataFrame:
        """Get the query-to-column relationship information."""
        column_info = self._cache.get("column_info", pd.DataFrame())
        if column_info.empty:
            return pd.DataFrame()
        return column_info[["query_id", "column_id"]].drop_duplicates()

    def _run_query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Execute a read query on a fresh cursor and return a pandas DataFrame.

        One cursor per query, always closed (even when ``execute`` raises). Value
        literals are passed as bound ``params`` (pyformat ``%(name)s``); SQL text
        and parameters are never logged.
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetch_pandas_all()
        finally:
            cursor.close()

    @wrap_snowflake_errors
    @log_stage
    def extract_query_logs(
        self,
        schema: str | None = None,
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
        cache: bool = True,
    ) -> pd.DataFrame:
        """
        Extract Snowflake query logs and parse them to extract table/column information.

        Parameters
        ----------
        schema: Optional[str] = None
            The schema to filter queries by (matched against ``QUERY_HISTORY.SCHEMA_NAME``)
            and the default schema used to resolve unqualified table names. When ``None``,
            queries across all schemas of the database are read and only fully qualified
            table references resolve (unresolvable queries are skipped).
        start_timestamp: Optional[str] = None
            The start timestamp in ISO format (e.g., '2024-01-01 00:00:00').
            If not provided, defaults to 30 days ago.
        end_timestamp: Optional[str] = None
            The end timestamp in ISO format (e.g., '2024-01-31 23:59:59').
            If not provided, defaults to current timestamp.
        limit: int = 100
            The maximum number of queries to return.
        drop_failed_queries: bool = True
            Whether to exclude failed queries.
        cache: bool = True
            Whether to cache the extracted information.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame containing the query log information.
        """
        # ``limit`` is interpolated into the SQL (LIMIT {limit}), so it must be a plain
        # non-negative int — never a bool or negative value that would produce invalid SQL
        # surfaced as an opaque error. Mirror the schema extractor's value_sample_limit guard.
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ConfigError(
                "limit must be a non-negative integer.",
                suggestion="Pass a limit >= 0 (0 returns no rows).",
            )

        params: dict[str, Any] = {"database": self.database}
        schema_condition = ""
        if schema:
            # Resolve to stored case so the SCHEMA_NAME filter matches (see self.database).
            schema = normalize_identifier(schema)
            schema_condition = "AND SCHEMA_NAME = %(schema)s"
            params["schema"] = schema

        # Provided timestamps are bound; the defaults are computed server-side.
        if start_timestamp:
            params["start_timestamp"] = start_timestamp
        if end_timestamp:
            params["end_timestamp"] = end_timestamp
        start_condition = (
            "TO_TIMESTAMP_LTZ(%(start_timestamp)s)"
            if start_timestamp
            else "DATEADD('day', -30, CURRENT_TIMESTAMP())"
        )
        end_condition = (
            "TO_TIMESTAMP_LTZ(%(end_timestamp)s)" if end_timestamp else "CURRENT_TIMESTAMP()"
        )
        query_types = ", ".join(f"'{t}'" for t in _LINEAGE_QUERY_TYPES)

        query = f"""SELECT
  QUERY_TEXT AS "query",
  ERROR_CODE AS "error_result"
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE DATABASE_NAME = %(database)s
  {schema_condition}
  AND QUERY_TYPE IN ({query_types})
  AND QUERY_TEXT IS NOT NULL
  AND START_TIME >= {start_condition}
  AND START_TIME < {end_condition}
ORDER BY START_TIME DESC
LIMIT {int(limit)}
"""

        query_info_df = self._run_query(query, params)

        if drop_failed_queries:
            query_info_df = query_info_df[query_info_df["error_result"].isnull()]

        # QUERY_TEXT is nullable in ACCOUNT_USAGE (redacted / not-captured statements). The
        # SQL already filters NULLs, but guard the fetched frame too so a NULL/blank text can
        # never crash create_query_id / parse_sql_query — a single such row must not abort the
        # whole batch. .copy() so the query_id assignment writes to an owned frame (no
        # SettingWithCopyWarning).
        query_info_df = query_info_df[
            query_info_df["query"].notna() & (query_info_df["query"].astype(str).str.strip() != "")
        ].copy()

        # Add query_id as hash of the query text
        query_info_df["query_id"] = query_info_df["query"].apply(create_query_id)

        # Parse queries to extract table and column information
        table_info = []
        column_info = []
        references_info = []
        cte_info = []

        for _, row in query_info_df.iterrows():
            query_text = row["query"]
            query_id = row["query_id"]

            parsed_dict = parse_sql_query(
                query_text,
                query_id,
                "snowflake",
                default_project_id=self.database,
                default_schema_id=schema,
            )

            if parsed_dict:
                table_info.extend(parsed_dict["table_info"])
                column_info.extend(parsed_dict["column_info"])
                references_info.extend(parsed_dict["references_info"])
                cte_info.extend(parsed_dict.get("cte_info", []))

        table_info_df = pd.DataFrame(table_info)
        column_info_df = pd.DataFrame(column_info)
        references_info_df = pd.DataFrame(references_info)
        cte_info_df = pd.DataFrame(cte_info)

        if cache:
            self._cache["query_info"] = query_info_df
            self._cache["table_info"] = table_info_df
            self._cache["column_info"] = column_info_df
            self._cache["column_references_info"] = references_info_df
            self._cache["cte_info"] = cte_info_df

        return query_info_df
