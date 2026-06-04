"""Read-only local CLI demo for the Finance Genie semantic layer."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dbxcarta.client import parse_sql
from dbxcarta.client.compare import compare_result_sets
from dbxcarta.client.graph_rag import build_graph_rag_context
from dbxcarta.client.local_generation import generate_sql_local
from dbxcarta.client.questions import Question, load_questions
from dbxcarta.client.schema_dump import fetch_schema_dump
from dbxcarta.client.settings import ClientSettings
from dbxcarta.core.executor import fetch_rows, preflight_warehouse
from dbxcarta.core.workspace import build_workspace_client
from dotenv import load_dotenv

# The bundled questions.json and the standalone .env both live at the example
# root, two levels up from this module, the same place the dbxcarta preset reads
# questions.json from. parents[2] resolves to examples/finance-genie/
# (local_demo.py -> dbxcarta_finance_genie_example -> src -> finance-genie).
_EXAMPLE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS = _EXAMPLE_ROOT / "questions.json"
# Anchor .env lookup to the example root so the demo never inherits the parent
# dbxcarta repo's .env.
DEMO_ENV_FILE = _EXAMPLE_ROOT / ".env"
_READ_ONLY_SQL_RE = re.compile(r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE)
_MUTATING_SQL_RE = re.compile(
    r"\b(ALTER|COPY|CREATE|DELETE|DROP|INSERT|MERGE|REPLACE|TRUNCATE|UPDATE)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DemoResult:
    question: str
    context_ids: list[str]
    context_text: str
    generated_sql: str
    columns: list[str]
    rows: list[list[Any]]
    reference_sql: str | None = None
    correct: bool | None = None
    comparison_error: str | None = None


def main(argv: list[str] | None = None) -> int:
    load_dotenv(DEMO_ENV_FILE, override=False)
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "questions":
            return _handle_questions(args)
        if args.command == "preflight":
            return _handle_preflight(args)
        if args.command == "sql":
            return _handle_sql(args)
        if args.command == "ask":
            return _handle_ask(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbxcarta demo finance-genie",
        description="Run a read-only local Finance Genie semantic-layer demo.",
    )
    parser.set_defaults(command="")
    subparsers = parser.add_subparsers(dest="command")

    questions = subparsers.add_parser("questions", help="List sample questions.")
    questions.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS),
        help="Path to a local questions JSON file.",
    )
    questions.set_defaults(command="questions")

    preflight = subparsers.add_parser(
        "preflight",
        help="Check local config, warehouse connectivity, and graph content.",
    )
    preflight.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS),
        help="Path to a local questions JSON file.",
    )
    preflight.set_defaults(command="preflight")

    sql = subparsers.add_parser("sql", help="Run a read-only SQL statement.")
    sql.add_argument("statement", help="SQL statement to execute.")
    sql.add_argument("--limit", type=int, default=20, help="Rows to print.")
    sql.set_defaults(command="sql")

    ask = subparsers.add_parser(
        "ask",
        help="Generate and run SQL using dbxcarta graph context.",
    )
    ask.add_argument("question", nargs="?", help="Question text.")
    ask.add_argument("--question-id", help="Question id from the question set.")
    ask.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS),
        help="Path to a local questions JSON file.",
    )
    ask.add_argument("--limit", type=int, default=20, help="Rows to print.")
    ask.add_argument(
        "--show-context",
        action="store_true",
        help="Print retrieved graph context ids.",
    )
    ask.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the prompt sent to the serving endpoint.",
    )
    ask.add_argument(
        "--no-compare-reference",
        action="store_true",
        help="Skip comparison with reference_sql when present.",
    )
    ask.set_defaults(command="ask")

    return parser


def _handle_questions(args: argparse.Namespace) -> int:
    questions = _load_local_questions(args.questions)
    for question in questions:
        print(f"{question.question_id}\t{question.question}")
    return 0


def _handle_preflight(args: argparse.Namespace) -> int:
    settings = _load_settings()
    questions = _load_local_questions(args.questions)
    ws = build_workspace_client()

    preflight_warehouse(ws, settings.databricks_warehouse_id)
    if not settings.dbxcarta_chat_endpoint:
        raise RuntimeError("DBXCARTA_CHAT_ENDPOINT is required for ask.")

    schema_text = fetch_schema_dump(settings)
    print("config=ok")
    print(f"warehouse={settings.databricks_warehouse_id}")
    print(f"questions={len(questions)} path={args.questions}")
    print(f"chat_endpoint={settings.dbxcarta_chat_endpoint}")
    print(f"embedding_endpoint={settings.dbxcarta_embed_endpoint}")
    print(f"graph_schema_lines={len(schema_text.splitlines())}")
    return 0


def _handle_sql(args: argparse.Namespace) -> int:
    settings = _load_settings()
    _ensure_read_only_sql(args.statement)
    ws = build_workspace_client()
    cols, rows, error = fetch_rows(
        ws,
        settings.databricks_warehouse_id,
        args.statement,
        settings.dbxcarta_client_timeout_sec,
    )
    if rows is None:
        raise RuntimeError(f"SQL failed: {error}")

    _print_rows(cols or [], rows, limit=args.limit)
    return 0


def _handle_ask(args: argparse.Namespace) -> int:
    settings = _load_settings()
    question_row = _resolve_question(args.question, args.question_id, args.questions)
    ws = build_workspace_client()
    result = run_graph_rag_question(
        ws=ws,
        settings=settings,
        question=question_row.question,
        reference_sql=question_row.reference_sql,
        compare_reference=not args.no_compare_reference,
        show_prompt=args.show_prompt,
    )

    print(f"question: {result.question}")
    if args.show_context:
        _print_context(result.context_ids, result.context_text)
    print("\ngenerated_sql:")
    print(result.generated_sql)
    if result.correct is not None:
        status = "correct" if result.correct else "different"
        print(f"\nreference_comparison: {status}")
        if result.comparison_error:
            print(f"comparison_error: {result.comparison_error}")
    print("\nresults:")
    _print_rows(result.columns, result.rows, limit=args.limit)
    return 0


def run_graph_rag_question(
    *,
    ws: Any,
    settings: ClientSettings,
    question: str,
    reference_sql: str | None = None,
    compare_reference: bool = True,
    show_prompt: bool = False,
) -> DemoResult:
    """Run one graph_rag local demo question end to end.

    Retrieval and prompt assembly come from the shared client seam so this
    demo cannot drift from the evaluation harness. Only the local Model
    Serving call, the read-only guard, the reference comparison, and the
    printing are demo-specific.
    """
    preflight_warehouse(ws, settings.databricks_warehouse_id)

    context = build_graph_rag_context(ws, settings, question)
    if show_prompt:
        print("prompt:")
        print(context.prompt)
        print()

    raw_sql = generate_sql_local(ws, settings.dbxcarta_chat_endpoint, context.prompt)
    generated_sql, parse_ok = parse_sql(raw_sql)
    if not parse_ok or not generated_sql:
        raise RuntimeError(f"generated response was not valid SQL: {raw_sql!r}")
    _ensure_read_only_sql(generated_sql)

    cols, rows, error = fetch_rows(
        ws,
        settings.databricks_warehouse_id,
        generated_sql,
        settings.dbxcarta_client_timeout_sec,
    )
    if rows is None:
        raise RuntimeError(f"generated SQL failed: {error}")

    correct: bool | None = None
    comparison_error: str | None = None
    if compare_reference and reference_sql:
        ref_cols, ref_rows, ref_error = fetch_rows(
            ws,
            settings.databricks_warehouse_id,
            reference_sql,
            settings.dbxcarta_client_timeout_sec,
        )
        if ref_rows is None:
            correct = False
            comparison_error = f"reference SQL failed: {ref_error}"
        else:
            correct, comparison_error = compare_result_sets(
                cols or [],
                rows,
                ref_cols or [],
                ref_rows,
            )

    return DemoResult(
        question=question,
        context_ids=context.seed_ids,
        context_text=context.context_text,
        generated_sql=generated_sql,
        columns=cols or [],
        rows=rows,
        reference_sql=reference_sql,
        correct=correct,
        comparison_error=comparison_error,
    )


def _load_settings() -> ClientSettings:
    return ClientSettings()


def _resolve_question(
    question_text: str | None,
    question_id: str | None,
    questions_path: str,
) -> Question:
    if question_text and question_id:
        raise ValueError("Use either question text or --question-id, not both.")
    if question_text:
        return Question(question_id="adhoc", question=question_text)
    if not question_id:
        raise ValueError("Provide question text or --question-id.")

    questions = _load_local_questions(questions_path)
    for row in questions:
        if row.question_id == question_id:
            return row
    raise ValueError(f"Question id not found: {question_id}")


def _load_local_questions(source: str) -> list[Question]:
    questions = load_questions(source)
    if not questions:
        raise ValueError(f"questions file is empty: {source}")
    return questions


def _ensure_read_only_sql(sql: str) -> None:
    statement = sql.strip().rstrip(";").strip()
    if not statement or ";" in statement:
        raise ValueError("Only one read-only SQL statement is allowed.")
    if not _READ_ONLY_SQL_RE.match(statement) or _MUTATING_SQL_RE.search(statement):
        raise ValueError("Only SELECT, WITH, or EXPLAIN statements are allowed.")


def _print_rows(columns: list[str], rows: list[list[Any]], *, limit: int) -> None:
    if not rows:
        print("(no rows)")
        return

    visible_rows = rows[: max(limit, 0)]
    if not columns:
        first_row = visible_rows[0] if visible_rows else rows[0]
        columns = [f"col_{i + 1}" for i in range(len(first_row))]

    widths = [len(col) for col in columns]
    rendered_rows = []
    for row in visible_rows:
        rendered = [_cell(value) for value in row]
        rendered_rows.append(rendered)
        for i, value in enumerate(rendered):
            widths[i] = min(max(widths[i], len(value)), 48)

    header = " | ".join(_clip(col, widths[i]) for i, col in enumerate(columns))
    sep = "-+-".join("-" * width for width in widths)
    print(header)
    print(sep)
    for row in rendered_rows:
        print(" | ".join(_clip(value, widths[i]) for i, value in enumerate(row)))

    remaining = len(rows) - len(visible_rows)
    if remaining > 0:
        print(f"... {remaining} more row(s)")


def _print_context(context_ids: list[str], context_text: str) -> None:
    print("context:")
    print("  context_ids are vector-search seed nodes from the dbxcarta graph.")
    print("  The model receives the expanded retrieved_context text below.")
    print("context_ids:")
    for context_id in context_ids:
        print(f"  {context_id}")
    print("\nretrieved_context:")
    print(context_text or "(no retrieved context)")


def _cell(value: Any) -> str:
    if value is None:
        return "NULL"
    return str(value)


def _clip(value: str, width: int) -> str:
    if len(value) <= width:
        return value.ljust(width)
    return value[: width - 3] + "..."


if __name__ == "__main__":
    sys.exit(main())
