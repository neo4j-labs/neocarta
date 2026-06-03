"""Extract Dataplex business glossary terms and catalog-to-glossary entry links."""

import google.auth
import google.auth.transport.requests
import pandas as pd
import requests
from google.cloud import dataplex_v1

from ....errors import StateError
from ...utils.generate_id import (
    generate_business_term_id,
    generate_column_id,
    generate_table_id,
)
from ..models import EntryLinkInfoResponse, GlossaryInfoResponse
from ..utils import parse_business_term_slug, parse_category_slug, parse_glossary_resource_path

# Standard Dataplex link type for glossary-term tagging. The lookupEntryLinks
# REST endpoint requires a type filter; this is the only documented one for
# "this catalog entity is defined by this term" links.
_ENTRY_LINK_TYPE = "projects/dataplex-types/locations/global/entryLinkTypes/definition"


class DataplexGlossaryExtractor:
    """
    Extractor for Dataplex business glossary content and the cross-domain entry
    links that tie catalog entries (BigQuery tables/columns) to glossary terms.

    Parameters
    ----------
    glossary_client : dataplex_v1.BusinessGlossaryServiceClient
        The Dataplex Business Glossary client.
    project_id : str
        The GCP project ID.
    project_number : str
        The GCP project number.
    dataplex_location : str
        The Dataplex location (e.g. ``us-central1`` or ``us``).
    """

    def __init__(
        self,
        glossary_client: dataplex_v1.BusinessGlossaryServiceClient,
        project_id: str,
        project_number: str,
        dataplex_location: str,
    ) -> None:
        """Initialize the Dataplex glossary extractor."""
        self.glossary_client = glossary_client
        self.project_id = project_id
        self.project_number = project_number
        self.dataplex_location = dataplex_location

        self._glossary_info: pd.DataFrame = pd.DataFrame()
        self._entry_link_info: pd.DataFrame = pd.DataFrame()

    @property
    def glossary_info(self) -> pd.DataFrame:
        """Get the glossary information DataFrame."""
        cols = ["glossary_id", "glossary_name", "glossary_resource_path"]
        if self._glossary_info.empty:
            return pd.DataFrame(columns=cols)
        df = self._glossary_info[
            self._glossary_info["category_id"].str.contains("/categories/", na=False)
        ].copy()
        df["glossary_resource_path"] = df["category_id"].apply(parse_glossary_resource_path)
        return df.drop_duplicates(subset=["glossary_id"])[cols]

    @property
    def category_info(self) -> pd.DataFrame:
        """Get the category information DataFrame."""
        cols = ["glossary_id", "category_id"]
        if self._glossary_info.empty:
            return pd.DataFrame(columns=cols)
        df = self._glossary_info[
            self._glossary_info["category_id"].str.contains("/categories/", na=False)
        ]
        return df.drop_duplicates(subset=["glossary_id", "category_id"])[cols]

    @property
    def business_term_info(self) -> pd.DataFrame:
        """Get the business term information DataFrame."""
        cols = ["glossary_id", "category_id", "term_id", "term_name", "term_description"]
        if self._glossary_info.empty:
            return pd.DataFrame(columns=cols)
        df = self._glossary_info[
            self._glossary_info["category_id"].str.contains("/categories/", na=False)
        ]
        return df.drop_duplicates(subset=["glossary_id", "category_id", "term_id"])[cols]

    @property
    def column_term_info(self) -> pd.DataFrame:
        """Get entry links where a Column is tagged with a BusinessTerm."""
        cols = ["entity_id", "term_id", "business_term_id"]
        if self._entry_link_info.empty:
            return pd.DataFrame(columns=cols)
        col_df = self._entry_link_info[
            self._entry_link_info["entity_type"] == "COLUMN"
        ].drop_duplicates(subset=["entity_id", "term_id"])[["entity_id", "term_id"]]
        if col_df.empty:
            return pd.DataFrame(columns=cols)
        glossary_df = self._glossary_info[
            ["glossary_id", "category_id", "term_id"]
        ].drop_duplicates(subset=["term_id"])
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
        if self._entry_link_info.empty:
            return pd.DataFrame(columns=cols)
        tbl_df = self._entry_link_info[
            self._entry_link_info["entity_type"] == "TABLE"
        ].drop_duplicates(subset=["entity_id", "term_id"])[["entity_id", "term_id"]]
        if tbl_df.empty:
            return pd.DataFrame(columns=cols)
        glossary_df = self._glossary_info[
            ["glossary_id", "category_id", "term_id"]
        ].drop_duplicates(subset=["term_id"])
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

    def extract(self, include_entry_links: bool = True) -> None:
        """
        Extract all glossary terms and (optionally) their entry links to catalog assets.

        Parameters
        ----------
        include_entry_links : bool, default True
            Whether to also pull the catalog↔glossary entry links that back the
            TAGGED_WITH edges. Disable when the catalog isn't present in this
            Neo4j instance, or to skip the REST-API round trips.
        """
        self.extract_glossary_info()
        if include_entry_links:
            self.extract_entry_links()

    def extract_glossary_info(self) -> pd.DataFrame:
        """
        Extract all glossary terms from all glossaries in the configured location.

        Returns:
        -------
        pd.DataFrame
            One row per term. Cached on the instance and projected via
            :attr:`glossary_info` / :attr:`category_info` / :attr:`business_term_info`.
        """
        parent = f"projects/{self.project_id}/locations/{self.dataplex_location}"

        records = []
        try:
            glossaries = self.glossary_client.list_glossaries(parent=parent)
        except Exception as e:
            print(f"Error listing glossaries: {e}")
            return pd.DataFrame()

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

        df = pd.DataFrame(records)
        self._glossary_info = pd.concat([self._glossary_info, df], ignore_index=True)
        return df

    def extract_entry_links(self) -> pd.DataFrame:
        """
        Retrieve all entry links between glossary terms and BigQuery assets.

        Uses the ``projects.locations:lookupEntryLinks`` REST endpoint (not yet in
        the Python SDK) to discover which tables and columns are tagged with each
        term. Requires :meth:`extract_glossary_info` to have run first so the
        term list is available.

        Returns:
        -------
        pd.DataFrame
            One row per (entity, term) pair. Columns: ``entity_id``,
            ``entity_type``, ``term_id``.

        Raises:
        ------
        StateError
            If called before :meth:`extract_glossary_info`.
        """
        if self._glossary_info.empty:
            raise StateError("extract_glossary_info() must be called before extract_entry_links().")

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = google.auth.transport.requests.AuthorizedSession(creds)

        records: list[EntryLinkInfoResponse] = []
        for _, row in self._glossary_info.drop_duplicates(subset=["term_id"]).iterrows():
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
                links = self._lookup_entry_links_page(session, term_entry)
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
        self._entry_link_info = pd.concat(
            [
                self._entry_link_info
                if not self._entry_link_info.empty
                else pd.DataFrame(columns=_entry_link_cols),
                df,
            ],
            ignore_index=True,
        )
        return df

    def _lookup_entry_links_page(
        self,
        session: requests.Session,
        entry: str,
        page_size: int = 10,
    ) -> list[dict]:
        """Page through all lookupEntryLinks results for a single entry."""
        url = (
            f"https://dataplex.googleapis.com/v1"
            f"/projects/{self.project_id}/locations/{self.dataplex_location}:lookupEntryLinks"
        )
        params: dict = {
            "entry": entry,
            "entryLinkTypes": _ENTRY_LINK_TYPE,
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
        """
        refs = {r["type"]: r for r in link.get("entryReferences", [])}
        source = refs.get("SOURCE")
        if not source:
            return None

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
