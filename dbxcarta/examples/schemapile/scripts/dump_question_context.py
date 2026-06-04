r"""Dump the three context blocks used for SchemaPile question generation.

Produces a Markdown document with three fenced sections: the schema dump,
the foreign-key list, and the sample-value list.

Run from the example directory so the .env overlay is picked up:

    uv run --directory examples/schemapile python scripts/dump_question_context.py \\
        > ../../docs/schemapile/questions-schema.md

Configuration comes from the existing ClientSettings overlay
(catalog, schemas, Neo4j credentials). Tune the confidence floor and
the per-column value cap with --confidence and --max-values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load the standalone .env. DBXCARTA_SCHEMAS is blank for schemapile (the
# data-only catalog is auto-discovered), and the Cypher below treats an empty
# schema list as "all schemas", so the dump covers the whole graph.
_EXAMPLE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_EXAMPLE_DIR / ".env")

from dbxcarta.client.neo4j_utils import neo4j_credentials  # noqa: E402
from dbxcarta.client.schema_dump import fetch_schema_dump  # noqa: E402
from dbxcarta.client.settings import ClientSettings  # noqa: E402

_FK_CYPHER = """
MATCH (db:Database {name: $catalog})-[:HAS_SCHEMA]->(s1:Schema)
      -[:HAS_TABLE]->(t1:Table)-[:HAS_COLUMN]->(c1:Column)
      -[r:REFERENCES]->(c2:Column)
      <-[:HAS_COLUMN]-(t2:Table)<-[:HAS_TABLE]-(s2:Schema)
WHERE COALESCE(r.confidence, 1.0) >= $threshold
  AND (size($schemas) = 0
       OR (s1.name IN $schemas AND s2.name IN $schemas))
RETURN s1.name AS s1, t1.name AS t1, c1.name AS c1,
       s2.name AS s2, t2.name AS t2, c2.name AS c2,
       COALESCE(r.confidence, 1.0) AS confidence,
       COALESCE(r.source, 'declared') AS source
ORDER BY s1, t1, c1, s2, t2, c2
"""

_VALUES_CYPHER = """
MATCH (db:Database {name: $catalog})-[:HAS_SCHEMA]->(s:Schema)
      -[:HAS_TABLE]->(t:Table)-[:HAS_COLUMN]->(c:Column)-[:HAS_VALUE]->(v:Value)
WHERE size($schemas) = 0 OR s.name IN $schemas
WITH s.name AS schema_name, t.name AS table_name, c.name AS col_name,
     collect(DISTINCT v.value) AS vals
RETURN schema_name, table_name, col_name, vals
ORDER BY schema_name, table_name, col_name
"""


def _format_fk_list(rows: list[dict]) -> str:
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for row in rows:
        left = f"{row['s1']}.{row['t1']}.{row['c1']}"
        right = f"{row['s2']}.{row['t2']}.{row['c2']}"
        first, second = sorted((left, right))
        key = (first, second)
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"{left} -> {right}  # source={row['source']}, confidence={row['confidence']:.2f}"
        )
    return "\n".join(lines) if lines else "(no FK edges met the confidence floor)"


def _format_values(rows: list[dict], max_values: int, max_chars: int) -> str:
    lines: list[str] = []
    for row in rows:
        clipped: list[str] = []
        for val in row["vals"][:max_values]:
            text = "NULL" if val is None else str(val)
            if len(text) > max_chars:
                text = text[: max_chars - 3] + "..."
            clipped.append(text)
        if not clipped:
            continue
        joined = ", ".join(clipped)
        lines.append(f"{row['schema_name']}.{row['table_name']}.{row['col_name']}: {joined}")
    return "\n".join(lines) if lines else "(no sample values present)"


def _emit_doc(
    schema_text: str,
    fk_text: str,
    values_text: str,
    catalog: str,
    schema_count: int,
    threshold: float,
) -> str:
    return f"""# Question-Generation Context (schemapile_lakehouse)

Generated from the live Neo4j graph for catalog `{catalog}` across
{schema_count} schemas. The three sections below are intended for
SchemaPile question-generation prompt iteration:

- The **Schema dump** section replaces `<<<PASTE THE OUTPUT OF fetch_schema_dump HERE>>>`.
- The **Foreign-key list** section replaces the `<<<PASTE THE FK LIST HERE ...>>>` block.
- The **Sample values** section replaces the `<<<PASTE THE SAMPLE-VALUE LIST HERE ...>>>` block.

This file is reproducible; regenerate with:

```
uv run --directory examples/schemapile python scripts/dump_question_context.py \\
    > docs/schemapile/questions-schema.md
```

FK confidence floor used for this dump: `>= {threshold:.2f}`.

---

## Schema dump

```
{schema_text}
```

---

## Foreign-key list

Format: `schema.table.column -> schema.table.column  # source=..., confidence=...`.
Trailing comments are informational; strip them before pasting into the
question-generation prompt if you prefer the simpler form.

```
{fk_text}
```

---

## Sample values

Format: `schema.table.column: value1, value2, value3, ...`.

```
{values_text}
```
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.8,
        help="Minimum REFERENCES confidence to include (default: 0.8)",
    )
    parser.add_argument(
        "--max-values",
        type=int,
        default=20,
        help="Max sample values per column (default: 20)",
    )
    parser.add_argument(
        "--max-value-chars",
        type=int,
        default=80,
        help="Max characters per sample value before truncation (default: 80)",
    )
    args = parser.parse_args(argv)

    settings = _load_settings()
    schemas = settings.schemas_list

    schema_text = fetch_schema_dump(settings)

    uri, username, password = neo4j_credentials(settings)
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session() as session:
            fk_rows = session.run(
                _FK_CYPHER,
                catalog=settings.dbxcarta_catalog,
                schemas=schemas,
                threshold=args.confidence,
            ).data()
            value_rows = session.run(
                _VALUES_CYPHER,
                catalog=settings.dbxcarta_catalog,
                schemas=schemas,
            ).data()
    finally:
        driver.close()

    fk_text = _format_fk_list(fk_rows)
    values_text = _format_values(value_rows, args.max_values, args.max_value_chars)

    sys.stdout.write(
        _emit_doc(
            schema_text=schema_text,
            fk_text=fk_text,
            values_text=values_text,
            catalog=settings.dbxcarta_catalog,
            schema_count=len(schemas),
            threshold=args.confidence,
        )
    )
    return 0


def _load_settings() -> ClientSettings:
    return ClientSettings()  # type: ignore[call-arg]


if __name__ == "__main__":
    raise SystemExit(main())
