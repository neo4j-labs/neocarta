"""Unit tests for CollibraExtractor."""

from neocarta.connectors.collibra.client import CollibraClient
from neocarta.connectors.collibra.extract import CollibraExtractor

from .fixtures import (
    ASSET_TYPES_RESPONSE,
    ASSETS_RESPONSE,
    ATTRIBUTE_URL,
    ATTRIBUTES_RESPONSE,
    COMMUNITIES_RESPONSE,
    DOMAIN_TYPES_RESPONSE,
    DOMAINS_RESPONSE,
    RELATION_TYPES_RESPONSE,
    RELATIONS_RESPONSE,
    make_filtered_url,
    paged_url,
)

BASE_URL = "https://test.collibra.com"


def _register_type_discovery(httpx_mock):
    httpx_mock.add_response(url=paged_url("/rest/2.0/assetTypes"), json=ASSET_TYPES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domainTypes"), json=DOMAIN_TYPES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/relationTypes"), json=RELATION_TYPES_RESPONSE)


def _make_extractor(httpx_mock, **kwargs) -> CollibraExtractor:
    _register_type_discovery(httpx_mock)
    client = CollibraClient(base_url=BASE_URL, token="tok")  # noqa: S106
    return CollibraExtractor(client=client, **kwargs)


def test_extract_community_info(httpx_mock):
    """Should extract 2 communities into a DataFrame."""
    extractor = _make_extractor(httpx_mock)
    httpx_mock.add_response(url=paged_url("/rest/2.0/communities"), json=COMMUNITIES_RESPONSE)
    df = extractor.extract_community_info()
    assert len(df) == 2
    assert "community_id" in df.columns
    assert set(df["community_id"]) == {"comm-finance", "comm-marketing"}


def test_extract_domain_info(httpx_mock):
    """Should extract 2 domains: one Schema, one Glossary."""
    extractor = _make_extractor(httpx_mock)
    httpx_mock.add_response(url=paged_url("/rest/2.0/communities"), json=COMMUNITIES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domains"), json=DOMAINS_RESPONSE)
    extractor.extract_community_info()
    df = extractor.extract_domain_info()
    assert len(df) == 2
    assert set(df["domain_id"]) == {"dom-schema-1", "dom-glossary-1"}


def test_extract_asset_info(httpx_mock):
    """Should extract 6 assets of various types."""
    extractor = _make_extractor(httpx_mock)
    httpx_mock.add_response(url=paged_url("/rest/2.0/communities"), json=COMMUNITIES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domains"), json=DOMAINS_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/assets"), json=ASSETS_RESPONSE)
    extractor.extract_community_info()
    extractor.extract_domain_info()
    df = extractor.extract_asset_info()
    assert len(df) == 6
    type_names = set(df["asset_type_name"])
    assert "Table" in type_names
    assert "Column" in type_names
    assert "Business Term" in type_names
    assert "Custom Report Layout" in type_names  # the unknown type


def test_attribute_batching_call_count(httpx_mock):
    """Attribute fetch should use ≤ ceil(N/100) HTTP calls (batch size 100)."""
    extractor = _make_extractor(httpx_mock)
    httpx_mock.add_response(url=paged_url("/rest/2.0/communities"), json=COMMUNITIES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domains"), json=DOMAINS_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/assets"), json=ASSETS_RESPONSE)
    httpx_mock.add_response(url=ATTRIBUTE_URL, json=ATTRIBUTES_RESPONSE)
    extractor.extract_community_info()
    extractor.extract_domain_info()
    extractor.extract_asset_info()

    pre_count = len(httpx_mock.get_requests())
    extractor.extract_attribute_info()
    post_count = len(httpx_mock.get_requests())

    n_assets = 6  # from ASSETS_RESPONSE
    import math

    expected_calls = math.ceil(n_assets / 100)  # = 1 for 6 assets
    assert (post_count - pre_count) == expected_calls


def test_include_lineage_false_skips_lineage_calls(httpx_mock):
    """When include_lineage=False no lineage API calls should be made."""
    extractor = _make_extractor(httpx_mock, include_lineage=False)
    httpx_mock.add_response(url=paged_url("/rest/2.0/communities"), json=COMMUNITIES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domains"), json=DOMAINS_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/assets"), json=ASSETS_RESPONSE)
    httpx_mock.add_response(url=ATTRIBUTE_URL, json=ATTRIBUTES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/relations"), json=RELATIONS_RESPONSE)
    extractor.extract_all()

    lineage_calls = [r for r in httpx_mock.get_requests() if "catalog/1.0" in str(r.url)]
    assert len(lineage_calls) == 0
    assert extractor.lineage_info.empty


def test_extract_all_populates_all_caches(httpx_mock):
    """extract_all() should populate all six DataFrame properties."""
    extractor = _make_extractor(httpx_mock, include_lineage=False)
    httpx_mock.add_response(url=paged_url("/rest/2.0/communities"), json=COMMUNITIES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domains"), json=DOMAINS_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/assets"), json=ASSETS_RESPONSE)
    httpx_mock.add_response(url=ATTRIBUTE_URL, json=ATTRIBUTES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/relations"), json=RELATIONS_RESPONSE)
    extractor.extract_all()

    assert not extractor.community_info.empty
    assert not extractor.domain_info.empty
    assert not extractor.asset_info.empty
    assert not extractor.attribute_info.empty
    assert not extractor.relation_info.empty


def test_scoped_extraction_by_community(httpx_mock):
    """community_ids filter should restrict extracted communities."""
    extractor = _make_extractor(httpx_mock, community_ids=["comm-finance"])
    # Scoped request includes communityId in the URL
    httpx_mock.add_response(
        url=make_filtered_url("/rest/2.0/communities", {"communityId": ["comm-finance"]}),
        json={
            "total": 1,
            "offset": 0,
            "limit": 100,
            "results": [{"id": "comm-finance", "name": "Finance", "description": None}],
        },
    )
    df = extractor.extract_community_info()
    assert len(df) == 1
    assert df.iloc[0]["community_id"] == "comm-finance"
