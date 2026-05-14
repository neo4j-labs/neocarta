"""Unit tests for CollibraClient: pagination, auth, retry, type discovery."""

import pytest

from neocarta.connectors.collibra.client import CollibraClient

from .fixtures import (
    ASSET_TYPES_RESPONSE,
    COMMUNITIES_PAGE_1,
    COMMUNITIES_PAGE_2,
    COMMUNITIES_RESPONSE,
    DOMAIN_TYPES_RESPONSE,
    RELATION_TYPES_RESPONSE,
    paged_url,
)

BASE_URL = "https://test.collibra.com"


def test_token_auth_sets_header(httpx_mock):
    """Bearer token should appear in Authorization header."""
    # _get doesn't add pagination params; register exact URL
    httpx_mock.add_response(
        url=f"{BASE_URL}/rest/2.0/communities",
        method="GET",
        json=COMMUNITIES_RESPONSE,
    )
    client = CollibraClient(base_url=BASE_URL, token="my-jwt")  # noqa: S106
    result = client._get("/rest/2.0/communities")
    assert result["total"] == 2
    sent_req = httpx_mock.get_requests()[0]
    assert sent_req.headers.get("authorization") == "Bearer my-jwt"


def test_basic_auth_calls_session_endpoint(httpx_mock):
    """Basic auth must POST to /rest/2.0/auth/sessions."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/rest/2.0/auth/sessions",
        method="POST",
        json={"token": "session-token"},
        status_code=200,
        headers={"Set-Cookie": "JSESSIONID=abc; Path=/; HttpOnly"},
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/rest/2.0/communities",
        method="GET",
        json=COMMUNITIES_RESPONSE,
    )
    client = CollibraClient(base_url=BASE_URL, username="user", password="pass")  # noqa: S106
    result = client._get("/rest/2.0/communities")
    assert result["total"] == 2

    # First request must be the auth POST
    requests = httpx_mock.get_requests()
    assert requests[0].url.path == "/rest/2.0/auth/sessions"
    assert requests[0].method == "POST"


def test_get_paginated_iterates_all_pages(httpx_mock):
    """get_paginated should follow offset until offset >= total."""
    # pytest-httpx matches exact URL including query params
    httpx_mock.add_response(
        url=paged_url("/rest/2.0/communities", limit=1, offset=0),
        method="GET",
        json=COMMUNITIES_PAGE_1,
    )
    httpx_mock.add_response(
        url=paged_url("/rest/2.0/communities", limit=1, offset=1),
        method="GET",
        json=COMMUNITIES_PAGE_2,
    )

    client = CollibraClient(base_url=BASE_URL, token="tok", page_size=1)  # noqa: S106
    results = client.get_paginated("/rest/2.0/communities")

    assert len(results) == 2
    assert results[0]["id"] == "comm-finance"
    assert results[1]["id"] == "comm-marketing"
    assert len(httpx_mock.get_requests()) == 2


def test_get_paginated_single_page(httpx_mock):
    """get_paginated should stop after one request when all results fit in one page."""
    httpx_mock.add_response(
        url=paged_url("/rest/2.0/communities"),
        method="GET",
        json=COMMUNITIES_RESPONSE,
    )
    client = CollibraClient(base_url=BASE_URL, token="tok", page_size=100)  # noqa: S106
    results = client.get_paginated("/rest/2.0/communities")

    assert len(results) == 2
    assert len(httpx_mock.get_requests()) == 1


def test_retry_on_429(httpx_mock, monkeypatch):
    """Client should retry after 429 with exponential back-off (sleep mocked)."""
    slept: list[float] = []

    def _fake_sleep(s: float) -> None:
        slept.append(s)

    monkeypatch.setattr("neocarta.connectors.collibra.client.time.sleep", _fake_sleep)

    # _get is called directly (no pagination params), so use plain URL
    httpx_mock.add_response(
        url=f"{BASE_URL}/rest/2.0/communities",
        method="GET",
        status_code=429,
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/rest/2.0/communities",
        method="GET",
        json=COMMUNITIES_RESPONSE,
    )

    client = CollibraClient(base_url=BASE_URL, token="tok")  # noqa: S106
    result = client._get("/rest/2.0/communities")

    assert result["total"] == 2
    assert len(slept) == 1  # one retry sleep
    assert slept[0] >= 1.0  # base delay


def test_discover_types_returns_uuid_maps(httpx_mock):
    """discover_types should return three UUID→name dicts."""
    httpx_mock.add_response(url=paged_url("/rest/2.0/assetTypes"), json=ASSET_TYPES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/domainTypes"), json=DOMAIN_TYPES_RESPONSE)
    httpx_mock.add_response(url=paged_url("/rest/2.0/relationTypes"), json=RELATION_TYPES_RESPONSE)

    client = CollibraClient(base_url=BASE_URL, token="tok")  # noqa: S106
    asset_types, domain_types, relation_types = client.discover_types()

    assert asset_types["at-table"] == "Table"
    assert asset_types["at-business-term"] == "Business Term"
    assert domain_types["dt-physical"] == "Physical Data Dictionary"
    assert domain_types["dt-glossary"] == "Business Glossary"
    assert relation_types["rt-contains-col"] == "Table contains Column"


def test_missing_credentials_raises():
    """Should raise ValueError when neither token nor username/password given."""
    with pytest.raises(ValueError, match="token"):
        CollibraClient(base_url=BASE_URL)
