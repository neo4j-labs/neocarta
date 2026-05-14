"""End-to-end unit tests for CollibraConnector (all HTTP and Neo4j mocked)."""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.collibra.connector import CollibraConnector

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
    paged_url,
)

BASE_URL = "https://test.collibra.com"


def _register_type_discovery(httpx_mock):
    httpx_mock.add_response(url=paged_url("/rest/2.0/assetTypes"), json=ASSET_TYPES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domainTypes"), json=DOMAIN_TYPES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/relationTypes"), json=RELATION_TYPES_RESPONSE)


def _register_extraction(httpx_mock):
    """Register all extraction endpoints except lineage."""
    httpx_mock.add_response(url=paged_url("/rest/2.0/communities"), json=COMMUNITIES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domains"), json=DOMAINS_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/assets"), json=ASSETS_RESPONSE)
    httpx_mock.add_response(url=ATTRIBUTE_URL, json=ATTRIBUTES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/relations"), json=RELATIONS_RESPONSE)


def _make_mock_driver():
    """Create a mock Neo4j driver whose execute_query returns a minimal summary."""
    driver = MagicMock()
    mock_summary = MagicMock()
    mock_summary.counters.__dict__ = {"nodes_created": 1}
    driver.execute_query.return_value = ([], mock_summary, [])
    return driver


def test_connector_missing_credentials():
    """CollibraConnector should raise ValueError with no credentials."""
    with pytest.raises(ValueError, match="token"):
        CollibraConnector(collibra_url=BASE_URL, neo4j_driver=MagicMock())


def test_run_calls_loader_with_nodes(httpx_mock):
    """run() should call the Neo4j loader with non-empty node lists."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/rest/2.0/auth/sessions",
        method="POST",
        json={"token": "session"},
        status_code=200,
        headers={"Set-Cookie": "JSESSIONID=abc; Path=/"},
    )
    _register_type_discovery(httpx_mock)
    _register_extraction(httpx_mock)

    driver = _make_mock_driver()
    connector = CollibraConnector(
        collibra_url=BASE_URL,
        neo4j_driver=driver,
        username="user",
        password="pass",  # noqa: S106
        include_lineage=False,
    )
    connector.run()

    assert driver.execute_query.called, "Neo4j loader should have been called"
    assert driver.execute_query.call_count >= 3


def test_extract_transform_load_separate_steps(httpx_mock):
    """extract_metadata(), transform_metadata(), load_metadata() can be called separately."""
    _register_type_discovery(httpx_mock)
    _register_extraction(httpx_mock)

    driver = _make_mock_driver()
    connector = CollibraConnector(
        collibra_url=BASE_URL,
        neo4j_driver=driver,
        token="tok",  # noqa: S106
        include_lineage=False,
    )

    connector.extract_metadata()
    assert not connector.extractor.community_info.empty
    assert connector.transformer is None

    connector.transform_metadata()
    assert connector.transformer is not None
    assert len(connector.transformer.database_nodes) > 0

    connector.load_metadata()
    assert driver.execute_query.called


def test_load_before_transform_raises(httpx_mock):
    """Calling load_metadata() before transform_metadata() should raise RuntimeError."""
    _register_type_discovery(httpx_mock)
    connector = CollibraConnector(
        collibra_url=BASE_URL,
        neo4j_driver=_make_mock_driver(),
        token="tok",  # noqa: S106
    )
    with pytest.raises(RuntimeError, match="transform_metadata"):
        connector.load_metadata()
