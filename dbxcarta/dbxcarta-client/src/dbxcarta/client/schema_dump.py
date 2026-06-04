"""Neo4j schema dump: read all columns across the configured catalogs/schemas."""

from __future__ import annotations

try:
    from neo4j import GraphDatabase
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
    raise ModuleNotFoundError(
        "dbxcarta-client schema dump requires Neo4j. Install the client "
        "package with the 'graph' extra: pip install 'dbxcarta-client[graph]'"
    ) from exc

from typing import TYPE_CHECKING

from dbxcarta.client.neo4j_utils import neo4j_credentials

if TYPE_CHECKING:
    from dbxcarta.client.settings import ClientSettings

_CYPHER = """
MATCH (db:Database)-[:HAS_SCHEMA]->(s:Schema)
      -[:HAS_TABLE]->(t:Table)-[:HAS_COLUMN]->(c:Column)
WHERE db.name IN $catalogs
  AND (size($schemas) = 0 OR s.name IN $schemas)
RETURN db.name AS catalog_name,
       s.name AS schema_name,
       t.name  AS table_name,
       c.name  AS column_name,
       c.type AS data_type,
       c.description AS comment,
       c.ordinal_position AS pos
ORDER BY db.name, s.name, t.name, c.ordinal_position
"""


def fetch_schema_dump(settings: ClientSettings) -> str:
    """Query Neo4j and return a formatted schema string for the prompt."""
    uri, username, password = neo4j_credentials(settings)
    driver = GraphDatabase.driver(uri, auth=(username, password))

    catalogs = settings.resolved_catalogs
    rows: list[dict] = []
    try:
        with driver.session() as session:
            result = session.run(
                _CYPHER,
                catalogs=catalogs,
                schemas=settings.schemas_list,
            )
            rows = result.data()
    finally:
        driver.close()

    if not rows:
        raise RuntimeError(
            "Neo4j returned no columns for "
            f"catalogs={catalogs!r} schemas={settings.schemas_list!r}. "
            "Run the server pipeline first to populate the graph."
        )

    text = _format_schema(rows)
    max_chars = settings.dbxcarta_schema_dump_max_chars
    if max_chars > 0 and len(text) > max_chars:
        cut = text.rfind("\n", 0, max_chars)
        text = text[:cut] + f"\n[schema truncated at {max_chars} chars; {len(text)} total]"
    return text


def _format_schema(rows: list[dict]) -> str:
    """Render column rows as a structured schema block for prompt insertion.

    Each table is qualified by its own ``catalog_name`` so a multi-catalog
    dump (bronze/silver/gold) yields correct three-part names.
    """
    lines: list[str] = []
    current_table: str | None = None

    for row in rows:
        fqt = f"{row['catalog_name']}.{row['schema_name']}.{row['table_name']}"
        if fqt != current_table:
            if current_table is not None:
                lines.append("")
            lines.append(f"Table: {fqt}")
            current_table = fqt

        comment = row.get("comment") or ""
        suffix = f" — {comment}" if comment else ""
        lines.append(f"  {row['column_name']} ({row['data_type']}){suffix}")

    return "\n".join(lines)
