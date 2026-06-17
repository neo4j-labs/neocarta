"""Fixtures for the Unity Catalog schema connector unit tests.

The HTTP layer is mocked: the extractor's owned ``httpx.Client`` is replaced with
a ``MagicMock`` whose ``.get`` dispatches per path/params to recorded JSON
fixtures (no sockets, no new test dependency).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neocarta.connectors.unity_catalog.schema.extract import UnityCatalogSchemaExtractor
from neocarta.connectors.unity_catalog.schema.transform import UnityCatalogSchemaTransformer

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "http://localhost:8080/api/2.1/unity-catalog"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _response(payload):
    """Build a mock httpx.Response that returns ``payload`` from .json()."""
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def catalog_payload():
    return _load("catalogs_get.json")


@pytest.fixture
def schemas_payload():
    return _load("schemas_list.json")


@pytest.fixture
def tables_payload():
    return _load("tables_list.json")


@pytest.fixture
def mock_client(catalog_payload, schemas_payload, tables_payload):
    """A mock httpx client dispatching the recorded fixtures by path/params.

    ``/tables`` returns the sales tables for ``schema_name=sales`` and an empty
    page for any other schema (e.g. ``ops``), so the full extract exercises both
    a populated and an empty schema.
    """
    tables_by_schema = {"sales": tables_payload}

    def _get(path, params=None):
        params = params or {}
        if path.startswith("/catalogs/"):
            return _response(catalog_payload)
        if path == "/schemas":
            return _response(schemas_payload)
        if path == "/tables":
            schema_name = params.get("schema_name")
            return _response(
                tables_by_schema.get(schema_name, {"tables": [], "next_page_token": ""})
            )
        msg = f"unexpected request path: {path}"
        raise AssertionError(msg)

    client = MagicMock()
    client.get.side_effect = _get
    return client


@pytest.fixture
def extractor(mock_client):
    """A UnityCatalogSchemaExtractor with its HTTP client swapped for the mock."""
    extractor = UnityCatalogSchemaExtractor(base_url=BASE_URL)
    extractor._client = mock_client
    return extractor


@pytest.fixture
def extractor_with_cache(extractor):
    """An extractor whose cache is populated by a full ``extract('main')`` run."""
    extractor.extract("main")
    return extractor


@pytest.fixture
def transformer():
    return UnityCatalogSchemaTransformer()
