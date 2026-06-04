"""LLM question generation for the dense-schema fixture.

Generates (question, SQL) pairs by sampling connected subgraphs of tables
from the single large schema. For each batch, a seed table is picked at
random; FK edges expand it to a neighborhood of 3-8 related tables. The
LLM is asked to produce `questions_per_batch` questions from that subgraph.
This distributes questions across the schema rather than concentrating them
on a small number of tables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sys
import textwrap
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dbxcarta.core.env import read_required_warehouse_id
from dbxcarta.core.materialize import sanitize_identifier
from dbxcarta.core.questions import GeneratedPair, ValidationOutcome
from dbxcarta.core.sql_safety import sql_targets_only_catalog
from dbxcarta.core.workspace import build_workspace_client

from dbxcarta_dense_schema_example.config import DenseSchemaConfig, load_config
from dbxcarta_dense_schema_example.utils import load_dotenv_file

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


logger = logging.getLogger(__name__)

_SHAPES = ("single_table_filter", "two_table_join", "aggregation")
_MAX_SUBGRAPH_TABLES = 8
_MIN_SUBGRAPH_TABLES = 3
_MAX_BFS_DEPTH = 2
_MAX_ATTEMPTS_PER_BATCH = 5
_CANDIDATE_MULTIPLIER = 4
_PROMPT_VERSION = 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="dbxcarta-dense-generate-questions")
    parser.add_argument("--dotenv", type=Path, default=Path(__file__).resolve().parents[2] / ".env")
    parser.add_argument("--output", type=Path, default=Path("questions.json"))
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=("Directory for LLM batch cache (default: .cache/questions_<DENSE_TABLE_COUNT>)."),
    )
    parser.add_argument("--warehouse-id", type=str, default=None)
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip SQL execution validation. Useful for offline iteration.",
    )
    args = parser.parse_args()

    load_dotenv_file(args.dotenv)
    config = load_config()

    if not config.candidate_cache.is_file():
        raise FileNotFoundError(
            f"Candidate JSON not found at {config.candidate_cache}."
            " Run dbxcarta-dense-generate first."
        )

    warehouse_id = ""
    if not args.skip_validate:
        warehouse_id = read_required_warehouse_id(
            args.warehouse_id,
            operation="SQL validation",
            extra_hint="or use --skip-validate",
        )

    payload = json.loads(config.candidate_cache.read_text())
    schema_entry = (payload.get("schemas") or [{}])[0]
    cache_dir = _default_cache_dir(config) if args.cache_dir is None else args.cache_dir

    ws = build_workspace_client()
    pairs = _generate_all(ws, config, schema_entry, cache_dir)
    if args.skip_validate:
        outcome = ValidationOutcome(accepted=pairs[: config.questions_target])
    else:
        outcome = _validate_all(
            ws,
            warehouse_id,
            config.catalog,
            pairs,
            target=config.questions_target,
        )

    accepted = outcome.accepted[: config.questions_target]
    args.output.write_text(json.dumps(_format_questions(accepted), indent=2))
    print(
        f"[dense] generated={len(pairs)}"
        f" accepted={len(accepted)}"
        f" errored={outcome.errored} empty={outcome.empty} trivial={outcome.trivial}",
        file=sys.stderr,
    )
    print(f"[dense] wrote {args.output}", file=sys.stderr)
    return 0


def _default_cache_dir(config: DenseSchemaConfig) -> Path:
    return Path(f".cache/questions_{config.table_count}")


def _generate_all(
    ws: WorkspaceClient,
    config: DenseSchemaConfig,
    schema_entry: dict[str, Any],
    cache_dir: Path,
) -> list[GeneratedPair]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    tables = schema_entry.get("tables") or []
    if not tables:
        return []

    fk_graph = _build_fk_graph(tables)
    table_names = [sanitize_identifier(t.get("name", ""), prefix="t") for t in tables]
    table_names = [n for n in table_names if n]

    pairs: list[GeneratedPair] = []
    rng = random.Random(config.seed)
    batch_idx = 0
    candidate_target = config.questions_target * _CANDIDATE_MULTIPLIER
    max_batches = config.questions_target * _CANDIDATE_MULTIPLIER

    while len(pairs) < candidate_target and batch_idx < max_batches:
        seed_table = rng.choice(table_names)
        subgraph_names = _expand_subgraph(seed_table, fk_graph, rng)
        if len(subgraph_names) < _MIN_SUBGRAPH_TABLES:
            batch_idx += 1
            continue

        subgraph_tables = [
            t
            for t in tables
            if sanitize_identifier(t.get("name", ""), prefix="t") in set(subgraph_names)
        ]

        cache_key = _cache_key(subgraph_names, config, batch_idx)
        cached = cache_dir / f"batch_{cache_key}.json"
        if cached.is_file():
            raw = json.loads(cached.read_text())
        else:
            raw = _call_model(ws, config, schema_entry, subgraph_tables)
            cached.write_text(json.dumps(raw, indent=2))

        for item in raw:
            shape = str(item.get("shape", "")).strip()
            question = str(item.get("question", "")).strip()
            sql = str(item.get("sql", "")).strip()
            if shape not in _SHAPES or not question or not sql:
                continue
            pairs.append(
                GeneratedPair(
                    uc_schema=schema_entry.get("uc_schema", ""),
                    source_id=schema_entry.get("source_id", ""),
                    shape=shape,
                    question=question,
                    sql=sql,
                )
            )

        batch_idx += 1

    return pairs[:candidate_target]


def _build_fk_graph(tables: list[dict[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for table in tables:
        name = sanitize_identifier(table.get("name", ""), prefix="t")
        if not name:
            continue
        graph.setdefault(name, set())
        for fk in table.get("foreign_keys") or []:
            foreign = sanitize_identifier(str(fk.get("foreign_table", "")), prefix="t")
            if foreign and foreign != name:
                graph[name].add(foreign)
                graph.setdefault(foreign, set()).add(name)
    return graph


def _expand_subgraph(
    seed: str,
    graph: dict[str, set[str]],
    rng: random.Random,
) -> list[str]:
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    while queue and len(visited) < _MAX_SUBGRAPH_TABLES:
        node, depth = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        if depth < _MAX_BFS_DEPTH:
            neighbors = sorted(graph.get(node, set()))
            rng.shuffle(neighbors)
            for neighbor in neighbors:
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))
    return list(visited)


def _cache_key(subgraph_names: list[str], config: DenseSchemaConfig, batch_idx: int) -> str:
    sig = json.dumps(
        {
            "tables": sorted(subgraph_names),
            "model": config.question_model,
            "per_batch": config.questions_per_batch,
            "temperature": config.question_temperature,
            "batch": batch_idx,
            "prompt_version": _PROMPT_VERSION,
        },
        sort_keys=True,
    ).encode()
    return hashlib.sha256(sig).hexdigest()[:16]


def _call_model(
    ws: WorkspaceClient,
    config: DenseSchemaConfig,
    schema_entry: dict[str, Any],
    subgraph_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

    prompt = _build_prompt(schema_entry, subgraph_tables, config)
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
    Create high-quality natural-language-to-SQL evaluation questions for a
    large synthetic Databricks Unity Catalog schema.

    Output strict JSON only: a list of objects. Each object must contain:
    - "shape": one of "single_table_filter", "two_table_join", "aggregation"
    - "question": a concise business-user question
    - "sql": a read-only Databricks SQL SELECT

    Prioritize realistic enterprise analytics questions. Avoid trivial
    lookups, toy counts, and questions answerable by selecting only id
    columns. Use business terms from table and column names. Prefer questions
    that require filters on status, date, amount, category, region, or type
    fields, meaningful joins through declared foreign keys, grouped
    aggregations, and ordered or top-N results.

    SQL requirements:
    - Use only the catalog, schema, tables, columns, and FK relationships
      shown in the user prompt.
    - Use fully qualified backticked table names.
    - Emit SELECT statements only.
    - Make queries likely to return non-empty results from the sample data.
    - Do not use information_schema, system tables, DDL, DML, or cross-schema
      joins.
    - Keep each query understandable enough for an evaluator to inspect.

    Do not emit any prose outside the JSON array.
""")


def _build_prompt(
    schema_entry: dict[str, Any],
    tables: list[dict[str, Any]],
    config: DenseSchemaConfig,
) -> str:
    catalog = config.catalog
    uc_schema = schema_entry.get("uc_schema", "")
    ddl_lines: list[str] = []
    for table in tables:
        table_name = sanitize_identifier(str(table.get("name", "")), prefix="t")
        if not table_name:
            continue
        safe_cols = [
            (sanitize_identifier(str(c.get("name", "")), prefix="c"), c)
            for c in (table.get("columns") or [])
        ]
        safe_cols = [(n, c) for n, c in safe_cols if n]
        cols = ", ".join(f"{name} {c.get('type', '')}" for name, c in safe_cols)
        pk = [sanitize_identifier(str(k), prefix="c") for k in (table.get("primary_keys") or [])]
        pk_clause = f" PK({', '.join(pk)})" if pk else ""
        fks = table.get("foreign_keys") or []
        fk_parts = []
        for fk in fks:
            fk_cols = [sanitize_identifier(str(c), prefix="c") for c in (fk.get("columns") or [])]
            ref_table = sanitize_identifier(str(fk.get("foreign_table") or ""), prefix="t")
            ref_cols = [
                sanitize_identifier(str(c), prefix="c") for c in (fk.get("referred_columns") or [])
            ]
            if fk_cols and ref_table and ref_cols:
                fk_parts.append(f"{', '.join(fk_cols)} -> {ref_table}({', '.join(ref_cols)})")
        fk_clause = f" FKs: {'; '.join(fk_parts)}" if fk_parts else ""
        sample_clause = _format_sample_rows(safe_cols, table.get("rows") or [])
        ddl_lines.append(f"- {table_name}({cols}){pk_clause}{fk_clause}{sample_clause}")

    schema_block = "\n".join(ddl_lines) if ddl_lines else "(no tables)"
    n = config.questions_per_batch
    n_per_shape = max(1, n // 3)
    return textwrap.dedent(f"""\
        Catalog: `{catalog}`
        Schema: `{uc_schema}`

        Tables:
        {schema_block}

        Produce exactly {n} question/SQL pairs as a JSON array. Distribute
        across the three shapes with at least {n_per_shape} of each shape.
        SQL must reference tables as `{catalog}`.`{uc_schema}`.`<table>`.
        Use sample rows to choose filter literals that are likely to exist.
        Prefer business-readable columns over opaque id-only projections.
        Prefer multi-table JOINs using the FK relationships shown above.
        For aggregation questions, include meaningful GROUP BY dimensions and
        ORDER BY or HAVING clauses where appropriate.
    """)


def _format_sample_rows(
    safe_cols: list[tuple[str, dict[str, Any]]],
    rows: list[list[Any]],
) -> str:
    if not safe_cols or not rows:
        return ""
    col_names = [name for name, _ in safe_cols]
    samples = []
    for row in rows[:2]:
        sample = {name: row[idx] for idx, name in enumerate(col_names) if idx < len(row)}
        samples.append(sample)
    return f" Samples: {json.dumps(samples, default=str)}"


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
    target: int | None = None,
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
            logger.info("[dense] sql errored: %s", exc)
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
        if target is not None and len(accepted) >= target:
            break
    return ValidationOutcome(accepted=accepted, errored=errored, empty=empty, trivial=trivial)


def _format_questions(pairs: list[GeneratedPair]) -> list[dict[str, Any]]:
    return [
        {
            "question_id": f"ds_{i:04d}",
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
