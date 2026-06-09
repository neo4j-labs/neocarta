"""Collibra HTTP client: authentication, pagination, type discovery, and retry."""

import time
from typing import Any, Self

import httpx

from ...errors import AuthError

_DEFAULT_PAGE_SIZE = 100
_MAX_RETRIES = 4
_RETRY_BASE_SECONDS = 1.0


class CollibraClient:
    """
    HTTP client for the Collibra Core REST API v2.

    Wraps ``httpx.Client`` with:

    * Basic-auth session establishment (cookie jar reuse across all calls)
    * Bearer-token auth
    * Transparent offset/limit pagination via ``get_paginated``
    * Exponential back-off on HTTP 429 responses
    * Type discovery (``discover_types``) for UUID → display-name resolution

    Parameters
    ----------
    base_url : str
        Root URL of the Collibra instance, e.g. ``https://myorg.collibra.com``.
    username : str | None
        Collibra username for basic auth.
    password : str | None
        Collibra password for basic auth.
    token : str | None
        JWT Bearer token (alternative to username/password).
    page_size : int
        Number of results per page for paginated requests.
    timeout : float
        HTTP request timeout in seconds.

    Raises:
    ------
    AuthError
        If neither (username + password) nor token is provided.
    """

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        timeout: float = 30.0,
    ) -> None:
        """Initialise the client and authenticate."""
        if not token and not (username and password):
            raise AuthError(
                "Collibra authentication requires either (username, password) or token.",
                suggestion="Pass username + password, or a JWT/OAuth bearer token, to CollibraClient.",
            )

        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._client = httpx.Client(timeout=timeout)

        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"
        else:
            self._authenticate(username, password)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _authenticate(self, username: str, password: str) -> None:
        """POST credentials to /rest/2.0/auth/sessions; store returned cookie."""
        url = f"{self._base_url}/rest/2.0/auth/sessions"
        resp = self._client.post(url, json={"username": username, "password": password})
        resp.raise_for_status()
        # httpx.Client stores Set-Cookie headers in its cookie jar automatically.

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request with exponential back-off on 429."""
        url = f"{self._base_url}{path}"
        delay = _RETRY_BASE_SECONDS
        for attempt in range(_MAX_RETRIES + 1):
            resp = self._client.get(url, params=params)
            if resp.status_code == 429 and attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}  # unreachable — raise_for_status will fire

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def get_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        """
        Fetch all pages from a paginated Collibra list endpoint.

        Iterates with ``offset``/``limit`` until ``offset >= total``.

        Parameters
        ----------
        path : str
            API path, e.g. ``/rest/2.0/communities``.
        params : dict[str, Any] | None
            Additional query parameters (merged with offset/limit).

        Returns:
        -------
        list[dict]
            All results across all pages.
        """
        params = dict(params or {})
        params["limit"] = self._page_size
        params["offset"] = 0
        results: list[dict] = []

        while True:
            page = self._get(path, params)
            results.extend(page.get("results", []))
            total = page.get("total", 0)
            params["offset"] += self._page_size
            if params["offset"] >= total:
                break

        return results

    # ------------------------------------------------------------------
    # Type discovery
    # ------------------------------------------------------------------

    def discover_types(
        self,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """
        Fetch and return UUID-to-name mappings for asset, domain, and relation types.

        Calls ``GET /rest/2.0/assetTypes``, ``GET /rest/2.0/domainTypes``, and
        ``GET /rest/2.0/relationTypes`` at startup so that all subsequent type
        resolution can use stable UUIDs rather than display names.

        Returns:
        -------
        asset_types : dict[str, str]
            UUID → display name for all asset types.
        domain_types : dict[str, str]
            UUID → display name for all domain types.
        relation_types : dict[str, str]
            UUID → display name for all relation types.
        """
        asset_types = {t["id"]: t["name"] for t in self.get_paginated("/rest/2.0/assetTypes")}
        domain_types = {t["id"]: t["name"] for t in self.get_paginated("/rest/2.0/domainTypes")}
        relation_types = {t["id"]: t["name"] for t in self.get_paginated("/rest/2.0/relationTypes")}
        return asset_types, domain_types, relation_types

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Self:
        """Support use as a context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Close client on context manager exit."""
        self.close()
