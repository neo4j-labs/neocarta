"""Collibra glossary extractor: glossary domains, categories, business terms, tags."""

import warnings
from collections import Counter
from typing import Any

import pandas as pd

from ....enums import NodeLabel, RelationshipType
from ....warnings import UnmappedCollibraAssetTypeWarning
from ..client import CollibraClient
from ..resolve import CollibraTypeResolver

_DESCRIPTION_ATTRIBUTE_TYPES = ("description", "definition", "note")


class CollibraGlossaryExtractor:
    """Extract Collibra business-glossary metadata into neocarta-shaped DataFrames.

    Pulls business-glossary domains (→ Glossary), the Data Category / Business
    Term assets within them, the category→term relations, and the asset→term
    "tagged with" relations. Cached state is exposed through read-only
    ``@property`` accessors consumed by :class:`CollibraGlossaryTransformer`.

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
    def glossary_info(self) -> pd.DataFrame:
        """Business-glossary domains (→ Glossary nodes)."""
        return self._cache.get("glossary_info", pd.DataFrame())

    @property
    def category_info(self) -> pd.DataFrame:
        """Data Category assets (→ Category nodes)."""
        return self._cache.get("category_info", pd.DataFrame())

    @property
    def business_term_info(self) -> pd.DataFrame:
        """Business Term assets (→ BusinessTerm nodes), with resolved parent category."""
        return self._cache.get("business_term_info", pd.DataFrame())

    @property
    def tagged_with_info(self) -> pd.DataFrame:
        """Asset→Business Term tag relations (source asset UUID, term UUID)."""
        return self._cache.get("tagged_with_info", pd.DataFrame())

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
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """Run all extraction steps and populate the cache.

        Parameters
        ----------
        community_ids, domain_ids : list[str], optional
            Restrict extraction to these Collibra community/domain UUIDs.
        asset_type_names : list[str], optional
            Restrict assets to these Collibra asset-type display names.
        include_nodes : list[NodeLabel], optional
            Subset of {GLOSSARY, CATEGORY, BUSINESS_TERM} to cache. ``None`` = all.
        include_relationships : list[RelationshipType], optional
            Subset of {HAS_CATEGORY, HAS_BUSINESS_TERM, TAGGED_WITH}. ``None`` = all.
        """
        self._cache.clear()
        resolver = CollibraTypeResolver(*self._client.discover_types())

        print("Extracting Collibra glossary metadata...")
        domains = self._extract_glossary_domains(resolver, community_ids, domain_ids)
        term_ids = self._extract_assets(resolver, domains, asset_type_names, include_nodes)
        # Term→category is always resolved: it feeds the term id (glossary.category.term),
        # so it must not depend on whether the HAS_BUSINESS_TERM edge is requested.
        self._extract_term_categories(resolver, term_ids)
        self._extract_tagged_with(resolver, term_ids, include_relationships)

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #

    def _extract_glossary_domains(
        self,
        resolver: CollibraTypeResolver,
        community_ids: list[str] | None,
        domain_ids: list[str] | None,
    ) -> pd.DataFrame:
        """Fetch domains whose domain type maps to ``Glossary`` and cache them."""
        rows: list[dict[str, Any]] = []
        for d in self._client.get_paginated("/rest/2.0/domains", {}):
            if domain_ids and d["id"] not in domain_ids:
                continue
            if community_ids and d["community"]["id"] not in community_ids:
                continue
            if resolver.neocarta_domain_type(d["type"]["name"]) != "Glossary":
                continue
            rows.append(
                {
                    "domain_id": d["id"],
                    "domain_name": d["name"],
                    "description": d.get("description"),
                }
            )
        df = pd.DataFrame(
            rows, columns=["domain_id", "domain_name", "description"]
        ).drop_duplicates(subset="domain_id")
        self._cache["glossary_info"] = df
        print(f"  Extracted {len(df)} glossary domains")
        return df

    def _extract_assets(
        self,
        resolver: CollibraTypeResolver,
        domains: pd.DataFrame,
        asset_type_names: list[str] | None,
        include_nodes: list[NodeLabel] | None,
    ) -> set[str]:
        """Fetch Category/BusinessTerm assets; return the set of term UUIDs."""
        domain_ids = list(domains["domain_id"]) if not domains.empty else []
        type_uuids = resolver.asset_type_ids_for_names(asset_type_names) if asset_type_names else []

        categories: list[dict[str, Any]] = []
        terms: list[dict[str, Any]] = []
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
                if neo_type == "Category":
                    categories.append(row)
                elif neo_type == "BusinessTerm":
                    terms.append(row)
                else:
                    unmapped[a["type"]["name"]] += 1

        descriptions = self._fetch_descriptions(
            [r["asset_id"] for r in categories] + [r["asset_id"] for r in terms]
        )
        for r in (*categories, *terms):
            r["description"] = descriptions.get(r["asset_id"])

        self._warn_unmapped(unmapped)
        cols = ["asset_id", "asset_name", "domain_id", "asset_type_name", "status", "description"]
        if include_nodes is None or NodeLabel.CATEGORY in include_nodes:
            self._cache["category_info"] = pd.DataFrame(categories, columns=cols)
            print(f"  Extracted {len(categories)} categories")
        if include_nodes is None or NodeLabel.BUSINESS_TERM in include_nodes:
            self._cache["business_term_info"] = pd.DataFrame(
                terms, columns=[*cols, "category_collibra_id"]
            )
            print(f"  Extracted {len(terms)} business terms")
        return {r["asset_id"] for r in terms}

    def _extract_term_categories(
        self,
        resolver: CollibraTypeResolver,
        term_ids: set[str],
    ) -> None:
        """Resolve each term's parent category UUID from category→term relations."""
        bt = self.business_term_info
        if bt.empty or not term_ids:
            return
        parent = self._relation_targets_to_sources(resolver, term_ids, {"HAS_BUSINESS_TERM"})
        self._cache["business_term_info"] = bt.assign(
            category_collibra_id=bt["asset_id"].map(parent)
        )

    def _extract_tagged_with(
        self,
        resolver: CollibraTypeResolver,
        term_ids: set[str],
        include_relationships: list[RelationshipType] | None,
    ) -> None:
        """Fetch asset→term tag relations and cache (source asset UUID, term UUID)."""
        if (
            include_relationships is not None
            and RelationshipType.TAGGED_WITH not in include_relationships
        ):
            return
        rows: list[dict[str, str]] = []
        for tid in resolver.relation_type_ids_for_neocarta({"TAGGED_WITH"}):
            for rel in self._client.get_paginated("/rest/2.0/relations", {"relationTypeId": tid}):
                source, target = rel["source"]["id"], rel["target"]["id"]
                # The term may be either endpoint depending on the relation's direction.
                if target in term_ids:
                    rows.append({"source_collibra_id": source, "term_collibra_id": target})
                elif source in term_ids:
                    rows.append({"source_collibra_id": target, "term_collibra_id": source})
        df = pd.DataFrame(rows, columns=["source_collibra_id", "term_collibra_id"])
        self._cache["tagged_with_info"] = df
        print(f"  Extracted {len(df)} tag relations")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _relation_targets_to_sources(
        self,
        resolver: CollibraTypeResolver,
        target_ids: set[str],
        neocarta_relationships: set[str],
    ) -> dict[str, str]:
        """Map relation target UUID → source UUID for the given neocarta relationship types."""
        out: dict[str, str] = {}
        for tid in resolver.relation_type_ids_for_neocarta(neocarta_relationships):
            for rel in self._client.get_paginated("/rest/2.0/relations", {"relationTypeId": tid}):
                if rel["target"]["id"] in target_ids:
                    out[rel["target"]["id"]] = rel["source"]["id"]
        return out

    def _fetch_descriptions(self, asset_ids: list[str]) -> dict[str, str]:
        """Fetch description-like attribute values, one ``assetId`` request per asset."""
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

    def _warn_unmapped(self, unmapped: Counter[str]) -> None:
        """Emit a single aggregated warning for skipped, out-of-scope asset types."""
        if not unmapped:
            return
        summary = ", ".join(f"{name} ({count})" for name, count in sorted(unmapped.items()))
        warnings.warn(
            f"Skipped {sum(unmapped.values())} Collibra assets outside the glossary "
            f"sub-connector's scope (Data Category/Business Term): {summary}.",
            UnmappedCollibraAssetTypeWarning,
            stacklevel=2,
        )
