from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from dbxcarta.core.env import select_overlay_path

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from dbxcarta.spark.settings import SparkIngestSettings
    from neo4j import Driver


def main() -> None:
    """Entry point for the dbxcarta domain commands.

    - `dbxcarta verify [--run-id RUN_ID]` runs graph and catalog verification.
    - `dbxcarta preset <import-path> {--check-ready|--upload-questions}`
      resolves the given preset and runs the requested action.

    Job submission and wheel upload moved to the separate `dbxcarta-submit`
    command. This package no longer depends on databricks-job-runner.
    """
    overlay = select_overlay_path()
    if overlay is not None:
        # Path only, never resolved values, so no secret reaches logs.
        print(f"dbxcarta: active env overlay: {overlay}", file=sys.stderr)

    command = sys.argv[1:2]
    if command == ["verify"]:
        sys.exit(_handle_verify(sys.argv[2:]))
    if command == ["preset"]:
        sys.exit(_handle_preset(sys.argv[2:]))

    if command:
        print(f"error: unknown command {command[0]!r}", file=sys.stderr)
    print(
        "usage: dbxcarta {verify|preset} ...\n"
        "  Job submission and upload moved to the `dbxcarta-submit` command.",
        file=sys.stderr,
    )
    sys.exit(2)


def _load_env(argv: list[str]) -> tuple[list[str] | None, int]:
    """Resolve and load the overlay/base env files, stripping the option.

    Returns ``(cleaned_argv, 0)`` on success, or ``(None, 2)`` after
    printing an :class:`EnvFileError` so the caller returns the code.
    """
    from dbxcarta.core.env import EnvFileError, load_env_files, resolve_env_files

    try:
        env_files, cleaned = resolve_env_files(argv)
    except EnvFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None, 2
    load_env_files(env_files)
    return cleaned, 0


def _handle_verify(argv: list[str]) -> int:
    import argparse

    cleaned, code = _load_env(argv)
    if cleaned is None:
        return code
    argv = cleaned

    parser = argparse.ArgumentParser(prog="dbxcarta verify")
    parser.add_argument(
        "--run-id",
        help="Run id to verify. Defaults to the most recent status='success' summary.",
    )
    args = parser.parse_args(argv)

    from dbxcarta.spark.ingest.summary_io import LoadSummaryError, load_summary_from_volume
    from dbxcarta.spark.settings import SparkIngestSettings
    from dbxcarta.spark.verify import verify_run

    settings = SparkIngestSettings()

    ws = _build_workspace_client()
    try:
        summary = load_summary_from_volume(ws, settings.dbxcarta_summary_volume, run_id=args.run_id)
    except LoadSummaryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if summary is None:
        scope_msg = f"run_id={args.run_id!r}" if args.run_id else "most recent status='success' run"
        print(
            f"error: no run summary found in {settings.dbxcarta_summary_volume} for {scope_msg}.",
            file=sys.stderr,
        )
        return 2

    driver = _build_neo4j_driver(ws, settings)
    try:
        report = verify_run(
            summary=summary,
            neo4j_driver=driver,
            ws=ws,
            warehouse_id=settings.databricks_warehouse_id,
            catalog=settings.dbxcarta_catalog,
            catalogs=settings.resolved_catalogs(),
            sample_limit=settings.dbxcarta_sample_limit,
        )
    finally:
        driver.close()

    print(report.format())
    return 0 if report.ok else 1


def _handle_preset(argv: list[str]) -> int:
    import argparse
    import os

    cleaned, code = _load_env(argv)
    if cleaned is None:
        return code
    argv = cleaned

    parser = argparse.ArgumentParser(prog="dbxcarta preset")
    parser.add_argument("spec", help="Preset import spec in 'package.module:attr' form.")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check-ready", action="store_true")
    actions.add_argument("--upload-questions", action="store_true")
    parser.add_argument("--warehouse-id", default="")
    parser.add_argument("--strict-optional", action="store_true")
    args = parser.parse_args(argv)

    from dbxcarta.core.presets import (
        QuestionsUploadable,
        ReadinessCheckable,
    )
    from dbxcarta.spark.loader import load_preset

    try:
        preset = load_preset(args.spec)
    except (ValueError, ImportError, AttributeError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.check_ready:
        if not isinstance(preset, ReadinessCheckable):
            print(f"error: preset {args.spec!r} does not implement readiness()", file=sys.stderr)
            return 2
        warehouse_id = args.warehouse_id or os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
        if not warehouse_id:
            print("error: DATABRICKS_WAREHOUSE_ID is required for --check-ready", file=sys.stderr)
            return 2
        ws = _build_workspace_client()
        report = preset.readiness(ws, warehouse_id)
        print(report.format(strict_optional=args.strict_optional))
        return 0 if report.ok(strict_optional=args.strict_optional) else 1

    if args.upload_questions:
        if not isinstance(preset, QuestionsUploadable):
            print(
                f"error: preset {args.spec!r} does not implement upload_questions()",
                file=sys.stderr,
            )
            return 2
        ws = _build_workspace_client()
        preset.upload_questions(ws)
        return 0

    # Unreachable: the actions group is mutually exclusive and required,
    # so exactly one branch above returns. Kept to satisfy the int return
    # contract, since mypy cannot prove the argparse group is exhaustive.
    return 2


def _build_workspace_client() -> WorkspaceClient:
    from dbxcarta.core.workspace import build_workspace_client

    return build_workspace_client()


def _build_neo4j_driver(ws: WorkspaceClient, settings: SparkIngestSettings) -> Driver:
    from dbxcarta.core.workspace import read_workspace_secret
    from neo4j import GraphDatabase

    scope = settings.databricks_secret_scope
    return GraphDatabase.driver(
        read_workspace_secret(ws, scope, "NEO4J_URI"),
        auth=(
            read_workspace_secret(ws, scope, "NEO4J_USERNAME"),
            read_workspace_secret(ws, scope, "NEO4J_PASSWORD"),
        ),
    )
