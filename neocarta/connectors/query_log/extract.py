"""Query log extractor for local JSON files."""

import pandas as pd

from .models import QueryLogExtractorCache
from .utils import parse_bigquery_query_log_json, parse_sql_query


class QueryLogExtractor:
    """Extractor class for query log files."""

    def __init__(self) -> None:
        """Initialize an empty extractor cache."""
        self._cache: QueryLogExtractorCache = QueryLogExtractorCache()

    @property
    def database_info(self) -> pd.DataFrame:
        """Get the database information."""
        return self._cache.get("table_info", pd.DataFrame())[
            ["project_id", "project_name", "platform", "service"]
        ].drop_duplicates()

    @property
    def schema_info(self) -> pd.DataFrame:
        """Get the schema information."""
        return self._cache.get("table_info", pd.DataFrame())[
            ["project_id", "dataset_id", "dataset_name"]
        ].drop_duplicates()

    @property
    def table_info(self) -> pd.DataFrame:
        """Get the table information."""
        return self._cache.get("table_info", pd.DataFrame())[
            ["project_id", "dataset_id", "table_id", "table_name"]
        ].drop_duplicates()

    @property
    def column_info(self) -> pd.DataFrame:
        """Get the column information."""
        return self._cache.get("column_info", pd.DataFrame())[
            ["query_id", "table_id", "table_name", "column_id", "column_name"]
        ].drop_duplicates()

    @property
    def column_references_info(self) -> pd.DataFrame:
        """Get the column references information."""
        return self._cache.get("column_references_info", pd.DataFrame())[
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
        """Get the CTE information."""
        return self._cache.get("cte_info", pd.DataFrame())

    @property
    def query_table_info(self) -> pd.DataFrame:
        """Get the query table information."""
        return self._cache.get("table_info", pd.DataFrame())[
            ["query_id", "table_id"]
        ].drop_duplicates()

    @property
    def query_column_info(self) -> pd.DataFrame:
        """Get the query column information."""
        return self._cache.get("column_info", pd.DataFrame())[
            ["query_id", "column_id"]
        ].drop_duplicates()

    def extract_info_from_query_log_json(
        self, query_log_file: str, source: str = "bigquery", cache: bool = True
    ) -> dict[str, pd.DataFrame]:
        """
        Extract information from a query log file.

        Parameters
        ----------
        query_log_file: str
            The path to the query log file.
        source: str = "bigquery"
            The source of the query log file.
        cache: bool = True
            Whether to cache the extracted information.

        Returns:
        -------
        dict[str, pd.DataFrame]
            A dictionary with the extracted information.
            - query_info: A Pandas DataFrame containing the query information.
            - table_info: A Pandas DataFrame containing the table information.
            - column_info: A Pandas DataFrame containing the column information.
            - column_references_info: A Pandas DataFrame containing the column references information.
        """
        # read the log file into a pandas dataframe
        if source == "bigquery":
            parsed = parse_bigquery_query_log_json(query_log_file)
        else:
            raise ValueError(f"Unsupported source: {source}")

        query_info_df = parsed["query_info"]

        # parse the queries
        table_info = []
        column_info = []
        references_info = []
        cte_info = []

        for _, row in query_info_df.iterrows():
            query = row["query"]
            query_id = row["query_id"]
            project_id = row.get("project_id")

            parsed_dict = parse_sql_query(
                query, query_id, "bigquery", default_project_id=project_id
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

        return {
            "query_info": query_info_df,
            "table_info": table_info_df,
            "column_info": column_info_df,
            "column_references_info": references_info_df,
            "cte_info": cte_info_df,
        }
