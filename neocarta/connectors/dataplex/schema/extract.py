"""Extract BigQuery schema metadata from GCP Dataplex."""

import pandas as pd
from google.cloud import dataplex_v1

from ...._logging import log_stage
from ....errors import ConfigError
from ..models import BigQueryMetadataInfoResponse


class DataplexSchemaExtractor:
    """
    Extractor for BigQuery catalog metadata via Dataplex Universal Catalog.

    Pulls table/column information for a BigQuery dataset by walking the managed
    ``@bigquery`` entry group in Dataplex.

    Parameters
    ----------
    catalog_client : dataplex_v1.CatalogServiceClient
        The Dataplex Catalog client.
    project_id : str
        The GCP project ID.
    project_number : str
        The GCP project number.
    dataplex_location : str
        The Dataplex location (e.g. ``us-central1`` or ``us``).
    """

    def __init__(
        self,
        catalog_client: dataplex_v1.CatalogServiceClient,
        project_id: str,
        project_number: str,
        dataplex_location: str,
    ) -> None:
        """Initialize the Dataplex schema extractor."""
        self.catalog_client = catalog_client
        self.project_id = project_id
        self.project_number = project_number
        self.dataplex_location = dataplex_location

        self._table_info: pd.DataFrame = pd.DataFrame()

    @property
    def database_info(self) -> pd.DataFrame:
        """Get the database information DataFrame."""
        cols = ["project_id", "service", "platform"]
        if self._table_info.empty:
            return pd.DataFrame(columns=cols)
        return self._table_info.drop_duplicates(subset=["project_id"])[cols]

    @property
    def schema_info(self) -> pd.DataFrame:
        """Get the schema information DataFrame."""
        cols = ["project_id", "dataset_id"]
        if self._table_info.empty:
            return pd.DataFrame(columns=cols)
        return self._table_info.drop_duplicates(subset=["project_id", "dataset_id"])[cols]

    @property
    def table_info(self) -> pd.DataFrame:
        """Get the table information DataFrame."""
        cols = ["project_id", "dataset_id", "table_id", "table_display_name", "table_description"]
        if self._table_info.empty:
            return pd.DataFrame(columns=cols)
        return self._table_info.drop_duplicates(subset=["project_id", "dataset_id", "table_id"])[
            cols
        ]

    @property
    def column_info(self) -> pd.DataFrame:
        """Get the column information DataFrame."""
        cols = [
            "project_id",
            "dataset_id",
            "table_id",
            "column_name",
            "column_description",
            "column_data_type",
            "column_mode",
        ]
        if self._table_info.empty:
            return pd.DataFrame(columns=cols)
        return self._table_info.drop_duplicates(
            subset=["project_id", "dataset_id", "table_id", "column_name"]
        )[cols]

    @log_stage
    def extract(self, dataset_id: str) -> pd.DataFrame:
        """
        Extract BigQuery catalog metadata for all tables in a dataset.

        Walks the managed ``@bigquery`` entry group, looks up each table's full
        entry view, and stores one row per column on the instance cache.

        Parameters
        ----------
        dataset_id : str
            The BigQuery dataset ID.

        Returns:
        -------
        pd.DataFrame
            One row per (table, column). Also available via the
            :attr:`database_info` / :attr:`schema_info` / :attr:`table_info` /
            :attr:`column_info` projection properties.
        """
        if dataset_id is None:
            raise ConfigError("dataset_id is required for Dataplex schema extraction.")

        table_ids = self._list_bigquery_dataset_table_ids(dataset_id)

        df = pd.DataFrame()
        for table_id in table_ids:
            df = pd.concat(
                [df, self._lookup_table_entry(table_id, dataset_id)],
                ignore_index=True,
            )

        self._table_info = pd.concat([self._table_info, df], ignore_index=True)
        return df

    def _list_bigquery_dataset_table_ids(self, dataset_id: str) -> list[str]:
        """List all BigQuery table IDs in a dataset via the Dataplex catalog."""
        entry_group = (
            f"projects/{self.project_number}/locations/{self.dataplex_location}"
            f"/entryGroups/@bigquery"
        )
        table_path_segment = (
            f"bigquery.googleapis.com/projects/{self.project_id}/datasets/{dataset_id}/tables/"
        )
        table_ids = []
        for entry in self.catalog_client.list_entries(parent=entry_group):
            if table_path_segment in entry.name:
                table_ids.append(entry.name.split("/tables/")[-1])
        return table_ids

    def _lookup_table_entry(self, table_id: str, dataset_id: str) -> pd.DataFrame:
        """Look up the full entry view for one BigQuery table and return one row per column."""
        table_entry_name = (
            f"projects/{self.project_number}/locations/{self.dataplex_location}"
            f"/entryGroups/@bigquery/entries/bigquery.googleapis.com/projects/{self.project_id}"
            f"/datasets/{dataset_id}/tables/{table_id}"
        )

        request = dataplex_v1.LookupEntryRequest(
            name=f"projects/{self.project_id}/locations/{self.dataplex_location}",
            entry=table_entry_name,
            view=dataplex_v1.EntryView.FULL,
        )
        entry = self.catalog_client.lookup_entry(request=request)

        fqn = entry.fully_qualified_name
        src = entry.entry_source

        storage = {}
        for key, aspect in entry.aspects.items():
            if "storage" in key and aspect.data:
                storage = dict(aspect.data)

        schema_fields = []
        for key, aspect in entry.aspects.items():
            if "schema" in key and aspect.data:
                for field in aspect.data["fields"]:
                    schema_fields.append(dict(field))

        records = [
            BigQueryMetadataInfoResponse(
                project_id=self.project_id,
                project_number=self.project_number,
                dataset_id=dataset_id,
                table_id=table_id,
                table_display_name=src.display_name,
                table_description=src.description,
                column_name=col.get("name"),
                column_data_type=col.get("dataType"),
                column_metadata_type=col.get("metadataType"),
                column_mode=col.get("mode"),
                column_description=col.get("description", ""),
                service=src.system,
                platform=src.platform,
                location=src.location,
                resource_name=storage.get("resourceName", ""),
                fully_qualified_name=fqn,
                parent_entry=entry.parent_entry,
                entry_type=entry.entry_type,
            )
            for col in schema_fields
        ]

        return pd.DataFrame(records)
