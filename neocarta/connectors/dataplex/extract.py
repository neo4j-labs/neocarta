"""Extract metadata from GCP Dataplex."""

import google.auth
import google.auth.transport.requests
import pandas as pd
import requests
from google.cloud import dataplex_v1

from ..utils.generate_id import generate_business_term_id, generate_column_id, generate_table_id
from .models import (
    BigQueryMetadataInfoResponse,
    DataplexExtractorCache,
    EntryLinkInfoResponse,
    GlossaryInfoResponse,
)
from .utils import parse_business_term_slug, parse_category_slug, parse_glossary_resource_path


class DataplexExtractor:
    """Extractor class for Dataplex."""

    def __init__(
        self,
        catalog_client: dataplex_v1.CatalogServiceClient,
        glossary_client: dataplex_v1.BusinessGlossaryServiceClient,
        project_id: str,
        project_number: str,
        dataplex_location: str,
        dataset_id: str | None = None,
    ) -> None:
        """
        Initialize the Dataplex extractor.

        Parameters
        ----------
        catalog_client: dataplex_v1.CatalogServiceClient
            The Dataplex Catalog client.
        glossary_client: dataplex_v1.BusinessGlossaryServiceClient
            The Dataplex Business Glossary client.
        project_id: str
            The GCP project ID. If not provided, will use the project ID from the client.
        project_number: str
            The GCP project number.
        dataset_id: Optional[str] = None
            The BigQuery dataset ID.
        dataplex_location: str
            The Dataplex location (e.g. 'us-central1' or 'us').
        """
        self.catalog_client = catalog_client
        self.glossary_client = glossary_client
        self.project_id = project_id
        self.project_number = project_number
        self.dataset_id = dataset_id
        self.dataplex_location = dataplex_location

        self._cache: DataplexExtractorCache = DataplexExtractorCache()

    @property
    def database_info(self) -> pd.DataFrame:
        """Get the database information DataFrame."""
        cols = ["project_id", "service", "platform"]
        return self._cache.get("table_info", pd.DataFrame(columns=cols)).drop_duplicates(
            subset=["project_id"]
        )[cols]

    @property
    def schema_info(self) -> pd.DataFrame:
        """Get the schema information DataFrame."""
        cols = ["project_id", "dataset_id"]
        return self._cache.get("table_info", pd.DataFrame(columns=cols)).drop_duplicates(
            subset=["project_id", "dataset_id"]
        )[cols]

    @property
    def table_info(self) -> pd.DataFrame:
        """Get the table information DataFrame."""
        cols = ["project_id", "dataset_id", "table_id", "table_display_name", "table_description"]
        return self._cache.get("table_info", pd.DataFrame(columns=cols)).drop_duplicates(
            subset=["project_id", "dataset_id", "table_id"]
        )[cols]

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
        return self._cache.get("table_info", pd.DataFrame(columns=cols)).drop_duplicates(
            subset=["project_id", "dataset_id", "table_id", "column_name"]
        )[cols]

    @property
    def glossary_info(self) -> pd.DataFrame:
        """Get the glossary information DataFrame."""
        cols = ["glossary_id", "glossary_name", "glossary_resource_path"]
        df = self._cache.get(
            "glossary_info", pd.DataFrame(columns=["glossary_id", "glossary_name", "category_id"])
        )
        df = df[df["category_id"].str.contains("/categories/", na=False)].copy()
        df["glossary_resource_path"] = df["category_id"].apply(parse_glossary_resource_path)
        return df.drop_duplicates(subset=["glossary_id"])[cols]

    @property
    def category_info(self) -> pd.DataFrame:
        """Get the category information DataFrame."""
        cols = ["glossary_id", "category_id"]
        df = self._cache.get("glossary_info", pd.DataFrame(columns=cols))
        df = df[df["category_id"].str.contains("/categories/", na=False)]
        return df.drop_duplicates(subset=["glossary_id", "category_id"])[cols]

    @property
    def business_term_info(self) -> pd.DataFrame:
        """Get the business term information DataFrame."""
        cols = ["glossary_id", "category_id", "term_id", "term_name", "term_description"]
        df = self._cache.get("glossary_info", pd.DataFrame(columns=cols))
        df = df[df["category_id"].str.contains("/categories/", na=False)]
        return df.drop_duplicates(subset=["glossary_id", "category_id", "term_id"])[cols]

    @property
    def column_term_info(self) -> pd.DataFrame:
        """Get entry links where a Column is tagged with a BusinessTerm."""
        cols = ["entity_id", "term_id", "business_term_id"]
        entry_df = self._cache.get(
            "entry_link_info", pd.DataFrame(columns=["entity_id", "entity_type", "term_id"])
        )
        col_df = entry_df[entry_df["entity_type"] == "COLUMN"].drop_duplicates(
            subset=["entity_id", "term_id"]
        )[["entity_id", "term_id"]]
        if col_df.empty:
            return pd.DataFrame(columns=cols)
        glossary_df = self._cache.get(
            "glossary_info", pd.DataFrame(columns=["glossary_id", "category_id", "term_id"])
        )[["glossary_id", "category_id", "term_id"]].drop_duplicates(subset=["term_id"])
        merged = col_df.merge(glossary_df, on="term_id", how="left")
        merged["business_term_id"] = merged.apply(
            lambda row: generate_business_term_id(
                row["glossary_id"],
                parse_category_slug(row["category_id"]),
                parse_business_term_slug(row["term_id"]),
            ),
            axis=1,
        )
        return merged[cols]

    @property
    def table_term_info(self) -> pd.DataFrame:
        """Get entry links where a Table is tagged with a BusinessTerm."""
        cols = ["entity_id", "term_id", "business_term_id"]
        entry_df = self._cache.get(
            "entry_link_info", pd.DataFrame(columns=["entity_id", "entity_type", "term_id"])
        )
        tbl_df = entry_df[entry_df["entity_type"] == "TABLE"].drop_duplicates(
            subset=["entity_id", "term_id"]
        )[["entity_id", "term_id"]]
        if tbl_df.empty:
            return pd.DataFrame(columns=cols)
        glossary_df = self._cache.get(
            "glossary_info", pd.DataFrame(columns=["glossary_id", "category_id", "term_id"])
        )[["glossary_id", "category_id", "term_id"]].drop_duplicates(subset=["term_id"])
        merged = tbl_df.merge(glossary_df, on="term_id", how="left")
        merged["business_term_id"] = merged.apply(
            lambda row: generate_business_term_id(
                row["glossary_id"],
                parse_category_slug(row["category_id"]),
                parse_business_term_slug(row["term_id"]),
            ),
            axis=1,
        )
        return merged[cols]

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
            raise ValueError(
                "Dataset ID is required in either constructor as `dataset_id` or as an argument to `extract_schema_info` method."
            )

        return dataset_id

    def _extract_bigquery_dataset_table_ids(
        self,
        dataset_id: str | None = None,
    ) -> list[str]:
        """
        Discover all BigQuery table IDs in a dataset via Dataplex Universal Catalog.

        Lists entries in the managed ``@bigquery`` entry group and filters for
        entries whose name contains the target dataset's table path.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The BigQuery dataset ID. If not provided, will use default instance `dataset_id`.

        Returns:
        -------
        list[str]
            A list of table IDs within the dataset.
        """
        dataset_id = self._get_dataset_id(dataset_id)

        entry_group = (
            f"projects/{self.project_number}/locations/{self.dataplex_location}"
            f"/entryGroups/@bigquery"
        )

        # Table entries have names of the form:
        # .../@bigquery/entries/bigquery.googleapis.com/projects/{project_id}/datasets/{dataset_id}/tables/{table_id}
        table_path_segment = (
            f"bigquery.googleapis.com/projects/{self.project_id}/datasets/{dataset_id}/tables/"
        )

        table_ids = []
        for entry in self.catalog_client.list_entries(parent=entry_group):
            if table_path_segment in entry.name:
                table_ids.append(entry.name.split("/tables/")[-1])

        return table_ids

    def extract_bigquery_info_for_table(
        self, table_id: str, dataset_id: str | None = None, cache: bool = True
    ) -> pd.DataFrame:
        """
        Extract full table metadata from Dataplex Universal Catalog for a BigQuery table.
        Returns project, dataset, table, schema, and service info.

        Parameters
        ----------
        table_id: str
            The BigQuery table ID.
        dataset_id: Optional[str] = None
            The BigQuery dataset ID. If not provided, will use default instance `dataset_id`.
        cache: bool = True
            Whether to cache the extract. If True, will cache the table information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame with one row per column.
            Has columns: project_id, project_number, dataset_id, table_id, table_display_name, table_description, column_name, column_data_type, column_metadata_type, column_mode, column_description, service, platform, location, resource_name, fully_qualified_name, parent_entry, entry_type.
        """
        dataset_id = self._get_dataset_id(dataset_id)

        table_entry_name = f"projects/{self.project_number}/locations/{self.dataplex_location}/entryGroups/@bigquery/entries/bigquery.googleapis.com/projects/{self.project_id}/datasets/{dataset_id}/tables/{table_id}"

        request = dataplex_v1.LookupEntryRequest(
            name=f"projects/{self.project_id}/locations/{self.dataplex_location}",
            entry=table_entry_name,
            view=dataplex_v1.EntryView.FULL,
        )
        entry = self.catalog_client.lookup_entry(request=request)

        # Parse FQN: "bigquery:project.demo_ecommerce.customers"
        fqn = entry.fully_qualified_name

        # Entry source metadata
        src = entry.entry_source

        # Storage aspect for resource name
        storage = {}
        for key, aspect in entry.aspects.items():
            if "storage" in key and aspect.data:
                storage = dict(aspect.data)

        # Schema fields
        schema_fields = []
        for key, aspect in entry.aspects.items():
            if "schema" in key and aspect.data:
                for field in aspect.data["fields"]:
                    schema_fields.append(dict(field))

        records = []
        for col in schema_fields:
            records.append(
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
            )

        # TODO: Handle caching duplicate table information if method run multiple times for same table.
        df = pd.DataFrame(records)
        if cache:
            self._cache["table_info"] = pd.concat(
                [self._cache.get("table_info", pd.DataFrame()), df], ignore_index=True
            )

        return df

    def extract_bigquery_info_for_all_tables(
        self, dataset_id: str | None = None, cache: bool = True
    ) -> pd.DataFrame:
        """
        Extract full table metadata from Dataplex Universal Catalog for all BigQuery tables in a dataset.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The BigQuery dataset ID. If not provided, will use default instance `dataset_id`.
        cache: bool = True
            Whether to cache the extract. If True, will cache the table information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame with one row per table column.
        """
        dataset_id = self._get_dataset_id(dataset_id)

        table_ids = self._extract_bigquery_dataset_table_ids(dataset_id)

        df = pd.DataFrame()
        for table_id in table_ids:
            df = pd.concat(
                [df, self.extract_bigquery_info_for_table(table_id, dataset_id, cache=False)],
                ignore_index=True,
            )

        if cache:
            self._cache["table_info"] = pd.concat(
                [self._cache.get("table_info", pd.DataFrame()), df], ignore_index=True
            )

        return df

    @staticmethod
    def _parse_glossary_category_id(term_parent: str) -> str | None:
        """
        Parse a Dataplex term parent to a category ID
        (projects/{project}/locations/{location}/glossaries/{glossary}/categories/{category}).
        """
        parts = term_parent.split("/")
        if parts[-2] == "categories":
            return parts[-1]
        return None

    def extract_glossary_info(self, cache: bool = True) -> pd.DataFrame:
        """
        Extract all glossary terms from all glossaries in the given location.

        Parameters
        ----------
        cache: bool = True
            Whether to cache the extract. If True, will cache the glossary information in the instance.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame with one row per term.
            Has columns: term_id, term_name, term_description, glossary_id, glossary_name, term_parent, category_id.
        """
        parent = f"projects/{self.project_id}/locations/{self.dataplex_location}"

        records = []

        try:
            glossaries = self.glossary_client.list_glossaries(parent=parent)
        except Exception as e:
            print(f"Error listing glossaries: {e}")
            return []

        for glossary in glossaries:
            glossary_id = glossary.name.split("/")[-1]
            glossary_name = glossary.display_name or glossary_id

            try:
                terms = self.glossary_client.list_glossary_terms(parent=glossary.name)
            except Exception as e:
                print(f"Error listing terms for glossary {glossary_id}: {e}")
                continue

            for term in terms:
                records.append(
                    GlossaryInfoResponse(
                        term_id=term.name,
                        term_name=term.display_name or term.name.split("/")[-1],
                        term_description=term.description or "",
                        glossary_id=glossary_id,
                        glossary_name=glossary_name,
                        term_parent=term.parent,
                        category_id=term.parent,
                    )
                )

        # TODO: Handle caching duplicate glossary information if method run multiple times for same glossary.
        df = pd.DataFrame(records)
        if cache:
            self._cache["glossary_info"] = pd.concat(
                [self._cache.get("glossary_info", pd.DataFrame()), df], ignore_index=True
            )

        return df

    def _lookup_entry_links_page(
        self,
        session: requests.Session,
        entry: str,
        entry_link_type: str,
        page_size: int = 10,
    ) -> list[dict]:
        """Page through all lookupEntryLinks results for a single entry."""
        url = (
            f"https://dataplex.googleapis.com/v1"
            f"/projects/{self.project_id}/locations/{self.dataplex_location}:lookupEntryLinks"
        )
        params: dict = {
            "entry": entry,
            "entryLinkTypes": entry_link_type,
            "pageSize": page_size,
        }
        links: list[dict] = []
        while True:
            response = session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            links.extend(data.get("entryLinks", []))
            next_token = data.get("nextPageToken")
            if not next_token:
                break
            params["pageToken"] = next_token
        return links

    @staticmethod
    def _parse_source_entry(link: dict) -> tuple[str, str] | None:
        """
        Parse the SOURCE entry reference from an EntryLink dict.

        Returns (entity_id, entity_type) where entity_id is the Neo4j node id
        (project_id.dataset_id.table_id[.column_name]) and entity_type is
        "COLUMN" or "TABLE". Returns None if the link cannot be parsed.

        The term_id is NOT parsed here — callers should use the known term.name
        from the SDK directly to avoid project_id vs project_number ambiguity.
        """
        refs = {r["type"]: r for r in link.get("entryReferences", [])}
        source = refs.get("SOURCE")
        if not source:
            return None

        # SOURCE entry name format:
        # projects/{num}/locations/{loc}/entryGroups/@bigquery/entries/bigquery.googleapis.com/projects/{project_id}/datasets/{dataset}/tables/{table}
        try:
            bq_resource = source["name"].split("/entries/")[-1]
            parts = bq_resource.split("/")
            bq_project_id = parts[2]
            dataset_id = parts[4]
            table_id = parts[6]
        except (IndexError, KeyError):
            return None

        path = source.get("path", "")
        if path:
            column_name = path.split(".")[-1]
            entity_id = generate_column_id(bq_project_id, dataset_id, table_id, column_name)
            entity_type = "COLUMN"
        else:
            entity_id = generate_table_id(bq_project_id, dataset_id, table_id)
            entity_type = "TABLE"

        return entity_id, entity_type

    def extract_entry_links(
        self,
        entry_link_type: str = "projects/dataplex-types/locations/global/entryLinkTypes/definition",
        cache: bool = True,
    ) -> pd.DataFrame:
        """
        Retrieve all entry links between glossary terms and BigQuery assets.

        Uses the projects.locations:lookupEntryLinks REST endpoint (not yet in the
        Python SDK) to discover which tables and columns are tagged with each term.

        Parameters
        ----------
        entry_link_type : str
            The entry link type resource name to filter by.
        cache : bool
            Whether to cache the result on the instance.

        Returns:
        -------
        pd.DataFrame
            One row per (entity, term) pair.
            Columns: entity_id, entity_type, term_id.
        """
        glossary_info = self._cache.get("glossary_info", pd.DataFrame())
        if glossary_info.empty:
            raise RuntimeError(
                "extract_glossary_info() must be called before extract_entry_links()."
            )

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = google.auth.transport.requests.AuthorizedSession(creds)

        records: list[EntryLinkInfoResponse] = []

        for _, row in glossary_info.drop_duplicates(subset=["term_id"]).iterrows():
            term_name = row["term_id"]
            term_slug = term_name.split("/terms/")[-1]
            glossary_id = term_name.split("/glossaries/")[1].split("/")[0]

            term_entry = (
                f"projects/{self.project_number}/locations/{self.dataplex_location}"
                f"/entryGroups/@dataplex/entries/"
                f"projects/{self.project_number}/locations/{self.dataplex_location}"
                f"/glossaries/{glossary_id}/terms/{term_slug}"
            )

            try:
                links = self._lookup_entry_links_page(session, term_entry, entry_link_type)
            except Exception as e:
                print(f"Error looking up entry links for term '{term_slug}': {e}")
                continue

            for link in links:
                parsed = self._parse_source_entry(link)
                if parsed:
                    entity_id, entity_type = parsed
                    records.append(
                        EntryLinkInfoResponse(
                            entity_id=entity_id,
                            entity_type=entity_type,
                            term_id=term_name,
                        )
                    )

        _entry_link_cols = ["entity_id", "entity_type", "term_id"]
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=_entry_link_cols)
        if cache:
            self._cache["entry_link_info"] = pd.concat(
                [
                    self._cache.get("entry_link_info", pd.DataFrame(columns=_entry_link_cols)),
                    df,
                ],
                ignore_index=True,
            )

        return df
