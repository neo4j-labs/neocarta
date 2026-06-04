# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "databricks-sdk>=0.40",
#     "python-dotenv>=1.0",
# ]
# ///
"""Clean up the DBxCarta ops plane for one integration.

Reads the ops location from a dbxcarta overlay env file (the same
`--env-file` the CLI uses), then, against the given Databricks profile:

  1. DROPs the ops tables in the summary table's catalog/schema:
     `dbxcarta_run_summary`, `client_retrieval`, and every
     `client_staging_*` table (covers all DBXCARTA_CLIENT_ARMS, even
     arms that have since changed).
  2. Empties the ops volume contents — every file and subdirectory
     under the volume root. This includes `runs/`, `staging/`, and
     `ledger/`, so the embedding-reuse ledger is wiped too.

The schema and the volume object itself are kept; only their contents
go. Nothing is deleted until you have seen the full list of targets and
answered the y/n prompt. Pass --yes to skip the prompt in automation.

Usage:
    uv run scripts/clean-dbxcarta.py \
        --profile aws-partner-rk \
        --env-file examples/finance-genie/dbxcarta-overlay.env

    # explicit warehouse instead of auto-resolve
    uv run scripts/clean-dbxcarta.py -p aws-partner-rk \
        -e examples/finance-genie/dbxcarta-overlay.env \
        --warehouse-id 1234567890abcdef
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.sql import StatementState
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ops tables live in the summary table's catalog.schema. These are the
# only names DBxCarta writes there; the prefix match absorbs arm drift.
OPS_TABLE_NAMES = ("dbxcarta_run_summary", "client_retrieval")
OPS_TABLE_PREFIXES = ("client_staging_",)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drop DBxCarta ops tables and empty the ops volume.",
    )
    parser.add_argument(
        "-p",
        "--profile",
        required=True,
        help="Databricks profile from ~/.databrickscfg.",
    )
    parser.add_argument(
        "-e",
        "--env-file",
        required=True,
        type=Path,
        help="dbxcarta overlay env file (provides the ops location).",
    )
    parser.add_argument(
        "--warehouse-id",
        default=None,
        help="SQL warehouse id. Default: DATABRICKS_WAREHOUSE_ID from the "
        "overlay or repo-root .env, else the first available warehouse.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the y/n prompt and delete the listed targets.",
    )
    return parser.parse_args()


def quote_fqn(catalog: str, schema: str, table: str) -> str:
    """Backtick-quote a 3-part name. Ops catalog names contain dashes."""
    return f"`{catalog}`.`{schema}`.`{table}`"


def resolve_ops_location(env_file: Path) -> tuple[str, str, str]:
    """Return (catalog, schema, volume_root) from the overlay env file.

    Catalog/schema come from DBXCARTA_SUMMARY_TABLE. The volume root is
    DATABRICKS_VOLUME_PATH when set, else the first three path segments
    of DBXCARTA_SUMMARY_VOLUME (/Volumes/<catalog>/<schema>/<volume>).
    """
    if not env_file.is_file():
        fail(f"env file not found: {env_file}")
    cfg = dotenv_values(env_file)

    summary_table = (cfg.get("DBXCARTA_SUMMARY_TABLE") or "").strip()
    if summary_table.count(".") != 2:
        fail(
            "DBXCARTA_SUMMARY_TABLE must be a 3-part name "
            f"catalog.schema.table, got: {summary_table!r}"
        )
    catalog, schema, _table = summary_table.split(".")

    volume_path = (cfg.get("DATABRICKS_VOLUME_PATH") or "").strip()
    if not volume_path:
        summary_volume = (cfg.get("DBXCARTA_SUMMARY_VOLUME") or "").strip()
        parts = summary_volume.strip("/").split("/")
        if len(parts) < 4 or parts[0] != "Volumes":
            fail(
                "cannot derive volume root: set DATABRICKS_VOLUME_PATH or a "
                f"valid DBXCARTA_SUMMARY_VOLUME, got: {summary_volume!r}"
            )
        volume_path = "/" + "/".join(parts[:4])

    return catalog, schema, volume_path.rstrip("/")


def resolve_warehouse_id(cli_value: str | None, env_file: Path, client: WorkspaceClient) -> str:
    if cli_value:
        return cli_value
    for source in (env_file, REPO_ROOT / ".env"):
        if source.is_file():
            value = (dotenv_values(source).get("DATABRICKS_WAREHOUSE_ID") or "").strip()
            if value:
                return value
    warehouses = list(client.warehouses.list())
    if not warehouses:
        fail("no SQL warehouse found; pass --warehouse-id")
    return warehouses[0].id


def run_sql(client: WorkspaceClient, warehouse_id: str, statement: str) -> None:
    resp = client.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="30s",
    )
    statement_id = resp.statement_id
    state = resp.status.state if resp.status else None
    while state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        resp = client.statement_execution.get_statement(statement_id)
        state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        detail = ""
        if resp.status and resp.status.error:
            detail = f": {resp.status.error.message}"
        fail(f"SQL failed ({state}){detail}\n  {statement}")


def collect_ops_tables(
    client: WorkspaceClient, warehouse_id: str, catalog: str, schema: str
) -> list[str]:
    """Return ops table names to drop, ordered."""
    resp = client.statement_execution.execute_statement(
        statement=f"SHOW TABLES IN `{catalog}`.`{schema}`",
        warehouse_id=warehouse_id,
        wait_timeout="30s",
    )
    rows = (resp.result.data_array if resp.result else None) or []
    # SHOW TABLES columns: database, tableName, isTemporary.
    table_names = [row[1] for row in rows]
    targets = [
        name
        for name in table_names
        if name in OPS_TABLE_NAMES or any(name.startswith(p) for p in OPS_TABLE_PREFIXES)
    ]
    return sorted(targets)


def collect_volume_entries(client: WorkspaceClient, volume_root: str) -> list[tuple[str, bool]]:
    """Return (path, is_directory) under volume_root in delete order.

    Post-order: a directory's children precede the directory itself, so
    the list can be deleted top to bottom. The volume root is excluded.
    """
    entries: list[tuple[str, bool]] = []

    def walk(directory: str) -> None:
        try:
            children = list(client.files.list_directory_contents(directory))
        except NotFound:
            return
        for child in children:
            if child.is_directory:
                walk(child.path)
                entries.append((child.path, True))
            else:
                entries.append((child.path, False))

    walk(volume_root)
    return entries


def confirm(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def main() -> None:
    args = parse_args()
    catalog, schema, volume_root = resolve_ops_location(args.env_file)
    client = WorkspaceClient(profile=args.profile)
    warehouse_id = resolve_warehouse_id(args.warehouse_id, args.env_file, client)

    print(f"profile      : {args.profile}")
    print(f"ops tables   : `{catalog}`.`{schema}` (drop ops tables)")
    print(f"ops volume   : {volume_root} (empty contents, keep volume)")
    print(f"warehouse id : {warehouse_id}")

    tables = collect_ops_tables(client, warehouse_id, catalog, schema)
    volume_entries = collect_volume_entries(client, volume_root)
    files = [p for p, is_dir in volume_entries if not is_dir]
    dirs = [p for p, is_dir in volume_entries if is_dir]

    print("\nThe following will be DELETED:")
    print(f"\n  Tables ({len(tables)}):")
    if tables:
        for name in tables:
            print(f"    - {quote_fqn(catalog, schema, name)}")
    else:
        print("    (none)")
    print(f"\n  Volume files ({len(files)}) and directories ({len(dirs)}) under {volume_root}:")
    if volume_entries:
        for path, is_dir in volume_entries:
            print(f"    - {path}{'/' if is_dir else ''}")
    else:
        print("    (none)")

    if not tables and not volume_entries:
        print("\nnothing to delete.")
        return

    if not args.yes and not confirm("\nProceed with deletion? [y/N] "):
        print("aborted.")
        return

    print("\n[1/2] dropping ops tables")
    for name in tables:
        fqn = quote_fqn(catalog, schema, name)
        print(f"  DROP TABLE {fqn}")
        run_sql(client, warehouse_id, f"DROP TABLE IF EXISTS {fqn}")

    print("\n[2/2] emptying ops volume (runs/, staging/, ledger/)")
    for path, is_dir in volume_entries:
        if is_dir:
            print(f"  rmdir {path}")
            client.files.delete_directory(path)
        else:
            print(f"  rm    {path}")
            client.files.delete(path)

    print("\ndone.")


if __name__ == "__main__":
    main()
