"""Extract schema metadata from the open Unity Catalog REST API.

Talks to a Unity Catalog server (github.com/unitycatalog/unitycatalog) over the
``/api/2.1/unity-catalog`` REST API using a thin :class:`httpx.Client` owned by
this extractor — no vendor SDK. The list endpoints embed each table's columns
inline, so columns need no per-column round trip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from ...._logging import log_stage
from ....errors import ConfigError, ConnectorError, ExtractionError, OperationTimeoutError
from ...utils import NodeLabel, RelationshipType
from .models import (
    CatalogInfo,
    ColumnInfo,
    SchemaInfo,
    TableInfo,
    UnityCatalogSchemaCache,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# Per-page result cap. Catalogs/schemas allow up to 1000; tables cap at 50.
_PAGE_SIZE_DEFAULT = 1000
_PAGE_SIZE_TABLES = 50

# Map a requested node label / relationship type onto the internal "need" it
# implies. Relationships are built from the same info rows as their child node
# (HAS_SCHEMA from schema_info, HAS_TABLE from table_info, HAS_COLUMN from
# column_info), so they share those needs.
_NODE_LABEL_NEEDS: dict[NodeLabel, str] = {
    NodeLabel.DATABASE: "catalog",
    NodeLabel.SCHEMA: "schema",
    NodeLabel.TABLE: "table",
    NodeLabel.COLUMN: "column",
}
_REL_TYPE_NEEDS: dict[RelationshipType, str] = {
    RelationshipType.HAS_SCHEMA: "schema",
    RelationshipType.HAS_TABLE: "table",
    RelationshipType.HAS_COLUMN: "column",
}
_ALL_NEEDS = frozenset({"catalog", "schema", "table", "column"})


class UnityCatalogSchemaExtractor:
    """Extractor for open Unity Catalog REST API schema metadata.

    Owns a long-lived :class:`httpx.Client`. Internal cached state is *not* part
    of the public API — callers interact only through the connector's stage
    methods and read results via the :attr:`catalog_info` / :attr:`schema_info` /
    :attr:`table_info` / :attr:`column_info` properties.

    Parameters
    ----------
    base_url : str
        Base URL of the Unity Catalog REST API, including the version prefix
        (e.g. ``http://localhost:8080/api/2.1/unity-catalog``).
    token : str | None, default None
        Bearer token sent in the ``Authorization`` header. ``None`` for a local
        OSS server that requires no auth.
    timeout : float, default 30.0
        Per-request timeout in seconds.
    """

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        """Initialize the extractor and build the owned HTTP client."""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)
        self._cache: UnityCatalogSchemaCache = UnityCatalogSchemaCache(
            catalog_info=None, schema_info=None, table_info=None, column_info=None
        )
        self._raw_tables: list[dict[str, Any]] = []

    @property
    def catalog_info(self) -> list[CatalogInfo]:
        """Cached catalog rows (one per ``:Database``)."""
        return self._cache.get("catalog_info") or []

    @property
    def schema_info(self) -> list[SchemaInfo]:
        """Cached schema rows (one per ``:Schema``)."""
        return self._cache.get("schema_info") or []

    @property
    def table_info(self) -> list[TableInfo]:
        """Cached table rows (one per ``:Table``)."""
        return self._cache.get("table_info") or []

    @property
    def column_info(self) -> list[ColumnInfo]:
        """Cached column rows (one per ``:Column``)."""
        return self._cache.get("column_info") or []

    def extract(
        self,
        catalog: str,
        schemas: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """Read schema metadata for ``catalog`` into the cache.

        Replaces any previously cached state. Applies ``include_nodes`` /
        ``include_relationships`` filtering: an entity type is cached only when
        requested, but tables are fetched transiently when only columns are
        requested (columns are embedded in the tables payload), and schemas are
        fetched whenever tables or columns are requested (schema names are needed
        to list tables).

        Parameters
        ----------
        catalog : str
            The Unity Catalog catalog name to extract.
        schemas : list[str] | None, default None
            Optional client-side filter; keep only these schema names. ``None``
            extracts every schema in the catalog.
        include_nodes : list[NodeLabel] | None, default None
            Node labels to produce. ``None`` includes all four.
        include_relationships : list[RelationshipType] | None, default None
            Relationship types to produce. ``None`` includes all three.
        """
        needs = self._resolve_needs(include_nodes, include_relationships)
        self._cache = UnityCatalogSchemaCache(
            catalog_info=None, schema_info=None, table_info=None, column_info=None
        )
        self._raw_tables = []

        # Always fetch the catalog: it validates the catalog exists and is the id
        # root for every downstream node. Cache it only when DATABASE is wanted.
        catalog_rows = self.extract_catalog_info(catalog)
        if "catalog" in needs:
            self._cache["catalog_info"] = catalog_rows

        if not needs & {"schema", "table", "column"}:
            return

        schema_rows = self.extract_schema_info(catalog, schemas)
        if "schema" in needs:
            self._cache["schema_info"] = schema_rows
        schema_names = [row["schema_name"] for row in schema_rows]

        if not needs & {"table", "column"}:
            return

        # Tables are fetched whenever tables OR columns are needed, but cached
        # only when TABLE is requested (transient extraction, contract §5).
        table_rows = self.extract_table_info(catalog, schema_names)
        if "table" in needs:
            self._cache["table_info"] = table_rows
        if "column" in needs:
            self._cache["column_info"] = self.extract_column_info()

    @log_stage
    def extract_catalog_info(self, catalog: str) -> list[CatalogInfo]:
        """Fetch a single catalog via ``GET /catalogs/{name}``."""
        payload = self._get(f"/catalogs/{catalog}")
        return [
            CatalogInfo(
                catalog_name=payload.get("name") or catalog,
                comment=payload.get("comment") or None,
            )
        ]

    @log_stage
    def extract_schema_info(
        self, catalog: str, schemas: list[str] | None = None
    ) -> list[SchemaInfo]:
        """List schemas via ``GET /schemas?catalog_name=...`` (paginated)."""
        wanted = set(schemas) if schemas else None
        rows: list[SchemaInfo] = []
        for item in self._paginate("/schemas", {"catalog_name": catalog}, "schemas"):
            name = item.get("name")
            if name is None or (wanted is not None and name not in wanted):
                continue
            rows.append(
                SchemaInfo(
                    catalog_name=catalog,
                    schema_name=name,
                    comment=item.get("comment") or None,
                )
            )
        return rows

    @log_stage
    def extract_table_info(self, catalog: str, schema_names: list[str]) -> list[TableInfo]:
        """List tables for each schema via ``GET /tables?...`` (paginated).

        Each ``TableInfo`` embeds its columns inline; the raw payloads are stashed
        so :meth:`extract_column_info` can flatten columns without more requests.
        """
        rows: list[TableInfo] = []
        raw_tables: list[dict[str, Any]] = []
        for schema_name in schema_names:
            params = {"catalog_name": catalog, "schema_name": schema_name}
            for item in self._paginate("/tables", params, "tables", page_size=_PAGE_SIZE_TABLES):
                # A table without a name can't form a valid id — fail loud on a
                # malformed/non-conformant payload rather than emit an empty-id node.
                name = item.get("name")
                if not name:
                    raise ExtractionError(
                        "Unity Catalog table payload missing required 'name' field.",
                        details={"catalog": catalog, "schema": schema_name},
                    )
                # Pin catalog/schema so column flattening stays consistent even if
                # a server omits them on the embedded payload.
                item["catalog_name"] = item.get("catalog_name") or catalog
                item["schema_name"] = item.get("schema_name") or schema_name
                raw_tables.append(item)
                rows.append(
                    TableInfo(
                        catalog_name=item["catalog_name"],
                        schema_name=item["schema_name"],
                        table_name=name,
                        table_type=item.get("table_type") or None,
                        comment=item.get("comment") or None,
                    )
                )
        self._raw_tables = raw_tables
        return rows

    @log_stage
    def extract_column_info(self) -> list[ColumnInfo]:
        """Flatten the columns embedded in the table payloads from the last fetch."""
        rows: list[ColumnInfo] = []
        for table in self._raw_tables:
            # table["name"] was validated non-empty in extract_table_info.
            table_name = table["name"]
            for column in table.get("columns") or []:
                column_name = column.get("name")
                if not column_name:
                    raise ExtractionError(
                        "Unity Catalog column payload missing required 'name' field.",
                        details={"table": table_name},
                    )
                rows.append(
                    ColumnInfo(
                        catalog_name=table["catalog_name"],
                        schema_name=table["schema_name"],
                        table_name=table_name,
                        column_name=column_name,
                        # type_text carries the full SQL type (e.g. decimal(10,2));
                        # fall back to the coarse type_name, then None.
                        column_type=column.get("type_text") or column.get("type_name") or None,
                        nullable=bool(column.get("nullable", True)),
                        comment=column.get("comment") or None,
                    )
                )
        return rows

    def close(self) -> None:
        """Close the owned HTTP client and its connection pool."""
        self._client.close()

    def _resolve_needs(
        self,
        include_nodes: list[NodeLabel] | None,
        include_relationships: list[RelationshipType] | None,
    ) -> set[str]:
        """Translate the include filters into the set of internal needs to extract."""
        if include_nodes is None and include_relationships is None:
            return set(_ALL_NEEDS)
        needs: set[str] = set()
        for label in include_nodes or []:
            try:
                needs.add(_NODE_LABEL_NEEDS[NodeLabel(label)])
            except (ValueError, KeyError) as exc:
                valid = ", ".join(member.value for member in _NODE_LABEL_NEEDS)
                raise ConfigError(
                    f"Unsupported node label for the Unity Catalog connector: {label!r}.",
                    suggestion=f"Use one of: {valid}.",
                ) from exc
        for rel in include_relationships or []:
            try:
                needs.add(_REL_TYPE_NEEDS[RelationshipType(rel)])
            except (ValueError, KeyError) as exc:
                valid = ", ".join(member.value for member in _REL_TYPE_NEEDS)
                raise ConfigError(
                    f"Unsupported relationship type for the Unity Catalog connector: {rel!r}.",
                    suggestion=f"Use one of: {valid}.",
                ) from exc
        return needs

    def _paginate(
        self,
        path: str,
        params: dict[str, Any],
        item_key: str,
        page_size: int = _PAGE_SIZE_DEFAULT,
    ) -> Iterator[dict[str, Any]]:
        """Yield every item across pages, following ``next_page_token``.

        Stops on a falsy token (``""``, ``null``, or missing) and guards against a
        server that echoes a repeated token (which would otherwise loop forever).
        """
        query = dict(params)
        query["max_results"] = page_size
        seen_tokens: set[str] = set()
        while True:
            payload = self._get(path, query)
            yield from payload.get(item_key) or []
            token = payload.get("next_page_token")
            if not token or token in seen_tokens:
                break
            seen_tokens.add(token)
            query["page_token"] = token

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Issue a GET and return the parsed JSON, mapping failures to typed errors.

        Never logs the token, query params, or response body — only the status
        code, path, and exception type reach error details (contract §16).
        """
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OperationTimeoutError(
                f"Unity Catalog request timed out after {self.timeout}s.",
                suggestion="Increase `timeout`, or narrow extraction with schemas=[...].",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ExtractionError(
                "Unity Catalog request returned an error status.",
                details={"status_code": exc.response.status_code, "path": path},
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(
                "Could not reach the Unity Catalog server.",
                details={"path": path, "error_type": type(exc).__name__},
            ) from exc
        try:
            return response.json()
        except ValueError as exc:
            raise ExtractionError(
                "Unity Catalog returned a non-JSON response.",
                details={"path": path},
            ) from exc
