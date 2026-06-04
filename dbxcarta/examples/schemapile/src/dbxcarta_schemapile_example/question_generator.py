"""LLM question generation + SQL validation.

For each candidate schema produced by the candidate selector, this module:

  1. Prompts a Databricks foundation-model endpoint with the schema DDL and
     asks for N (question, sql) pairs covering single-table filters,
     two-table joins, and aggregations.
  2. Executes each candidate SQL against the materialized Delta tables.
  3. Keeps only pairs that run cleanly, return at least one row, and do not
     return a single trivial scalar.

The accepted pairs are written to `questions.json` in the dbxcarta
evaluation format. The list is `useful for relative comparison across
dbxcarta arms, not a hand-curated gold benchmark` — see the README.

Generated outputs are cached per (uc_schema, seed) under
`.cache/questions/<uc_schema>.json` so re-runs do not re-bill the model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dbxcarta.core.env import read_required_warehouse_id
from dbxcarta.core.materialize import sanitize_identifier
from dbxcarta.core.questions import GeneratedPair, ValidationOutcome
from dbxcarta.core.sql_safety import sql_targets_only_catalog
from dbxcarta.core.workspace import build_workspace_client

from dbxcarta_schemapile_example.config import SchemaPileConfig, load_config
from dbxcarta_schemapile_example.utils import load_dotenv_file

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


logger = logging.getLogger(__name__)


_SHAPES = ("single_table_filter", "two_table_join", "aggregation")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dbxcarta-schemapile-generate-questions",
        description=(
            "Generate and validate evaluation questions for the materialized"
            " schemapile slice. Writes questions.json next to the candidate JSON."
        ),
    )
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".env",
        help="Path to the .env file to load (default: example directory .env)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("questions.json"),
        help="Where to write the validated questions.json (default: questions.json)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/questions"),
        help="Directory for per-schema LLM output caches (default: .cache/questions)",
    )
    parser.add_argument(
        "--warehouse-id",
        type=str,
        default=None,
        help="Override DATABRICKS_WAREHOUSE_ID for SQL validation.",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Generate but skip the SQL execution step. Useful for offline iteration.",
    )
    parser.add_argument(
        "--exclude-shapes",
        nargs="+",
        metavar="SHAPE",
        default=[],
        help=("Shapes to drop after generation. E.g. --exclude-shapes single_table_filter"),
    )
    args = parser.parse_args()

    load_dotenv_file(args.dotenv)
    config = load_config()

    if not config.candidate_cache.is_file():
        raise FileNotFoundError(
            f"Candidate JSON not found at {config.candidate_cache}."
            " Run dbxcarta-schemapile-select first."
        )

    warehouse_id = ""
    if not args.skip_validate:
        warehouse_id = read_required_warehouse_id(
            args.warehouse_id,
            operation="SQL validation",
            extra_hint="or use --skip-validate",
        )

    payload = json.loads(config.candidate_cache.read_text())
    schemas = payload.get("schemas") or []
    if not schemas:
        print("[schemapile] no candidate schemas found", file=sys.stderr)
        return 1

    ws = build_workspace_client()
    pairs = _generate_all(ws, config, schemas, args.cache_dir)

    # Shape filter: applied before validation to avoid executing unwanted questions.
    exclude = set(args.exclude_shapes)
    if exclude:
        pairs = [p for p in pairs if p.shape not in exclude]

    if args.skip_validate:
        outcome = ValidationOutcome(accepted=pairs)
    else:
        outcome = _validate_all(ws, warehouse_id, config.catalog, pairs)

    # Deduplicate by exact SQL, preserving order.
    seen_sql: set[str] = set()
    unique: list[GeneratedPair] = []
    for pair in outcome.accepted:
        if pair.sql not in seen_sql:
            seen_sql.add(pair.sql)
            unique.append(pair)
    removed_dups = len(outcome.accepted) - len(unique)

    args.output.write_text(json.dumps(_format_questions(unique), indent=2))
    print(
        f"[schemapile] generated={len(pairs)}"
        f" accepted={len(outcome.accepted)}"
        f" deduped={removed_dups}"
        f" written={len(unique)}"
        f" errored={outcome.errored} empty={outcome.empty} trivial={outcome.trivial}",
        file=sys.stderr,
    )
    print(f"[schemapile] wrote {args.output}", file=sys.stderr)
    return 0


def _generate_all(
    ws: WorkspaceClient,
    config: SchemaPileConfig,
    schemas: list[dict[str, Any]],
    cache_dir: Path,
) -> list[GeneratedPair]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    pairs: list[GeneratedPair] = []
    for entry in schemas:
        cached = _cache_path(cache_dir, entry["uc_schema"], config)
        if cached.is_file():
            logger.info("[schemapile] cache hit: %s", cached.name)
            raw = json.loads(cached.read_text())
        else:
            raw = _call_model(ws, config, entry)
            cached.write_text(json.dumps(raw, indent=2))
        for item in raw:
            shape = str(item.get("shape", "")).strip()
            question = str(item.get("question", "")).strip()
            sql = str(item.get("sql", "")).strip()
            if shape not in _SHAPES or not question or not sql:
                continue
            pairs.append(
                GeneratedPair(
                    uc_schema=entry["uc_schema"],
                    source_id=entry["source_id"],
                    shape=shape,
                    question=question,
                    sql=sql,
                )
            )
    return pairs


def _cache_path(cache_dir: Path, uc_schema: str, config: SchemaPileConfig) -> Path:
    sig = hashlib.sha256(
        json.dumps(
            {
                "uc_schema": uc_schema,
                "model": config.question_model,
                "questions_per_schema": config.questions_per_schema,
                "temperature": config.question_temperature,
                "seed": config.seed,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return cache_dir / f"{uc_schema}-{sig}.json"


def _call_model(
    ws: WorkspaceClient,
    config: SchemaPileConfig,
    entry: dict[str, Any],
) -> list[dict[str, Any]]:
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

    prompt = _build_prompt(entry, config)
    response = ws.serving_endpoints.query(
        name=config.question_model,
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content=_SYSTEM_PROMPT),
            ChatMessage(role=ChatMessageRole.USER, content=prompt),
        ],
        temperature=config.question_temperature,
        max_tokens=2000,
    )
    text = _first_message_text(response)
    return _parse_json_block(text)


_SYSTEM_PROMPT = textwrap.dedent("""\
    You write evaluation questions for natural-language-to-SQL benchmarks.
    You output strict JSON only: a list of objects each with the keys
    "shape", "question", "sql". Valid "shape" values are
    "single_table_filter", "two_table_join", "aggregation". Every "sql"
    string must be a syntactically valid Databricks SQL SELECT statement
    that references only tables under the catalog and schema named in the
    user prompt. Use fully qualified table names with backticks.
    Do not emit any prose outside the JSON array.
""")


def _build_prompt(entry: dict[str, Any], config: SchemaPileConfig) -> str:
    schema_catalog = config.catalog
    uc_schema = entry["uc_schema"]
    tables = entry.get("tables") or []
    ddl_lines: list[str] = []
    for table in tables:
        table_name = sanitize_identifier(str(table.get("name", "")), prefix="t")
        if not table_name:
            continue
        materialized_columns = [
            (sanitize_identifier(str(c.get("name", "")), prefix="c"), c)
            for c in (table.get("columns") or [])
        ]
        materialized_columns = [(name, c) for name, c in materialized_columns if name]
        cols = ", ".join(f"{name} {c.get('type', '')}" for name, c in materialized_columns)
        pk = table.get("primary_keys") or []
        materialized_pk = [
            name for name in (sanitize_identifier(str(c), prefix="c") for c in pk) if name
        ]
        pk_clause = f" PK({', '.join(materialized_pk)})" if materialized_pk else ""
        fks = table.get("foreign_keys") or []
        fk_clause = ""
        if fks:
            fk_clause = " FKs: " + "; ".join(
                f"{', '.join(_sanitize_fk_columns(fk.get('columns') or []))} -> "
                f"{sanitize_identifier(str(fk.get('foreign_table') or '?'), prefix='t')}"
                f"({', '.join(_sanitize_fk_columns(fk.get('referred_columns') or []))})"
                for fk in fks
            )
        ddl_lines.append(f"- {table_name}({cols}){pk_clause}{fk_clause}")
    schema_block = "\n".join(ddl_lines) if ddl_lines else "(no tables)"

    n = config.questions_per_schema
    n_per_shape = max(1, n // 3)
    return textwrap.dedent(f"""\
        Catalog: `{schema_catalog}`
        Schema: `{uc_schema}` (originally `{entry["source_id"]}`)

        Tables and columns:
        {schema_block}

        Produce exactly {n} question/SQL pairs as a JSON array. Distribute
        them roughly evenly across the three shapes, with at least
        {n_per_shape} of each shape when the schema supports it. SQL
        statements must reference tables as
        `{schema_catalog}`.`{uc_schema}`.`<table>` and must be SELECTs only.
    """)


def _sanitize_fk_columns(columns: list[Any]) -> list[str]:
    return [
        name
        for name in (sanitize_identifier(str(column), prefix="c") for column in columns)
        if name
    ]


_JSON_BLOCK_RE = re.compile(r"\[\s*\{.*?\}\s*\]", re.DOTALL)


def _parse_json_block(text: str) -> list[dict[str, Any]]:
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _first_message_text(response: Any) -> str:
    """Extract the first chat message text from a serving-endpoint response.

    Handles both the SDK `QueryEndpointResponse` object (typed attributes,
    no `.get`) and a plain-dict response shape, so test doubles and the
    real SDK both flow through one path.
    """
    if isinstance(response, dict):
        choices = response.get("choices") or []
    else:
        choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    if message is None:
        return ""
    if isinstance(message, dict):
        return message.get("content") or ""
    return getattr(message, "content", None) or ""


def _validate_all(
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
    pairs: list[GeneratedPair],
) -> ValidationOutcome:
    from databricks.sdk.service.sql import (
        ExecuteStatementRequestOnWaitTimeout,
        StatementState,
    )

    accepted: list[GeneratedPair] = []
    errored = 0
    empty = 0
    trivial = 0
    for pair in pairs:
        if not sql_targets_only_catalog(pair.sql, catalog):
            errored += 1
            continue
        try:
            response = ws.statement_execution.execute_statement(
                warehouse_id=warehouse_id,
                statement=pair.sql,
                wait_timeout="30s",
                on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
            )
        except Exception as exc:
            logger.info("[schemapile] sql errored for %s: %s", pair.uc_schema, exc)
            errored += 1
            continue

        status = getattr(getattr(response, "status", None), "state", None)
        if status != StatementState.SUCCEEDED:
            errored += 1
            continue
        result = getattr(response, "result", None)
        rows = getattr(result, "data_array", None) or []
        if not rows:
            empty += 1
            continue
        if len(rows) == 1 and len(rows[0]) == 1 and rows[0][0] in (None, "", 0, "0"):
            trivial += 1
            continue
        accepted.append(pair)
    return ValidationOutcome(
        accepted=accepted,
        errored=errored,
        empty=empty,
        trivial=trivial,
    )


def _format_questions(pairs: list[GeneratedPair]) -> list[dict[str, Any]]:
    """Emit the dbxcarta client question format.

    The reference arm needs `question_id` + `reference_sql`; the
    schema/source/shape fields stay alongside so failure analysis can trace
    a question back to its origin schema and shape.
    """
    return [
        {
            "question_id": f"sp_{i:04d}",
            "question": pair.question,
            "reference_sql": pair.sql,
            "schema": pair.uc_schema,
            "source_id": pair.source_id,
            "shape": pair.shape,
        }
        for i, pair in enumerate(pairs)
    ]


if __name__ == "__main__":
    raise SystemExit(main())
