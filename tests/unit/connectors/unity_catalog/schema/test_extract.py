"""Unit tests for UnityCatalogSchemaExtractor (HTTP mocked via recorded fixtures)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from neocarta.connectors.unity_catalog.schema.extract import UnityCatalogSchemaExtractor
from neocarta.connectors.utils import NodeLabel, RelationshipType
from neocarta.errors import ConfigError, ConnectorError, ExtractionError, OperationTimeoutError

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "http://localhost:8080/api/2.1/unity-catalog"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _ok_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _extractor_with_get(get_side_effect):
    """Build an extractor whose HTTP client .get uses the given side effect."""
    client = MagicMock()
    client.get.side_effect = get_side_effect
    extractor = UnityCatalogSchemaExtractor(base_url=BASE_URL)
    extractor._client = client
    return extractor


# --------------------------------------------------------------------------- #
# extraction + flattening
# --------------------------------------------------------------------------- #
def test_extract_full_caches_all_levels(extractor_with_cache):
    """A full extract caches one catalog, two schemas, two tables, three columns."""
    assert len(extractor_with_cache.catalog_info) == 1
    assert len(extractor_with_cache.schema_info) == 2
    assert len(extractor_with_cache.table_info) == 2
    # orders has 2 columns, customers_view has 1; the empty `ops` schema adds none.
    assert len(extractor_with_cache.column_info) == 3


def test_extract_maps_comment_and_type(extractor_with_cache):
    """comment -> None and type_text is used for the column type."""
    columns = {row["column_name"]: row for row in extractor_with_cache.column_info}
    assert columns["amount"]["column_type"] == "decimal(10,2)"
    assert columns["amount"]["comment"] is None
    assert columns["amount"]["nullable"] is True
    assert columns["order_id"]["nullable"] is False

    schemas = {row["schema_name"]: row for row in extractor_with_cache.schema_info}
    assert schemas["ops"]["comment"] is None
    assert schemas["sales"]["comment"] == "Sales data"


def test_view_folds_into_table(extractor_with_cache):
    """A view (table_type MATERIALIZED_VIEW) is captured as an ordinary table row."""
    tables = {row["table_name"]: row for row in extractor_with_cache.table_info}
    assert tables["customers_view"]["table_type"] == "MATERIALIZED_VIEW"
    assert tables["customers_view"]["comment"] is None


def test_schemas_filter_restricts_to_requested(extractor):
    """The schemas argument keeps only the requested schema names."""
    extractor.extract("main", schemas=["sales"])
    assert [row["schema_name"] for row in extractor.schema_info] == ["sales"]


# --------------------------------------------------------------------------- #
# pagination
# --------------------------------------------------------------------------- #
def test_pagination_follows_next_page_token():
    """extract_table_info accumulates rows across pages until the token is empty."""
    pages = [_load("tables_page1.json"), _load("tables_page2.json")]

    def _get(path, params=None):
        return _ok_response(pages.pop(0))

    extractor = _extractor_with_get(_get)
    rows = extractor.extract_table_info("main", ["sales"])

    assert {row["table_name"] for row in rows} == {"orders", "shipments"}
    assert extractor._client.get.call_count == 2


def test_pagination_stops_on_repeated_token():
    """A server that echoes the same token does not loop forever."""

    def _get(path, params=None):
        return _ok_response({"tables": [], "next_page_token": "STUCK"})

    extractor = _extractor_with_get(_get)
    rows = extractor.extract_table_info("main", ["sales"])

    assert rows == []
    assert extractor._client.get.call_count == 2  # first page, then the repeat guard stops it


# --------------------------------------------------------------------------- #
# filtering / transient extraction
# --------------------------------------------------------------------------- #
def test_column_only_filter_caches_columns_but_not_tables(mock_client):
    """include_nodes=[COLUMN] still fetches tables transiently to attach columns."""
    extractor = UnityCatalogSchemaExtractor(base_url=BASE_URL)
    extractor._client = mock_client

    extractor.extract(
        "main",
        include_nodes=[NodeLabel.COLUMN],
        include_relationships=[RelationshipType.HAS_COLUMN],
    )

    assert extractor.table_info == []  # not cached
    assert extractor.catalog_info == []
    assert extractor.schema_info == []
    assert len(extractor.column_info) == 3  # columns still produced
    # the /tables endpoint was still hit (columns are embedded there)
    assert any(call.args and call.args[0] == "/tables" for call in mock_client.get.call_args_list)


def test_database_only_filter_skips_schema_calls(mock_client):
    """include_nodes=[DATABASE] caches only the catalog and never lists schemas."""
    extractor = UnityCatalogSchemaExtractor(base_url=BASE_URL)
    extractor._client = mock_client

    extractor.extract("main", include_nodes=[NodeLabel.DATABASE])

    assert len(extractor.catalog_info) == 1
    assert extractor.schema_info == []
    assert extractor.table_info == []
    assert not any(
        call.args and call.args[0] == "/schemas" for call in mock_client.get.call_args_list
    )


def test_unknown_node_label_raises_config_error(extractor):
    """An unsupported node label is rejected before any network call."""
    with pytest.raises(ConfigError):
        extractor.extract("main", include_nodes=[NodeLabel.VALUE])


# --------------------------------------------------------------------------- #
# error mapping
# --------------------------------------------------------------------------- #
def test_http_status_error_maps_to_extraction_error():
    """A non-2xx response (via raise_for_status) becomes ExtractionError."""
    request = httpx.Request("GET", f"{BASE_URL}/catalogs/main")
    response = httpx.Response(404, request=request)

    def _get(path, params=None):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "not found", request=request, response=response
        )
        return resp

    extractor = _extractor_with_get(_get)
    with pytest.raises(ExtractionError):
        extractor.extract_catalog_info("main")


def test_connect_error_maps_to_connector_error():
    """A transport/connect failure becomes ConnectorError."""

    def _get(path, params=None):
        raise httpx.ConnectError("boom")

    extractor = _extractor_with_get(_get)
    with pytest.raises(ConnectorError):
        extractor.extract_catalog_info("main")


def test_timeout_maps_to_operation_timeout_error():
    """A request timeout becomes OperationTimeoutError."""

    def _get(path, params=None):
        raise httpx.TimeoutException("slow")

    extractor = _extractor_with_get(_get)
    with pytest.raises(OperationTimeoutError):
        extractor.extract_catalog_info("main")


# --------------------------------------------------------------------------- #
# malformed payload guards
# --------------------------------------------------------------------------- #
def test_missing_table_name_raises_extraction_error():
    """A table payload without a 'name' field fails loud rather than emitting an empty id."""

    def _get(path, params=None):
        return _ok_response(
            {
                "tables": [{"catalog_name": "main", "schema_name": "sales", "columns": []}],
                "next_page_token": "",
            }
        )

    extractor = _extractor_with_get(_get)
    with pytest.raises(ExtractionError):
        extractor.extract_table_info("main", ["sales"])


def test_missing_column_name_raises_extraction_error():
    """A column payload without a 'name' field fails loud during flattening."""

    def _get(path, params=None):
        return _ok_response(
            {
                "tables": [
                    {
                        "name": "orders",
                        "catalog_name": "main",
                        "schema_name": "sales",
                        "columns": [{"type_text": "int", "nullable": True}],
                    }
                ],
                "next_page_token": "",
            }
        )

    extractor = _extractor_with_get(_get)
    extractor.extract_table_info("main", ["sales"])  # stashes the raw table payloads
    with pytest.raises(ExtractionError):
        extractor.extract_column_info()
