"""DBxCarta demo setup script.

Sets up the test catalog schemas defined in tests/fixtures/setup_test_catalog.sql
against a Databricks SQL warehouse, then prints instructions for running the
full graph_rag demo using the pre-seeded question set.

Usage:
    python scripts/run_demo.py [--catalog CATALOG] [--volume-path VOL_PATH] [--teardown]

Required env vars:
    DATABRICKS_WAREHOUSE_ID    SQL warehouse to execute DDL against

Optional env vars (overridden by the corresponding CLI flags):
    DBXCARTA_CATALOG           Catalog to set up schemas in (default: main)
    DATABRICKS_VOLUME_PATH     UC Volume base path for external tables
                               (e.g. /Volumes/main/default/dbxcarta)
                               Required only for dbxcarta_test_external schema.

After setup, run the full demo via the dbxcarta CLI with:
    DBXCARTA_CATALOG=<catalog>
    DBXCARTA_SCHEMAS=dbxcarta_test_sales,dbxcarta_test_inventory,dbxcarta_test_hr,dbxcarta_test_events
    DBXCARTA_CLIENT_QUESTIONS=/Volumes/<catalog>/<schema>/<volume>/demo_questions.json
    DBXCARTA_CLIENT_ARMS=graph_rag
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

load_dotenv()

_SETUP_SQL = Path(__file__).parent.parent / "tests" / "fixtures" / "setup_test_catalog.sql"
_INSERT_SQL = Path(__file__).parent.parent / "tests" / "fixtures" / "insert_test_data.sql"
_DEMO_SCHEMAS = [
    "dbxcarta_test_sales",
    "dbxcarta_test_inventory",
    "dbxcarta_test_hr",
    "dbxcarta_test_events",
]
# Teardown includes external schema and legacy backward-compat schemas for full cleanup.
_TEARDOWN_SCHEMAS = [
    *_DEMO_SCHEMAS,
    "dbxcarta_test_external",
    "dbxcarta_fk_test",
    "dbxcarta_fk_test_b",
]


def _setup(
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
    volume_path: str,
) -> None:
    from dbxcarta.core.executor import execute_ddl, split_sql_statements

    raw = _SETUP_SQL.read_text()
    # Backtick-quote the catalog in USE CATALOG (hyphen requires quoting in SQL).
    # All other ${catalog} occurrences in the fixture are in comments.
    # Catalog context for all other statements is set via the execute_statement API parameter.
    sql = raw.replace("USE CATALOG ${catalog}", f"USE CATALOG `{catalog}`").replace(
        "${catalog}", catalog
    )
    if volume_path:
        sql = sql.replace("${volume_path}", volume_path)
    statements = split_sql_statements(sql)
    total = len(statements)

    print(f"Setting up demo schemas in catalog '{catalog}' ({total} statements)...")

    skipped = 0
    for i, stmt in enumerate(statements, 1):
        if "${volume_path}" in stmt:
            print(f"  [{i}/{total}] SKIP (no volume path — external table skipped)")
            skipped += 1
            continue
        preview = stmt[:70].replace("\n", " ")
        succeeded, error = execute_ddl(ws, warehouse_id, stmt, timeout_sec=50, catalog=catalog)
        if succeeded:
            print(f"  [{i}/{total}] OK  {preview}")
        else:
            print(f"  [{i}/{total}] ERR {preview}")
            print(f"  Error: {error}")
            print(
                f"\nSetup failed at statement {i}/{total}. "
                f"Subsequent FK constraints will cascade from this failure.\n"
                f"Fix the error and re-run, or tear down first for a clean start:\n"
                f"  python scripts/run_demo.py --catalog {catalog} --teardown"
            )
            sys.exit(1)

    done = total - skipped
    suffix = f" ({skipped} skipped — no volume path)" if skipped else ""
    print(f"\nDone. {done} statement(s) executed successfully{suffix}.")


def _insert_data(
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
    volume_path: str,
) -> None:
    from dbxcarta.core.executor import execute_ddl, split_sql_statements

    raw = _INSERT_SQL.read_text()
    sql = raw.replace("USE CATALOG ${catalog}", f"USE CATALOG `{catalog}`").replace(
        "${catalog}", catalog
    )
    statements = split_sql_statements(sql)
    total = len(statements)

    print(f"Inserting test data into catalog '{catalog}' ({total} statements)...")

    skipped = 0
    for i, stmt in enumerate(statements, 1):
        if not volume_path and "dbxcarta_test_external" in stmt:
            print(f"  [{i}/{total}] SKIP (no volume path — external table insert skipped)")
            skipped += 1
            continue
        preview = stmt[:70].replace("\n", " ")
        succeeded, error = execute_ddl(ws, warehouse_id, stmt, timeout_sec=50, catalog=catalog)
        if succeeded:
            print(f"  [{i}/{total}] OK  {preview}")
        else:
            print(f"  [{i}/{total}] ERR {preview}")
            print(f"  Error: {error}")
            print(
                f"\nData insert failed at statement {i}/{total}.\n"
                f"Fix the error and re-run, or tear down and start fresh:\n"
                f"  python scripts/run_demo.py --catalog {catalog} --teardown"
            )
            sys.exit(1)

    done = total - skipped
    suffix = f" ({skipped} skipped — no volume path)" if skipped else ""
    print(f"\nDone. {done} statement(s) executed successfully{suffix}.")


def _teardown(
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
) -> None:
    from dbxcarta.core.executor import execute_ddl

    statements = [f"DROP SCHEMA IF EXISTS {schema} CASCADE" for schema in _TEARDOWN_SCHEMAS]
    total = len(statements)

    print(f"Tearing down demo schemas in catalog '{catalog}'...")

    warnings = []
    for i, stmt in enumerate(statements, 1):
        succeeded, error = execute_ddl(ws, warehouse_id, stmt, timeout_sec=50, catalog=catalog)
        if succeeded:
            print(f"  [{i}/{total}] OK  {stmt}")
        else:
            print(f"  [{i}/{total}] WARN {stmt}")
            print(f"         {error}")
            warnings.append(error)

    if warnings:
        print(f"\n{len(warnings)} drop(s) reported warnings (schemas may not have existed).")
    else:
        print(f"\nDone. {total} schema(s) removed.")


def _print_next_steps(catalog: str, volume_path: str) -> None:
    schemas = ",".join(_DEMO_SCHEMAS)
    questions = (
        f"{volume_path.rstrip('/')}/demo_questions.json"
        if volume_path
        else "/Volumes/<catalog>/<schema>/<volume>/demo_questions.json"
    )
    print(f"""
Next steps
----------
1. Confirm these values in .env:

   DBXCARTA_CATALOG={catalog}
   DBXCARTA_SCHEMAS={schemas}
   DBXCARTA_CLIENT_QUESTIONS={questions}
   DBXCARTA_CLIENT_ARMS=graph_rag

2. Upload the package and demo questions, then build the Neo4j semantic layer:

   uv run dbxcarta-submit publish-wheels
   uv run dbxcarta-submit upload --data tests/fixtures
   uv run dbxcarta-submit submit-entrypoint ingest

3. After ingest succeeds, run the graph_rag demo client:

   uv run dbxcarta-submit submit-entrypoint client

   The question set exercises cross-schema joins (sales->inventory, sales->hr),
   self-referential FKs (hr.employees.manager_id), the composite FK path
   (product_suppliers), and intra-schema event analytics.

4. To tear down the schemas after the demo:

   uv run python scripts/run_demo.py --catalog {catalog} --teardown
""")


def main() -> None:
    parser = argparse.ArgumentParser(description="DBxCarta demo schema setup")
    parser.add_argument(
        "--catalog",
        default=os.getenv("DBXCARTA_CATALOG", "main"),
        help="Target UC catalog (default: DBXCARTA_CATALOG env var, else 'main')",
    )
    parser.add_argument(
        "--volume-path",
        default=os.getenv("DATABRICKS_VOLUME_PATH", ""),
        help="UC Volume base path for external tables (e.g. /Volumes/cat/schema/vol)",
    )
    parser.add_argument(
        "--teardown",
        action="store_true",
        help="Drop all demo schemas instead of creating them",
    )
    args = parser.parse_args()

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
    if not warehouse_id:
        print("ERROR: DATABRICKS_WAREHOUSE_ID is not set.", file=sys.stderr)
        sys.exit(1)

    from dbxcarta.core.executor import preflight_warehouse
    from dbxcarta.core.workspace import build_workspace_client

    ws = build_workspace_client()
    preflight_warehouse(ws, warehouse_id)

    if args.teardown:
        _teardown(ws, warehouse_id, args.catalog)
    else:
        _setup(ws, warehouse_id, args.catalog, args.volume_path)
        _insert_data(ws, warehouse_id, args.catalog, args.volume_path)
        _print_next_steps(args.catalog, args.volume_path)


if __name__ == "__main__":
    main()
