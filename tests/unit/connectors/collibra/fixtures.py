"""Synthetic Collibra API response fixtures for unit tests."""

# --- Type discovery responses ---

ASSET_TYPES_RESPONSE = {
    "total": 8,
    "offset": 0,
    "limit": 100,
    "results": [
        {"id": "at-table", "name": "Table"},
        {"id": "at-column", "name": "Column"},
        {"id": "at-business-term", "name": "Business Term"},
        {"id": "at-data-domain", "name": "Data Domain"},
        {"id": "at-sub-domain", "name": "Sub Domain"},
        {"id": "at-report", "name": "Report"},
        {"id": "at-field", "name": "Field"},
        {"id": "at-unknown", "name": "Custom Report Layout"},  # maps to CatalogAsset
    ],
}

DOMAIN_TYPES_RESPONSE = {
    "total": 2,
    "offset": 0,
    "limit": 100,
    "results": [
        {"id": "dt-physical", "name": "Physical Data Dictionary"},
        {"id": "dt-glossary", "name": "Business Glossary"},
    ],
}

RELATION_TYPES_RESPONSE = {
    "total": 4,
    "offset": 0,
    "limit": 100,
    "results": [
        {"id": "rt-contains-col", "name": "Table contains Column"},
        {
            "id": "rt-tagged-with",
            "name": "Data Attribute / Data Element / Business Term association",
        },
        {"id": "rt-domain-subdomain", "name": "Domain / Sub Domain"},
        {"id": "rt-cat-term", "name": "Category / Business Term"},
    ],
}

# --- Community responses ---

COMMUNITIES_RESPONSE = {
    "total": 2,
    "offset": 0,
    "limit": 100,
    "results": [
        {
            "id": "comm-finance",
            "name": "Finance",
            "description": "Finance division data",
        },
        {
            "id": "comm-marketing",
            "name": "Marketing",
            "description": "Marketing division data",
        },
    ],
}

COMMUNITIES_PAGE_1 = {
    "total": 2,
    "offset": 0,
    "limit": 1,
    "results": [{"id": "comm-finance", "name": "Finance", "description": "Finance division data"}],
}

COMMUNITIES_PAGE_2 = {
    "total": 2,
    "offset": 1,
    "limit": 1,
    "results": [{"id": "comm-marketing", "name": "Marketing", "description": None}],
}

# --- Domain responses ---

DOMAINS_RESPONSE = {
    "total": 2,
    "offset": 0,
    "limit": 100,
    "results": [
        {
            "id": "dom-schema-1",
            "name": "Finance Schema",
            "description": "Physical data dictionary",
            "community": {"id": "comm-finance", "name": "Finance"},
            "type": {"id": "dt-physical", "name": "Physical Data Dictionary"},
        },
        {
            "id": "dom-glossary-1",
            "name": "Finance Glossary",
            "description": "Business glossary",
            "community": {"id": "comm-finance", "name": "Finance"},
            "type": {"id": "dt-glossary", "name": "Business Glossary"},
        },
    ],
}

# --- Asset responses ---

ASSETS_RESPONSE = {
    "total": 6,
    "offset": 0,
    "limit": 100,
    "results": [
        {
            "id": "asset-table-1",
            "name": "orders",
            "displayName": "Orders",
            "domain": {"id": "dom-schema-1", "name": "Finance Schema"},
            "type": {"id": "at-table", "name": "Table"},
            "status": {"id": "s-accepted", "name": "Accepted"},
        },
        {
            "id": "asset-col-1",
            "name": "order_id",
            "displayName": "Order ID",
            "domain": {"id": "dom-schema-1", "name": "Finance Schema"},
            "type": {"id": "at-column", "name": "Column"},
            "status": {"id": "s-accepted", "name": "Accepted"},
        },
        {
            "id": "asset-bt-1",
            "name": "Revenue",
            "displayName": "Revenue",
            "domain": {"id": "dom-glossary-1", "name": "Finance Glossary"},
            "type": {"id": "at-business-term", "name": "Business Term"},
            "status": {"id": "s-draft", "name": "Draft"},
        },
        {
            "id": "asset-dd-1",
            "name": "Financial Data",
            "displayName": "Financial Data",
            "domain": {"id": "dom-glossary-1", "name": "Finance Glossary"},
            "type": {"id": "at-data-domain", "name": "Data Domain"},
            "status": None,
        },
        {
            "id": "asset-report-1",
            "name": "Monthly Revenue Report",
            "displayName": "Monthly Revenue Report",
            "domain": {"id": "dom-schema-1", "name": "Finance Schema"},
            "type": {"id": "at-report", "name": "Report"},
            "status": None,
        },
        {
            "id": "asset-unknown-1",
            "name": "Custom Layout A",
            "displayName": "Custom Layout A",
            "domain": {"id": "dom-schema-1", "name": "Finance Schema"},
            "type": {"id": "at-unknown", "name": "Custom Report Layout"},
            "status": None,
        },
    ],
}

# --- Attribute responses (batch) ---

ATTRIBUTES_RESPONSE = {
    "total": 3,
    "offset": 0,
    "limit": 1000,
    "results": [
        {
            "id": "attr-1",
            "asset": {"id": "asset-table-1", "name": "orders"},
            "type": {"id": "atype-desc", "name": "Description"},
            "value": "All customer orders",
        },
        {
            "id": "attr-2",
            "asset": {"id": "asset-bt-1", "name": "Revenue"},
            "type": {"id": "atype-def", "name": "Definition"},
            "value": "Total income from sales",
        },
        {
            "id": "attr-3",
            "asset": {"id": "asset-col-1", "name": "order_id"},
            "type": {"id": "atype-desc", "name": "Description"},
            "value": "Primary key of the orders table",
        },
    ],
}

# --- Relation responses ---

RELATIONS_RESPONSE = {
    "total": 2,
    "offset": 0,
    "limit": 100,
    "results": [
        {
            "id": "rel-1",
            "source": {"id": "asset-table-1", "name": "orders"},
            "target": {"id": "asset-col-1", "name": "order_id"},
            "type": {"id": "rt-contains-col", "name": "Table contains Column"},
        },
        {
            "id": "rel-2",
            "source": {"id": "asset-col-1", "name": "order_id"},
            "target": {"id": "asset-bt-1", "name": "Revenue"},
            "type": {
                "id": "rt-tagged-with",
                "name": "Data Attribute / Data Element / Business Term association",
            },
        },
    ],
}

# --- Lineage responses ---

LINEAGE_RESPONSE_TABLE = {
    "lineageNodes": [
        {"id": "asset-report-1", "name": "Monthly Revenue Report", "type": "TABLE"},
    ]
}

LINEAGE_RESPONSE_EMPTY = {"lineageNodes": []}


_BASE = "https://test.collibra.com"
_DEFAULT_PAGE_SIZE = 100


def paged_url(path: str, offset: int = 0, limit: int = _DEFAULT_PAGE_SIZE) -> str:
    """Build a URL with pagination query params (as pytest-httpx matches exact URLs)."""
    return f"{_BASE}{path}?limit={limit}&offset={offset}"


def paged_url_with_params(
    path: str, extra: str, offset: int = 0, limit: int = _DEFAULT_PAGE_SIZE
) -> str:
    """Build a URL with pagination + extra query params."""
    return f"{_BASE}{path}?{extra}&limit={limit}&offset={offset}"


def make_filtered_url(
    path: str,
    extra_params: dict,
    offset: int = 0,
    limit: int = _DEFAULT_PAGE_SIZE,
) -> str:
    """Build the exact URL httpx produces for a filtered paginated request.

    Extra params are placed before ``limit``/``offset`` to match httpx insertion order.
    """
    import httpx as _httpx

    req = _httpx.Request(
        "GET",
        f"{_BASE}{path}",
        params={**extra_params, "limit": limit, "offset": offset},
    )
    return str(req.url)


def make_attribute_url(asset_ids: list[str]) -> str:
    """Pre-compute the exact attribute request URL that httpx will generate.

    httpx encodes list params as repeated keys, e.g. ``assetId%5B%5D=a&assetId%5B%5D=b``.
    pytest-httpx matches exact URLs, so callers must use this helper when registering
    the attribute mock response.
    """
    import httpx as _httpx

    req = _httpx.Request(
        "GET",
        f"{_BASE}/rest/2.0/attributes",
        params={"limit": 1000, "offset": 0, "assetId[]": asset_ids},
    )
    return str(req.url)


# Pre-computed for the ASSETS_RESPONSE fixture (6 assets).
ATTRIBUTE_URL = make_attribute_url([r["id"] for r in ASSETS_RESPONSE["results"]])


class CollibraAPIBuilder:
    """
    Helper for composing pytest-httpx mock handlers in unit tests.

    pytest-httpx performs exact URL matching including query parameters, so all
    paginated endpoints must be registered with ``?limit=N&offset=M`` included.

    Usage::

        builder = CollibraAPIBuilder(httpx_mock)
        builder.register_type_discovery()
        builder.register_communities()
        ...
    """

    def __init__(self, httpx_mock: object) -> None:
        """Store the pytest-httpx mock object."""
        self.mock = httpx_mock
        self._base = _BASE

    def add(self, url: str, response: dict, method: str = "GET") -> None:
        """Register a single mocked response at the given full URL."""
        self.mock.add_response(  # type: ignore[attr-defined]
            url=url,
            method=method,
            json=response,
            status_code=200,
        )

    def register_auth(self) -> None:
        """Register mock basic auth session endpoint."""
        self.mock.add_response(  # type: ignore[attr-defined]
            url=f"{self._base}/rest/2.0/auth/sessions",
            method="POST",
            json={"token": "mock-session-token"},
            status_code=200,
            headers={"Set-Cookie": "JSESSIONID=mock-session; Path=/; HttpOnly"},
        )

    def register_type_discovery(self) -> None:
        """Register all three type discovery endpoints (with pagination params)."""
        self.add(paged_url("/rest/2.0/assetTypes"), ASSET_TYPES_RESPONSE)
        self.add(paged_url("/rest/2.0/domainTypes"), DOMAIN_TYPES_RESPONSE)
        self.add(paged_url("/rest/2.0/relationTypes"), RELATION_TYPES_RESPONSE)

    def register_communities(self) -> None:
        """Register communities endpoint."""
        self.add(paged_url("/rest/2.0/communities"), COMMUNITIES_RESPONSE)

    def register_domains(self) -> None:
        """Register domains endpoint."""
        self.add(paged_url("/rest/2.0/domains"), DOMAINS_RESPONSE)

    def register_assets(self) -> None:
        """Register assets endpoint."""
        self.add(paged_url("/rest/2.0/assets"), ASSETS_RESPONSE)

    def register_attributes(self) -> None:
        """Register attributes endpoint."""
        self.add(ATTRIBUTE_URL, ATTRIBUTES_RESPONSE)

    def register_relations(self) -> None:
        """Register relations endpoint."""
        self.add(paged_url("/rest/2.0/relations"), RELATIONS_RESPONSE)

    def register_lineage(
        self, asset_id: str = "asset-table-1", response: dict | None = None
    ) -> None:
        """Register outbound lineage endpoint for a specific asset."""
        self.add(
            f"{self._base}/rest/catalog/1.0/asset/{asset_id}/outboundLineage",
            response or LINEAGE_RESPONSE_EMPTY,
        )

    def register_all(self) -> None:
        """Register all standard endpoints for a complete extraction run."""
        self.register_auth()
        self.register_type_discovery()
        self.register_communities()
        self.register_domains()
        self.register_assets()
        self.register_attributes()
        self.register_relations()
        for asset_id in ["asset-table-1", "asset-col-1", "asset-report-1"]:
            self.register_lineage(asset_id, LINEAGE_RESPONSE_EMPTY)
        self.register_lineage("asset-table-1", LINEAGE_RESPONSE_TABLE)
