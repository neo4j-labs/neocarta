"""Collibra schema extractor: communities, physical domains, table/column assets."""

import warnings
from collections import Counter
from typing import Any

import pandas as pd

from ....enums import NodeLabel
from ....warnings import UnmappedCollibraAssetTypeWarning
from ..client import CollibraClient
from ..resolve import CollibraTypeResolver

# Description-like attribute types, in priority order (matched case-insensitively).
_DESCRIPTION_ATTRIBUTE_TYPES = ("description", "definition", "note")


class CollibraSchemaExtractor:
    """Extract Collibra physical-layer metadata into neocarta-shaped DataFrames.

    Pulls communities (→ Database), physical-data domains (→ Schema), and the
    Table-/Column-typed assets within them, plus the "contains column" relations
    used to attach columns to their parent table. Cached state is exposed through
    read-only ``@property`` accessors consumed by :class:`CollibraSchemaTransformer`.

    Parameters
    ----------
    client : CollibraClient
        Authenticated Collibra HTTP client.
    """

    def __init__(self, client: CollibraClient) -> None:
        """Initialise the extractor with an empty cache."""
        self._client = client
        self._cache: dict[str, pd.DataFrame] = {}

    # ------------------------------------------------------------------ #
    # Cache accessors
    # ------------------------------------------------------------------ #

    @property
    def community_info(self) -> pd.DataFrame:
        """Communities (→ Database nodes)."""
        return self._cache.get("community_info", pd.DataFrame())

    @property
    def schema_domain_info(self) -> pd.DataFrame:
        """Physical-data domains (→ Schema nodes)."""
        return self._cache.get("schema_domain_info", pd.DataFrame())

    @property
    def table_info(self) -> pd.DataFrame:
        """Table-typed assets."""
        return self._cache.get("table_info", pd.DataFrame())

    @property
    def column_info(self) -> pd.DataFrame:
        """Column-typed assets (with resolved parent table)."""
        return self._cache.get("column_info", pd.DataFrame())

    # ------------------------------------------------------------------ #
    # Extraction entry point
    # ------------------------------------------------------------------ #

    def extract(
        self,
        community_ids: list[str] | None = None,
        domain_ids: list[str] | None = None,
        asset_type_names: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
    ) -> None:
        """Run all extraction steps and populate the cache.

        Parameters
        ----------
        community_ids, domain_ids : list[str], optional
            Restrict extraction to these Collibra community/domain UUIDs.
        asset_type_names : list[str], optional
            Restrict assets to these Collibra asset-type display names.
        include_nodes : list[NodeLabel], optional
            When given, only these node types are cached. ``None`` caches everything.
        """
        self._cache.clear()
        resolver = CollibraTypeResolver(*self._client.discover_types())

        print("Extracting Collibra schema metadata...")
        communities = self._extract_communities(community_ids)
        domains = self._extract_schema_domains(resolver, communities, domain_ids)
        self._extract_assets(resolver, domains, asset_type_names, include_nodes)

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #

    def _extract_communities(self, community_ids: list[str] | None) -> pd.DataFrame:
        """Fetch communities (optionally scoped) and cache them."""
        rows = [
            {
                "community_id": c["id"],
                "community_name": c["name"],
                "description": c.get("description"),
            }
            for c in self._client.get_paginated("/rest/2.0/communities", {})
            if not community_ids or c["id"] in community_ids
        ]
        df = pd.DataFrame(rows, columns=["community_id", "community_name", "description"])
        self._cache["community_info"] = df
        print(f"  Extracted {len(df)} communities")
        return df

    def _extract_schema_domains(
        self,
        resolver: CollibraTypeResolver,
        communities: pd.DataFrame,
        domain_ids: list[str] | None,
    ) -> pd.DataFrame:
        """Fetch domains whose domain type maps to ``Schema`` and cache them."""
        community_ids = set(communities["community_id"]) if not communities.empty else set()
        rows: list[dict[str, Any]] = []
        for d in self._client.get_paginated("/rest/2.0/domains", {}):
            if domain_ids and d["id"] not in domain_ids:
                continue
            if community_ids and d["community"]["id"] not in community_ids:
                continue
            if resolver.neocarta_domain_type(d["type"]["name"]) != "Schema":
                continue
            rows.append(
                {
                    "domain_id": d["id"],
                    "domain_name": d["name"],
                    "description": d.get("description"),
                    "community_id": d["community"]["id"],
                }
            )
        df = pd.DataFrame(
            rows, columns=["domain_id", "domain_name", "description", "community_id"]
        ).drop_duplicates(subset="domain_id")
        self._cache["schema_domain_info"] = df
        print(f"  Extracted {len(df)} schema domains")
        return df

    def _extract_assets(
        self,
        resolver: CollibraTypeResolver,
        domains: pd.DataFrame,
        asset_type_names: list[str] | None,
        include_nodes: list[NodeLabel] | None,
    ) -> None:
        """Fetch Table/Column assets in the given domains and resolve column parents."""
        domain_ids = list(domains["domain_id"]) if not domains.empty else []
        type_uuids = resolver.asset_type_ids_for_names(asset_type_names) if asset_type_names else []

        tables: list[dict[str, Any]] = []
        columns: list[dict[str, Any]] = []
        column_collibra_ids: list[str] = []
        unmapped: Counter[str] = Counter()

        for did in domain_ids:
            params: dict[str, Any] = {"domainId": did}
            if type_uuids:
                params["typeId"] = type_uuids
            for a in self._client.get_paginated("/rest/2.0/assets", params):
                neo_type = resolver.neocarta_asset_type(a["type"]["name"])
                row = {
                    "asset_id": a["id"],
                    "asset_name": a.get("displayName") or a["name"],
                    "domain_id": a["domain"]["id"],
                    "asset_type_name": a["type"]["name"],
                    "status": a["status"]["name"] if a.get("status") else None,
                }
                if neo_type == "Table":
                    tables.append(row)
                elif neo_type == "Column":
                    columns.append(row)
                    column_collibra_ids.append(a["id"])
                else:
                    unmapped[a["type"]["name"]] += 1

        descriptions = self._fetch_descriptions(
            [r["asset_id"] for r in tables] + [r["asset_id"] for r in columns]
        )
        for r in (*tables, *columns):
            r["description"] = descriptions.get(r["asset_id"])

        column_parent = self._fetch_column_parent_tables(resolver, column_collibra_ids)
        for r in columns:
            r["table_collibra_id"] = column_parent.get(r["asset_id"])

        self._warn_unmapped(unmapped)
        self._cache_assets(tables, columns, include_nodes)

    def _cache_assets(
        self,
        tables: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        include_nodes: list[NodeLabel] | None,
    ) -> None:
        """Cache table/column DataFrames, honouring ``include_nodes``."""
        table_cols = [
            "asset_id",
            "asset_name",
            "domain_id",
            "asset_type_name",
            "status",
            "description",
        ]
        column_cols = [*table_cols, "table_collibra_id"]
        want_columns = include_nodes is None or NodeLabel.COLUMN in include_nodes
        # Tables are cached when requested OR when columns are (columns need their
        # parent table to build a stable id, per the contract's transient-association rule).
        if include_nodes is None or NodeLabel.TABLE in include_nodes or want_columns:
            self._cache["table_info"] = pd.DataFrame(tables, columns=table_cols)
            print(f"  Extracted {len(tables)} tables")
        if want_columns:
            self._cache["column_info"] = pd.DataFrame(columns, columns=column_cols)
            print(f"  Extracted {len(columns)} columns")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _fetch_descriptions(self, asset_ids: list[str]) -> dict[str, str]:
        """Fetch description-like attribute values, one ``assetId`` request per asset.

        ``GET /rest/2.0/attributes`` filters by a single ``assetId`` — there is no
        array form — so attributes are fetched per asset and the first present
        description-like value is kept.
        """
        out: dict[str, str] = {}
        for aid in asset_ids:
            by_type: dict[str, str] = {}
            for attr in self._client.get_paginated("/rest/2.0/attributes", {"assetId": aid}):
                value = attr.get("value")
                if value:
                    by_type.setdefault(attr["type"]["name"].lower(), value)
            for key in _DESCRIPTION_ATTRIBUTE_TYPES:
                if key in by_type:
                    out[aid] = by_type[key]
                    break
        return out

    def _fetch_column_parent_tables(
        self, resolver: CollibraTypeResolver, column_ids: list[str]
    ) -> dict[str, str]:
        """Map each column UUID to its parent table UUID via "contains column" relations."""
        if not column_ids:
            return {}
        column_set = set(column_ids)
        parent: dict[str, str] = {}
        for tid in resolver.relation_type_ids_for_neocarta({"HAS_COLUMN"}):
            for rel in self._client.get_paginated("/rest/2.0/relations", {"relationTypeId": tid}):
                if rel["target"]["id"] in column_set:
                    parent[rel["target"]["id"]] = rel["source"]["id"]
        return parent

    def _warn_unmapped(self, unmapped: Counter[str]) -> None:
        """Emit a single aggregated warning for skipped, out-of-scope asset types."""
        if not unmapped:
            return
        summary = ", ".join(f"{name} ({count})" for name, count in sorted(unmapped.items()))
        warnings.warn(
            f"Skipped {sum(unmapped.values())} Collibra assets outside the schema "
            f"sub-connector's scope (Table/Column): {summary}.",
            UnmappedCollibraAssetTypeWarning,
            stacklevel=2,
        )
