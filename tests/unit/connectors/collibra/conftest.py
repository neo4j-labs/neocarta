"""Shared fixtures for Collibra connector unit tests.

Provides a fake :class:`CollibraClient` (a ``MagicMock`` wired with
``discover_types`` + ``get_paginated``) backed by one small, coherent Collibra
instance: a Sales community with a physical Warehouse domain (Table + Columns)
and a Sales Glossary domain (Data Category + Business Terms), plus a tag relation
from a column to a business term so cross-sub-connector behaviour is exercisable.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

# Asset / domain / relation type UUID → display name maps (as discover_types returns).
ASSET_TYPES = {
    "at-table": "Table",
    "at-col": "Column",
    "at-bt": "Business Term",
    "at-cat": "Data Category",
    "at-dq": "Data Quality Rule",  # intentionally unmapped
}
DOMAIN_TYPES = {"dt-phys": "Physical Data Dictionary", "dt-gloss": "Business Glossary"}
RELATION_TYPES = {
    "rt-contains": "Table contains Column",
    "rt-cat-term": "Category / Business Term",
    "rt-tag": "Asset associated with Business Term",
}

COMMUNITIES = [{"id": "comm-sales", "name": "Sales", "description": "Sales community"}]

DOMAINS = [
    {
        "id": "dom-wh",
        "name": "Warehouse",
        "description": "Physical warehouse",
        "community": {"id": "comm-sales"},
        "type": {"id": "dt-phys", "name": "Physical Data Dictionary"},
    },
    {
        "id": "dom-gloss",
        "name": "Sales Glossary",
        "description": "Business terms",
        "community": {"id": "comm-sales"},
        "type": {"id": "dt-gloss", "name": "Business Glossary"},
    },
]


def _asset(aid: str, name: str, domain: str, type_id: str, type_name: str) -> dict[str, Any]:
    return {
        "id": aid,
        "name": name,
        "displayName": name,
        "domain": {"id": domain},
        "type": {"id": type_id, "name": type_name},
        "status": {"id": "st-acc", "name": "Accepted"},
    }


ASSETS_BY_DOMAIN = {
    "dom-wh": [
        _asset("a-orders", "orders", "dom-wh", "at-table", "Table"),
        _asset("a-orderid", "order_id", "dom-wh", "at-col", "Column"),
        _asset("a-custid", "customer_id", "dom-wh", "at-col", "Column"),
        _asset("a-dq", "Orders Freshness", "dom-wh", "at-dq", "Data Quality Rule"),
    ],
    "dom-gloss": [
        _asset("a-cat", "Orders", "dom-gloss", "at-cat", "Data Category"),
        _asset("a-bt-order", "Order", "dom-gloss", "at-bt", "Business Term"),
        _asset("a-bt-cust", "Customer", "dom-gloss", "at-bt", "Business Term"),
    ],
}

RELATIONS_BY_TYPE = {
    "rt-contains": [
        {
            "id": "r1",
            "source": {"id": "a-orders"},
            "target": {"id": "a-orderid"},
            "type": {"id": "rt-contains"},
        },
        {
            "id": "r2",
            "source": {"id": "a-orders"},
            "target": {"id": "a-custid"},
            "type": {"id": "rt-contains"},
        },
    ],
    "rt-cat-term": [
        {
            "id": "r3",
            "source": {"id": "a-cat"},
            "target": {"id": "a-bt-order"},
            "type": {"id": "rt-cat-term"},
        },
    ],
    "rt-tag": [
        {
            "id": "r4",
            "source": {"id": "a-orderid"},
            "target": {"id": "a-bt-order"},
            "type": {"id": "rt-tag"},
        },
    ],
}

ATTRIBUTES_BY_ASSET = {
    "a-orders": [
        {
            "id": "at1",
            "asset": {"id": "a-orders"},
            "type": {"name": "Description"},
            "value": "All sales orders",
        },
    ],
    "a-orderid": [
        {
            "id": "at2",
            "asset": {"id": "a-orderid"},
            "type": {"name": "Definition"},
            "value": "Order identifier",
        },
    ],
    "a-bt-order": [
        {
            "id": "at3",
            "asset": {"id": "a-bt-order"},
            "type": {"name": "Description"},
            "value": "A customer order",
        },
    ],
}


def make_fake_client() -> MagicMock:
    """Build a MagicMock CollibraClient backed by the sample instance."""
    client = MagicMock()
    client.discover_types.return_value = (ASSET_TYPES, DOMAIN_TYPES, RELATION_TYPES)

    def get_paginated(path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        params = params or {}
        if path == "/rest/2.0/communities":
            return COMMUNITIES
        if path == "/rest/2.0/domains":
            return DOMAINS
        if path == "/rest/2.0/assets":
            assets = ASSETS_BY_DOMAIN.get(params.get("domainId"), [])
            type_ids = params.get("typeId")
            if type_ids:
                assets = [a for a in assets if a["type"]["id"] in type_ids]
            return assets
        if path == "/rest/2.0/relations":
            return RELATIONS_BY_TYPE.get(params.get("relationTypeId"), [])
        if path == "/rest/2.0/attributes":
            return ATTRIBUTES_BY_ASSET.get(params.get("assetId"), [])
        return []

    client.get_paginated.side_effect = get_paginated
    return client


@pytest.fixture
def fake_client() -> MagicMock:
    """A fake CollibraClient wired with the sample instance payloads."""
    return make_fake_client()
