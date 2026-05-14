"""Collibra Extractor: fetches raw metadata from Collibra APIs into DataFrames."""

import math
from typing import Any

import pandas as pd

from .client import CollibraClient
from .type_mapping import ASSET_TYPE_ALIASES

_ATTRIBUTE_BATCH_SIZE = 100


class CollibraExtractor:
    """
    Extractor that pulls Collibra metadata into neocarta-compatible DataFrames.

    Calls ``CollibraClient`` for paginated entity lists, batches attribute
    fetches (≤100 IDs per request), and optionally fetches technical lineage.

    Parameters
    ----------
    client : CollibraClient
        Authenticated Collibra HTTP client.
    community_ids : list[str] | None
        When provided, restrict extraction to these community UUIDs.
    domain_ids : list[str] | None
        When provided, restrict extraction to these domain UUIDs.
    asset_type_names : list[str] | None
        When provided, restrict extraction to assets whose type display name
        (case-insensitive) is in this list.
    include_lineage : bool
        Whether to fetch technical lineage via the Catalog Lineage API.
    """

    def __init__(
        self,
        client: CollibraClient,
        community_ids: list[str] | None = None,
        domain_ids: list[str] | None = None,
        asset_type_names: list[str] | None = None,
        include_lineage: bool = True,
    ) -> None:
        """Initialise the extractor and discover Collibra types."""
        self._client = client
        self._community_ids = community_ids
        self._domain_ids = domain_ids
        self._asset_type_names = [n.lower() for n in asset_type_names] if asset_type_names else None
        self._include_lineage = include_lineage
        self._cache: dict[str, pd.DataFrame] = {}

        # Discover UUID → display-name maps at startup.
        self._asset_types, self._domain_types, self._relation_types = client.discover_types()

        # Reverse maps: lower-name → uuid (for scoped type filtering)
        self._asset_type_by_name: dict[str, str] = {
            v.lower(): k for k, v in self._asset_types.items()
        }
        self._domain_type_by_name: dict[str, str] = {
            v.lower(): k for k, v in self._domain_types.items()
        }
        self._relation_type_by_name: dict[str, str] = {
            v.lower(): k for k, v in self._relation_types.items()
        }

    # ------------------------------------------------------------------
    # Type resolution helpers (exposed for transformer)
    # ------------------------------------------------------------------

    @property
    def asset_types(self) -> dict[str, str]:
        """UUID → display-name map for asset types."""
        return self._asset_types

    @property
    def domain_types(self) -> dict[str, str]:
        """UUID → display-name map for domain types."""
        return self._domain_types

    @property
    def relation_types(self) -> dict[str, str]:
        """UUID → display-name map for relation types."""
        return self._relation_types

    # ------------------------------------------------------------------
    # DataFrame cache properties
    # ------------------------------------------------------------------

    @property
    def community_info(self) -> pd.DataFrame:
        """Extracted communities DataFrame."""
        return self._cache.get("community_info", pd.DataFrame())

    @property
    def domain_info(self) -> pd.DataFrame:
        """Extracted domains DataFrame."""
        return self._cache.get("domain_info", pd.DataFrame())

    @property
    def asset_info(self) -> pd.DataFrame:
        """Extracted assets DataFrame."""
        return self._cache.get("asset_info", pd.DataFrame())

    @property
    def attribute_info(self) -> pd.DataFrame:
        """Extracted attributes DataFrame."""
        return self._cache.get("attribute_info", pd.DataFrame())

    @property
    def relation_info(self) -> pd.DataFrame:
        """Extracted relations DataFrame."""
        return self._cache.get("relation_info", pd.DataFrame())

    @property
    def lineage_info(self) -> pd.DataFrame:
        """Extracted lineage pairs DataFrame."""
        return self._cache.get("lineage_info", pd.DataFrame())

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def extract_community_info(self) -> pd.DataFrame:
        """Fetch all communities (or scoped subset) and return as DataFrame."""
        rows: list[dict[str, Any]] = []
        params: dict[str, Any] = {}
        if self._community_ids:
            params["communityId"] = self._community_ids

        raw = self._client.get_paginated("/rest/2.0/communities", params)
        for c in raw:
            if self._community_ids and c["id"] not in self._community_ids:
                continue
            rows.append(
                {
                    "community_id": c["id"],
                    "community_name": c["name"],
                    "description": c.get("description"),
                }
            )

        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(columns=["community_id", "community_name", "description"])
        )
        self._cache["community_info"] = df
        print(f"  Extracted {len(df)} communities")
        return df

    def extract_domain_info(self) -> pd.DataFrame:
        """Fetch all domains (optionally scoped) and return as DataFrame."""
        rows: list[dict[str, Any]] = []

        if self._community_ids:
            # Scoped: one request per community to minimise response size.
            iter_cids: list[str | None] = list(self._community_ids)
        else:
            iter_cids = [None]

        for cid in iter_cids:
            params: dict[str, Any] = {}
            if cid:
                params["communityId"] = cid
            if self._domain_ids:
                params["domainId"] = self._domain_ids

            for d in self._client.get_paginated("/rest/2.0/domains", params):
                if self._domain_ids and d["id"] not in self._domain_ids:
                    continue
                rows.append(
                    {
                        "domain_id": d["id"],
                        "domain_name": d["name"],
                        "description": d.get("description"),
                        "community_id": d["community"]["id"],
                        "domain_type_id": d["type"]["id"],
                        "domain_type_name": d["type"]["name"],
                    }
                )

        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(
                columns=[
                    "domain_id",
                    "domain_name",
                    "description",
                    "community_id",
                    "domain_type_id",
                    "domain_type_name",
                ]
            )
        )
        df = df.drop_duplicates(subset="domain_id")
        self._cache["domain_info"] = df
        print(f"  Extracted {len(df)} domains")
        return df

    def extract_asset_info(self) -> pd.DataFrame:
        """Fetch all assets (optionally scoped) and return as DataFrame."""
        rows: list[dict[str, Any]] = []

        if self._domain_ids:
            # Scoped: one request per domain to minimise response size.
            iter_dids: list[str | None] = list(self._domain_ids)
        else:
            iter_dids = [None]

        # Build optional asset type UUID filter
        type_uuids: list[str] = []
        if self._asset_type_names:
            for name in self._asset_type_names:
                uid = self._asset_type_by_name.get(name)
                if uid:
                    type_uuids.append(uid)

        for did in iter_dids:
            params: dict[str, Any] = {}
            if did:
                params["domainId"] = did
            if type_uuids:
                params["typeId"] = type_uuids

            for a in self._client.get_paginated("/rest/2.0/assets", params):
                rows.append(
                    {
                        "asset_id": a["id"],
                        "asset_name": a.get("displayName") or a["name"],
                        "domain_id": a["domain"]["id"],
                        "asset_type_id": a["type"]["id"],
                        "asset_type_name": a["type"]["name"],
                        "status": a["status"]["name"] if a.get("status") else None,
                    }
                )

        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(
                columns=[
                    "asset_id",
                    "asset_name",
                    "domain_id",
                    "asset_type_id",
                    "asset_type_name",
                    "status",
                ]
            )
        )
        df = df.drop_duplicates(subset="asset_id")
        self._cache["asset_info"] = df
        print(f"  Extracted {len(df)} assets")
        return df

    def extract_attribute_info(self) -> pd.DataFrame:
        """Fetch attributes for all known assets in batches of ≤100."""
        asset_ids = list(self._cache.get("asset_info", pd.DataFrame()).get("asset_id", []))
        if not asset_ids:
            df = pd.DataFrame(columns=["attribute_id", "asset_id", "attribute_type", "value"])
            self._cache["attribute_info"] = df
            return df

        rows: list[dict[str, Any]] = []
        n_batches = math.ceil(len(asset_ids) / _ATTRIBUTE_BATCH_SIZE)
        for i in range(n_batches):
            batch = asset_ids[i * _ATTRIBUTE_BATCH_SIZE : (i + 1) * _ATTRIBUTE_BATCH_SIZE]
            # Collibra supports repeated query params with the assetId[] key.
            # We call _get directly (not get_paginated) because 100 assets have
            # far fewer than 1000 attributes — one request per batch is sufficient.
            params: dict[str, Any] = {"limit": 1000, "offset": 0, "assetId[]": batch}
            result = self._client._get("/rest/2.0/attributes", params)

            for attr in result.get("results", []):
                rows.append(
                    {
                        "attribute_id": attr["id"],
                        "asset_id": attr["asset"]["id"],
                        "attribute_type": attr["type"]["name"],
                        "value": attr.get("value"),
                    }
                )

        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(columns=["attribute_id", "asset_id", "attribute_type", "value"])
        )
        self._cache["attribute_info"] = df
        print(f"  Extracted {len(df)} attributes")
        return df

    def extract_relation_info(self) -> pd.DataFrame:
        """Fetch all relations between known assets and return as DataFrame."""
        asset_ids = set(self._cache.get("asset_info", pd.DataFrame()).get("asset_id", []))
        rows: list[dict[str, Any]] = []

        # Fetch relations by source and by target to get full picture
        for raw in self._client.get_paginated("/rest/2.0/relations", {}):
            src_id = raw["source"]["id"]
            tgt_id = raw["target"]["id"]
            if src_id in asset_ids or tgt_id in asset_ids:
                rows.append(
                    {
                        "relation_id": raw["id"],
                        "source_id": src_id,
                        "source_name": raw["source"]["name"],
                        "target_id": tgt_id,
                        "target_name": raw["target"]["name"],
                        "relation_type_id": raw["type"]["id"],
                        "relation_type_name": raw["type"]["name"],
                    }
                )

        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(
                columns=[
                    "relation_id",
                    "source_id",
                    "source_name",
                    "target_id",
                    "target_name",
                    "relation_type_id",
                    "relation_type_name",
                ]
            )
        )
        self._cache["relation_info"] = df
        print(f"  Extracted {len(df)} relations")
        return df

    def extract_lineage_info(self) -> pd.DataFrame:
        """Fetch outbound technical lineage for Table/Column assets."""
        rows: list[dict[str, Any]] = []

        if not self._include_lineage:
            df = pd.DataFrame(columns=["source_id", "target_id", "lineage_type"])
            self._cache["lineage_info"] = df
            return df

        # Only fetch lineage for assets mapped to Table or Column
        asset_df = self._cache.get("asset_info", pd.DataFrame())
        if asset_df.empty:
            df = pd.DataFrame(columns=["source_id", "target_id", "lineage_type"])
            self._cache["lineage_info"] = df
            return df

        table_col_types = {"table", "column", "data set", "dataset", "field", "view"}
        lineage_asset_ids = [
            row["asset_id"]
            for _, row in asset_df.iterrows()
            if row["asset_type_name"].lower() in table_col_types
            or ASSET_TYPE_ALIASES.get(row["asset_type_name"].lower()) in ("Table", "Column")
        ]

        for aid in lineage_asset_ids:
            try:
                result = self._client._get(f"/rest/catalog/1.0/asset/{aid}/outboundLineage")
                for node in result.get("lineageNodes", []):
                    rows.append(
                        {
                            "source_id": aid,
                            "target_id": node["id"],
                            "lineage_type": node.get("type"),
                        }
                    )
            except Exception:
                pass

        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(columns=["source_id", "target_id", "lineage_type"])
        )
        self._cache["lineage_info"] = df
        print(f"  Extracted {len(df)} lineage pairs")
        return df

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> None:
        """Run all extraction steps and populate the cache."""
        print("Extracting Collibra metadata...")
        self.extract_community_info()
        self.extract_domain_info()
        self.extract_asset_info()
        self.extract_attribute_info()
        self.extract_relation_info()
        self.extract_lineage_info()
