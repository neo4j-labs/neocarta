"""Unit tests for CollibraClient: auth handling and offset/limit pagination."""

from typing import Any

import pytest

from neocarta.connectors.collibra import CollibraClient
from neocarta.errors import AuthError

BASE_URL = "https://test.collibra.com"
TOKEN = "jwt-123"  # noqa: S105  (dummy bearer token for tests)


def test_missing_credentials_raises_auth_error():
    """Constructing without token or username/password raises AuthError."""
    with pytest.raises(AuthError):
        CollibraClient(base_url=BASE_URL)


def test_token_sets_bearer_header_without_network():
    """A bearer token is applied to the session headers (no auth round-trip)."""
    client = CollibraClient(base_url=BASE_URL, token=TOKEN)
    assert client._client.headers["Authorization"] == "Bearer jwt-123"


def test_get_paginated_iterates_until_total(monkeypatch):
    """get_paginated walks offset/limit pages until offset >= total."""
    client = CollibraClient(base_url=BASE_URL, token=TOKEN, page_size=2)
    pages = {
        0: {"results": [{"id": "1"}, {"id": "2"}], "total": 3},
        2: {"results": [{"id": "3"}], "total": 3},
    }

    def fake_get(_path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return pages[params["offset"]]

    monkeypatch.setattr(client, "_get", fake_get)
    results = client.get_paginated("/rest/2.0/communities", {})
    assert [r["id"] for r in results] == ["1", "2", "3"]
