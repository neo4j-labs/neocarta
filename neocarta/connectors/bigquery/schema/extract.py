"""BigQuery schema extractor."""

import hashlib

import pandas as pd
from google.cloud import bigquery

from ...._logging import log_stage
from ....errors import ConfigError, StateError
from ...utils.generate_id import generate_column_id
from .._errors import wrap_bigquery_errors
from .models import SchemaExtractorCache


class BigQuerySchemaExtractor:
    """
    Extractor class for BigQuery schema metadata.
    Extracts metadata from BigQuery Information Schema tables.
    """

    def __init__(
        self,
        client: bigquery.Client,
        project_id: str | None = None,
        dataset_id: str | None = None,
    ) -> None:
        """
        Initialize the BigQuery schema extractor.

        Parameters
        ----------
        client: bigquery.Client
            The BigQuery client.
        project_id: Optional[str] = None
            The project ID. If not provided, will use the project ID from the client.
        dataset_id: Optional[str] = None
            The dataset ID. May be provided in extractor methods.
        """
        self.client = client
        self.project_id = client.project or project_id

        if self.project_id is None:
            raise ConfigError(
                "Project ID is required as argument in constructor or as attribute in BigQueryclient."
            )

        self.dataset_id = dataset_id
        self._cache: SchemaExtractorCache = SchemaExtractorCache()

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
        """Get the column references information."""
        return self._cache.get("column_references_info", pd.DataFrame())

    @property
    def column_unique_values(self) -> pd.DataFrame:
        """Get the column unique values."""
        return self._cache.get("column_unique_values", pd.DataFrame())

    def _get_dataset_id(self, dataset_id: str | None = None) -> str:
        """
        Get the dataset ID. If not provided, will use default instance `dataset_id`.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.

        Returns:
        -------
        str
            The dataset ID.
        """
        dataset_id = dataset_id or self.dataset_id

        if dataset_id is None:
            raise ConfigError(
                "Dataset ID is required in either constructor as `dataset_id` or as an argument to `extract_schema_info` method."
            )

        return dataset_id

    @log_stage
    def extract_database_info(self, cache: bool = True) -> pd.DataFrame:
        """
        Extract BigQuery database (project) information.

        Parameters
        ----------
        cache: bool = True
            Whether to cache the extract. If True, will cache the database information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame containing the BigQuery database information.
        """
        df = pd.DataFrame([{"project_id": self.project_id}])
        if cache:
            self._cache["database_info"] = df

        return df

    @wrap_bigquery_errors
    @log_stage
    def extract_schema_info(
        self, dataset_id: str | None = None, cache: bool = True
    ) -> pd.DataFrame:
        """
        Extract BigQuery schema (dataset) information.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        cache: bool = True
            Whether to cache the extract. If True, will cache the schema information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame containing the BigQuery schema information.
        """
        dataset_id = self._get_dataset_id(dataset_id)

        df = self.client.query(f"""
SELECT
    '{self.project_id}' as project_id,
    schema_name as dataset_id,
    option_value as description
FROM `{self.project_id}`.INFORMATION_SCHEMA.SCHEMATA_OPTIONS
WHERE schema_name = '{dataset_id}'
    AND option_name = 'description'
""").to_dataframe()

        if df.empty:
            data = [{"project_id": self.project_id, "dataset_id": dataset_id, "description": None}]
            df = pd.DataFrame(data)

        if cache:
            self._cache["schema_info"] = df

        return df

    @wrap_bigquery_errors
    @log_stage
    def extract_table_info(self, dataset_id: str | None = None, cache: bool = True) -> pd.DataFrame:
        """
        Extract BigQuery table information from the specified dataset.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        cache: bool = True
            Whether to cache the extract. If True, will cache the table information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame containing the BigQuery table information.
        """
        dataset_id = self._get_dataset_id(dataset_id)

        df = self.client.query(f"""
SELECT
    tables.table_catalog,
    tables.table_schema,
    tables.table_name,
    tables.table_type,
    tables.creation_time,
    tables.ddl,
    table_options.option_value as description
FROM `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.TABLES as tables
    LEFT JOIN `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.TABLE_OPTIONS as table_options
        ON tables.table_catalog = table_options.table_catalog
        AND tables.table_schema = table_options.table_schema
        AND tables.table_name = table_options.table_name
        AND table_options.option_name = 'description'
WHERE table_type = 'BASE TABLE'
ORDER BY table_name
""").to_dataframe()

        if cache:
            self._cache["table_info"] = df

        return df

    @wrap_bigquery_errors
    @log_stage
    def extract_column_info(
        self, dataset_id: str | None = None, cache: bool = True
    ) -> pd.DataFrame:
        """
        Extract BigQuery column information.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        cache: bool = True
            Whether to cache the extract. If True, will cache the column information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame containing the BigQuery column information.
        """

        def _is_pk(row: pd.Series) -> bool:
            return isinstance(row["constraint_name"], str) and row["constraint_name"].endswith(
                "pk$"
            )

        def _is_fk(row: pd.Series) -> bool:
            return isinstance(row["constraint_name"], str) and ".fk_" in row["constraint_name"]

        dataset_id = self._get_dataset_id(dataset_id)

        df = self.client.query(f"""
SELECT
    columns.table_catalog,
    columns.table_schema,
    columns.table_name,
    columns.column_name,
    columns.is_nullable,
    columns.data_type,
    column_field_paths.description,
    key_column_usage.constraint_name

FROM `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.COLUMNS as columns
    LEFT JOIN `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS column_field_paths
        ON columns.table_schema = column_field_paths.table_schema
        AND columns.table_name = column_field_paths.table_name
        AND columns.column_name = column_field_paths.column_name

    LEFT JOIN `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.KEY_COLUMN_USAGE key_column_usage
        ON columns.table_schema = key_column_usage.table_schema
        AND columns.table_name = key_column_usage.table_name
        AND columns.column_name = key_column_usage.column_name
""").to_dataframe()

        df["is_primary_key"] = df.apply(_is_pk, axis=1)
        df["is_foreign_key"] = df.apply(_is_fk, axis=1)

        if cache:
            self._cache["column_info"] = df

        return df

    @wrap_bigquery_errors
    @log_stage
    def extract_column_references_info(
        self, dataset_id: str | None = None, cache: bool = True
    ) -> pd.DataFrame:
        """
        Extract BigQuery column references information.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        cache: bool = True
            Whether to cache the extract. If True, will cache the column references information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame containing the BigQuery column references information.
        """
        dataset_id = self._get_dataset_id(dataset_id)

        df = self.client.query(f"""
SELECT
    tc.constraint_catalog,
    tc.constraint_schema,
    tc.constraint_name,
    tc.constraint_type,
    tc.table_name,
    kcu.column_name,
    kcu.ordinal_position,
    ccu.table_name AS referenced_table,
    ccu.column_name AS referenced_column
FROM `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
    LEFT JOIN `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
        ON tc.constraint_name = kcu.constraint_name
    LEFT JOIN `{self.project_id}`.`{dataset_id}`.INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
        ON tc.constraint_name = ccu.constraint_name
ORDER BY tc.table_name, tc.constraint_type, kcu.ordinal_position
""").to_dataframe()

        if cache:
            self._cache["column_references_info"] = df

        return df

    @wrap_bigquery_errors
    def extract_column_unique_values_for_table(
        self,
        table_name: str,
        column_names: list[str],
        dataset_id: str | None = None,
        limit: int = 10,
        cache: bool = True,
        column_info: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """
        Extract BigQuery column unique values to be used as reference values.

        Parameters
        ----------
        table_name: str
            The table name.
        column_names: list[str]
            List of column names to extract unique values from.
         dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        limit: int
            The number of unique values to extract per column.
        cache: bool = True
            Whether to cache the extract. If True, will cache the column unique values in the instance.
        column_info: Optional[pd.DataFrame] = None
            The column information. If not provided, will use cached column information.
            Used to determine column data types to skip array columns.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame with columns: column_name, unique_value, column_id,
            value_id, project_id, dataset_id, table_name. Each row represents one
            unique value for a column, carrying the table's name-parts.
        """
        dataset_id = self._get_dataset_id(dataset_id)

        # Get column_info to check data types
        column_info = column_info or self._cache.get("column_info", None)

        # Build ARRAY_AGG aggregation for each column, skipping array columns
        select_clauses = []
        for col in column_names:
            # Check if this column is an array or struct type
            if column_info is not None:
                col_data_type = column_info[
                    (column_info["table_name"] == table_name) & (column_info["column_name"] == col)
                ]["data_type"]

                # Skip non-groupable types — ARRAY_AGG(DISTINCT) requires a groupable
                # argument, which excludes ARRAY, STRUCT, GEOGRAPHY, JSON, and BIGNUMERIC.
                if not col_data_type.empty:
                    data_type = col_data_type.iloc[0]
                    if data_type.startswith(("ARRAY", "STRUCT", "GEOGRAPHY", "JSON", "BIGNUMERIC")):
                        continue

            select_clauses.append(
                f"ARRAY_AGG(DISTINCT `{col}` IGNORE NULLS LIMIT {limit}) as `{col}`"
            )

        # If all columns are arrays, return an empty DataFrame with expected structure
        if not select_clauses:
            return pd.DataFrame(
                columns=[
                    "column_name",
                    "unique_value",
                    "column_id",
                    "value_id",
                    "project_id",
                    "dataset_id",
                    "table_name",
                ]
            )

        query = f"""
        SELECT {", ".join(select_clauses)}
        FROM `{self.project_id}`.`{dataset_id}`.{table_name}
        """

        df = self.client.query(query).to_dataframe()
        # Reshape to long format: column_name, unique_value
        # Melt the dataframe to get column names as a column, then explode the arrays
        result = df.melt(var_name="column_name", value_name="unique_value")
        result = result.explode("unique_value").dropna().reset_index(drop=True)

        result["unique_value"] = result["unique_value"].astype(str)

        # Add column_id using normalized ID generation
        result["column_id"] = result["column_name"].apply(
            lambda col: generate_column_id(self.project_id, dataset_id, table_name, col)
        )

        # Hash the unique value and append to column_id for value_id
        if result.empty:
            result["value_id"] = pd.Series(dtype=str)
        else:
            result["value_id"] = result.apply(
                lambda row: (
                    row["column_id"]
                    + "."
                    + hashlib.md5(row["unique_value"].encode(), usedforsecurity=False).hexdigest()
                ),
                axis=1,
            )

        # Carry the table's name-parts so downstream normalization can build value
        # records without re-deriving them. Additive: existing consumers read only
        # column_name/unique_value/column_id/value_id.
        result["project_id"] = self.project_id
        result["dataset_id"] = dataset_id
        result["table_name"] = table_name

        # TODO: Handle caching duplicate column information if method run multiple times for same table and columns.
        if cache:
            self._cache["column_unique_values"] = pd.concat(
                [self._cache.get("column_unique_values", pd.DataFrame()), result], ignore_index=True
            )

        return result

    @wrap_bigquery_errors
    @log_stage
    def extract_column_unique_values_for_all_tables(
        self,
        dataset_id: str | None = None,
        table_info: pd.DataFrame | None = None,
        column_info: pd.DataFrame | None = None,
        cache: bool = True,
    ) -> pd.DataFrame:
        """
        Extract BigQuery column unique values for all tables in the dataset.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        table_info: Optional[pd.DataFrame] = None
            The table information. If not provided, will use cached table information.
        column_info: Optional[pd.DataFrame] = None
            The column information. If not provided, will use cached column information.
        cache: bool = True
            Whether to cache the extract. If True, will cache the column unique values in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame.
            Each row represents one unique value for a column.
        """
        column_info = column_info or self._cache.get("column_info", None)
        if column_info is None:
            raise StateError(
                "Column information is required to extract column unique values for all tables. Please use `extract_column_info` method to extract column information. You may cache results by setting method argument `cache` to True."
            )

        table_info = table_info or self._cache.get("table_info", None)
        if table_info is None:
            raise StateError(
                "Table information is required to extract column unique values for all tables. Please use `extract_table_info` method to extract table information. You may cache results by setting method argument `cache` to True."
            )

        dataset_id = self._get_dataset_id(dataset_id)

        value_info = pd.DataFrame()
        for table_name in table_info["table_name"].unique():
            column_names = column_info[column_info["table_name"] == table_name][
                "column_name"
            ].unique()
            value_info = pd.concat(
                [
                    value_info,
                    self.extract_column_unique_values_for_table(
                        table_name, column_names, dataset_id
                    ),
                ]
            )

        if cache:
            self._cache["column_unique_values"] = pd.concat(
                [self._cache.get("column_unique_values", pd.DataFrame()), value_info],
                ignore_index=True,
            )

        return value_info
