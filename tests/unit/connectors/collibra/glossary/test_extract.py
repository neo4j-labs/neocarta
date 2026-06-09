"""Unit tests for CollibraGlossaryExtractor: domains, assets, categories, tags."""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.collibra.glossary.extract import CollibraGlossaryExtractor
from neocarta.enums import NodeLabel, RelationshipType
from neocarta.warnings import UnmappedCollibraAssetTypeWarning


def test_extract_populates_glossary_category_term_caches(fake_client):
    """A full extract caches the glossary domain, categories, and business terms."""
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract()
    assert list(extractor.glossary_info["domain_id"]) == ["dom-gloss"]
    assert set(extractor.category_info["asset_id"]) == {"a-cat"}
    assert set(extractor.business_term_info["asset_id"]) == {"a-bt-order", "a-bt-cust"}


def test_only_glossary_domains_are_kept(fake_client):
    """The physical domain is excluded from the glossary extractor's domains."""
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract()
    assert "dom-wh" not in set(extractor.glossary_info["domain_id"])


def test_term_parent_category_is_resolved(fake_client):
    """Each term records its parent category UUID from category→term relations."""
    import pandas as pd

    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract()
    parents = extractor.business_term_info.set_index("asset_id")["category_collibra_id"].to_dict()
    assert parents["a-bt-order"] == "a-cat"
    assert pd.isna(parents["a-bt-cust"])  # uncategorised


def test_tagged_with_pairs_source_asset_and_term(fake_client):
    """Tag relations are captured as (source asset UUID, term UUID) pairs."""
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract()
    rows = extractor.tagged_with_info.to_dict("records")
    assert rows == [{"source_collibra_id": "a-orderid", "term_collibra_id": "a-bt-order"}]


def test_term_category_resolved_even_when_has_business_term_excluded(fake_client):
    """Category resolution feeds the term id, so it runs regardless of edge filtering."""
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract(include_relationships=[RelationshipType.TAGGED_WITH])
    parents = extractor.business_term_info.set_index("asset_id")["category_collibra_id"].to_dict()
    assert parents["a-bt-order"] == "a-cat"


def test_include_relationships_excluding_tagged_with_skips_tag_fetch(fake_client):
    """Excluding TAGGED_WITH avoids fetching tag relations."""
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract(include_relationships=[RelationshipType.HAS_BUSINESS_TERM])
    assert extractor.tagged_with_info.empty


def test_include_nodes_terms_only(fake_client):
    """include_nodes=[BUSINESS_TERM] caches terms but not categories."""
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract(include_nodes=[NodeLabel.BUSINESS_TERM])
    assert not extractor.business_term_info.empty
    assert extractor.category_info.empty


def test_unmapped_warning_not_raised_for_clean_glossary(fake_client, recwarn):
    """The sample glossary domain has only mapped types, so no unmapped warning fires."""
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract()
    assert not [w for w in recwarn if issubclass(w.category, UnmappedCollibraAssetTypeWarning)]


def test_unmapped_warning_for_out_of_scope_asset():
    """An unmapped asset type in a glossary domain raises the warning."""
    client = MagicMock()
    client.discover_types.return_value = (
        {"at-policy": "Policy"},
        {"dt-gloss": "Business Glossary"},
        {},
    )
    domain = {
        "id": "dom-gloss",
        "name": "Sales Glossary",
        "description": None,
        "community": {"id": "comm-sales"},
        "type": {"id": "dt-gloss", "name": "Business Glossary"},
    }
    policy_asset = {
        "id": "a-policy",
        "name": "Retention Policy",
        "displayName": "Retention Policy",
        "domain": {"id": "dom-gloss"},
        "type": {"id": "at-policy", "name": "Policy"},
        "status": None,
    }

    def get_paginated(path, params=None):
        params = params or {}
        if path == "/rest/2.0/domains":
            return [domain]
        if path == "/rest/2.0/assets":
            return [policy_asset] if params.get("domainId") == "dom-gloss" else []
        return []

    client.get_paginated.side_effect = get_paginated
    extractor = CollibraGlossaryExtractor(client)
    with pytest.warns(UnmappedCollibraAssetTypeWarning, match="Policy"):
        extractor.extract()
