"""BigQuery query log extractor."""

import pandas as pd
from google.cloud import bigquery

from ...query_log.utils import create_query_id, parse_sql_query
from .models import LogsExtractorCache


class BigQueryLogsExtractor:
    """
    Extractor class for BigQuery query logs.
    Extracts and parses query logs from BigQuery INFORMATION_SCHEMA.JOBS_BY_PROJECT.
    """

    def __init__(self, client: bigquery.Client, project_id: str | None = None) -> None:
        """
        Initialize the BigQuery logs extractor.

        Parameters
        ----------
        client: bigquery.Client
            The BigQuery client.
        project_id: Optional[str] = None
            The project ID. If not provided, will use the project ID from the client.
        """
        self.client = client
        self.project_id = client.project or project_id

        if self.project_id is None:
            raise ValueError(
                "Project ID is required as argument in constructor or as attribute in BigQuery client."
            )

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

    def extract_query_logs(
        self,
        dataset_id: str,
        region: str = "region-us",
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
        cache: bool = True,
    ) -> pd.DataFrame:
        """
        Extract BigQuery query logs and parse them to extract table/column information.

        Parameters
        ----------
        dataset_id: str
            The dataset ID to filter queries by.
        region: str = "region-us"
            The BigQuery region for INFORMATION_SCHEMA.JOBS_BY_PROJECT.
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
        # Set default timestamps if not provided
        start_condition = (
            f"TIMESTAMP('{start_timestamp}')"
            if start_timestamp
            else "TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)"
        )
        end_condition = f"TIMESTAMP('{end_timestamp}')" if end_timestamp else "CURRENT_TIMESTAMP()"

        query = f"""SELECT
  job.error_result,
  job.query
FROM
  `{self.project_id}.{region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT` AS job,
  UNNEST(job.referenced_tables) AS ref
WHERE
  ref.dataset_id = '{dataset_id}'
  AND ref.table_id NOT LIKE 'INFORMATION_SCHEMA.%'
  AND job.creation_time >= {start_condition}
  AND job.creation_time < {end_condition}
ORDER BY
  job.creation_time DESC
LIMIT {limit};
"""

        query_info_df = self.client.query(query).to_dataframe()

        if drop_failed_queries:
            query_info_df = query_info_df[query_info_df["error_result"].isnull()]

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
                "bigquery",
                default_project_id=self.project_id,
                default_schema_id=dataset_id,
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
