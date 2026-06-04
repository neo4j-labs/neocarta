"""Automated end-to-end integration test harness for DBxCarta.

Steps:
  preflight        — workspace + warehouse connectivity
  unit_tests       — fast pytest suite
  schema_setup     — teardown + fixture DDL
  ingest_run       — upload, submit, download RunSummary
  assertions       — validate RunSummary contents
  references_diff  — fixture FK declarations vs Neo4j REFERENCES set
  write_output     — write results to volume

Usage:
    uv run python scripts/run_autotest.py
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

FIXTURE_SCHEMAS = [
    "dbxcarta_test_sales",
    "dbxcarta_test_inventory",
    "dbxcarta_test_hr",
    "dbxcarta_test_events",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_ws():
    from dbxcarta.core.workspace import build_workspace_client

    return build_workspace_client()


def _run(
    cmd: list[str], *, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_overrides or {})}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=PROJECT_ROOT)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def run_preflight() -> dict:
    print("\n=== Preflight ===")
    errors: list[str] = []

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
    if not warehouse_id:
        errors.append("DATABRICKS_WAREHOUSE_ID not set")

    catalog = os.environ.get("DBXCARTA_CATALOG", "")
    if catalog != "dbxcarta-catalog":
        errors.append(f"DBXCARTA_CATALOG={catalog!r}, expected 'dbxcarta-catalog'")

    cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID", "")
    compute_mode = os.environ.get("DATABRICKS_COMPUTE_MODE", "")
    if not cluster_id and compute_mode != "serverless":
        errors.append(
            "No compute configured: DATABRICKS_CLUSTER_ID unset and "
            "DATABRICKS_COMPUTE_MODE != serverless"
        )

    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        return {"status": "fail", "errors": errors}

    try:
        from dbxcarta.core.executor import preflight_warehouse

        ws = _make_ws()
        preflight_warehouse(ws, warehouse_id)
        print(f"  Warehouse {warehouse_id}: OK")
    except Exception as exc:
        return {"status": "fail", "errors": [str(exc)]}

    return {"status": "pass"}


# ---------------------------------------------------------------------------
# Unit Test Gate
# ---------------------------------------------------------------------------


def run_unit_tests() -> dict:
    print("\n=== Unit Test Gate ===")
    result = _run(
        [
            "uv",
            "run",
            "pytest",
            "tests/",
            "-x",
            "-q",
            "--ignore=tests/integration",
        ]
    )

    passed = 0
    failed = 0
    for line in result.stdout.splitlines():
        m = re.search(r"(\d+) passed", line)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", line)
        if m:
            failed = int(m.group(1))

    status = "pass" if result.returncode == 0 else "fail"
    return {"status": status, "passed": passed, "failed": failed}


# ---------------------------------------------------------------------------
# Schema Teardown and Setup
# ---------------------------------------------------------------------------


def run_schema_setup() -> dict:
    print("\n=== Schema Teardown and Setup ===")
    catalog = os.environ["DBXCARTA_CATALOG"]

    # Teardown — best-effort (ignore returncode)
    print("  Teardown...")
    _run(
        ["uv", "run", "python", "scripts/run_demo.py", "--catalog", catalog, "--teardown"],
        env_overrides={"DATABRICKS_VOLUME_PATH": ""},
    )

    # Setup — external schema is out of scope for the autotest (no FKs, requires
    # cloud storage path). Clear DATABRICKS_VOLUME_PATH so run_demo.py skips it.
    print("  Setup...")
    result = _run(
        ["uv", "run", "python", "scripts/run_demo.py", "--catalog", catalog],
        env_overrides={"DATABRICKS_VOLUME_PATH": ""},
    )

    if result.returncode != 0:
        return {"status": "fail", "error": "Schema setup failed"}

    ok_count = result.stdout.count("] OK ")
    err_count = result.stdout.count("] ERR ")
    return {"status": "pass", "statements_ok": ok_count, "statements_failed": err_count}


# ---------------------------------------------------------------------------
# Ingest Run
# ---------------------------------------------------------------------------


def run_ingest() -> dict:
    print("\n=== Ingest Run ===")

    summary_volume = os.environ.get("DBXCARTA_SUMMARY_VOLUME", "")
    if not summary_volume:
        return {"status": "fail", "error": "DBXCARTA_SUMMARY_VOLUME not set"}

    from databricks_job_runner.download import download_file, list_volume_files

    ws = _make_ws()

    print("  Publishing wheels...")
    r = _run(["uv", "run", "dbxcarta-submit", "publish-wheels"])
    if r.returncode != 0:
        return {"status": "fail", "error": "wheel publish failed"}

    files_before = set(list_volume_files(ws, summary_volume))

    print("  Submitting pipeline run...")
    schemas_val = ",".join(FIXTURE_SCHEMAS)
    r = _run(
        ["uv", "run", "dbxcarta-submit", "submit-entrypoint", "ingest"],
        env_overrides={"DBXCARTA_SCHEMAS": schemas_val},
    )
    if r.returncode != 0:
        return {"status": "fail", "error": "pipeline run failed"}

    run_id: str | None = None
    for line in r.stdout.splitlines():
        m = re.search(r"Run ID:\s+(\d+)", line)
        if m:
            run_id = m.group(1)
            break

    if not run_id:
        return {"status": "fail", "error": "Could not parse run_id from submit output"}

    print(f"  run_id={run_id}")

    files_after = set(list_volume_files(ws, summary_volume))
    new_files = files_after - files_before
    summary_pat = re.compile(r"^dbxcarta_.*\.json$")
    matches = sorted(f for f in new_files if summary_pat.match(f))
    if not matches:
        return {
            "status": "fail",
            "run_id": run_id,
            "error": (
                f"No new RunSummary JSON written to {summary_volume} after run {run_id}. "
                f"New files seen: {sorted(new_files)!r}"
            ),
        }

    filename = matches[-1]  # lexicographic sort puts newest YYYYMMDDTHHMMSSZ last
    remote_path = filename if filename.startswith("/Volumes") else f"{summary_volume}/{filename}"

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        local_path = Path(tmp.name)

    try:
        download_file(ws, remote_path, local_path)
        run_summary = json.loads(local_path.read_text())
    finally:
        local_path.unlink(missing_ok=True)

    print(f"  RunSummary: {filename}")
    return {"status": "pass", "run_id": run_id, "run_summary": run_summary}


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def run_assertions(run_summary: dict) -> dict:
    print("\n=== Assertions ===")
    failed: list[str] = []

    def assert_eq(key: str, actual, expected) -> None:
        if actual != expected:
            failed.append(f"{key}: expected {expected!r}, got {actual!r}")

    def assert_ge(key: str, actual, minimum) -> None:
        if actual is None or actual < minimum:
            failed.append(f"{key}: expected >= {minimum}, got {actual!r}")

    def assert_present(key: str, value) -> None:
        if not value:
            failed.append(f"{key}: expected non-empty, got {value!r}")

    assert_eq("status", run_summary.get("status"), "success")
    assert_eq("error", run_summary.get("error"), None)

    rc = run_summary.get("row_counts", {})
    assert_ge("row_counts.schemas", rc.get("schemas"), 4)
    assert_ge("row_counts.tables", rc.get("tables"), 19)
    assert_ge("row_counts.fk_declared", rc.get("fk_declared"), 16)
    assert_ge("row_counts.fk_edges", rc.get("fk_edges"), 16)
    assert_present("neo4j_counts", run_summary.get("neo4j_counts"))

    for f in failed:
        print(f"  FAIL: {f}")
    if not failed:
        print("  All assertions passed.")

    return {"status": "pass" if not failed else "fail", "failed": failed}


# ---------------------------------------------------------------------------
# Fixture-FK ↔ Neo4j REFERENCES diff
# ---------------------------------------------------------------------------
#
# This step exists because the run summary's `fk_*` counters and Neo4j's
# REFERENCES edge count can drift apart silently without a direct comparison.
#
# The fixture (tests/fixtures/setup_test_catalog.sql) is the authoritative
# source for *declared* FKs. The pipeline also produces *inferred* FK edges
# via `dbxcarta.spark.ingest.fk.metadata` (column-comment hints) and optionally
# `dbxcarta.spark.ingest.fk.semantic`; replicating that logic here would just duplicate
# the pipeline. So this step asserts only what the fixture pins down (the
# declared bucket) and reports the inferred bucket informationally so a
# regression in inference is visible without being asserted against a
# hand-curated list. Bucketing keys off the `r.source` property each
# REFERENCES edge carries (`'declared'` / `'inferred_metadata'` / etc.).


_FK_RE = re.compile(
    r"ALTER\s+TABLE\s+(?P<src_schema>\w+)\.(?P<src_table>\w+)\s+"
    r"ADD\s+CONSTRAINT\s+\w+\s+"
    r"FOREIGN\s+KEY\s*\(\s*(?P<src_col>\w+)\s*\)\s+"
    r"REFERENCES\s+(?P<dst_schema>\w+)\.(?P<dst_table>\w+)\s*\(\s*(?P<dst_col>\w+)\s*\)",
    re.IGNORECASE,
)


def _parse_fixture_fks(catalog: str) -> set[tuple[str, str]]:
    """Parse `tests/fixtures/setup_test_catalog.sql` and return the canonical
    set of *declared* `(src_id, dst_id)` REFERENCES edges, normalized via
    `generate_id`.
    """
    from dbxcarta.spark.contract import generate_id

    fixture_sql = (PROJECT_ROOT / "tests" / "fixtures" / "setup_test_catalog.sql").read_text()
    out: set[tuple[str, str]] = set()
    for m in _FK_RE.finditer(fixture_sql):
        src_id = generate_id(catalog, m["src_schema"], m["src_table"], m["src_col"])
        dst_id = generate_id(catalog, m["dst_schema"], m["dst_table"], m["dst_col"])
        out.add((src_id, dst_id))
    return out


def _neo4j_references_by_source(ws) -> dict[str, set[tuple[str, str]]]:
    """Open a Neo4j session via Databricks Secrets; return REFERENCES edges
    bucketed by their `source` property (`'declared'`, `'inferred_metadata'`,
    `'inferred_semantic'`, ...).
    """
    import base64

    from neo4j import GraphDatabase

    scope = os.environ.get("DATABRICKS_SECRET_SCOPE")
    if not scope:
        raise RuntimeError(
            "DATABRICKS_SECRET_SCOPE is not set; select an example overlay "
            "(e.g. --env-file examples/<name>/dbxcarta-overlay.env)."
        )

    def _secret(key: str) -> str:
        return base64.b64decode(ws.secrets.get_secret(scope=scope, key=key).value).decode()

    driver = GraphDatabase.driver(
        _secret("NEO4J_URI"),
        auth=(_secret("NEO4J_USERNAME"), _secret("NEO4J_PASSWORD")),
    )
    try:
        with driver.session() as s:
            rows = s.run(
                "MATCH (a:Column)-[r:REFERENCES]->(b:Column) "
                "RETURN a.id AS src, b.id AS dst, r.source AS source"
            ).data()
    finally:
        driver.close()

    buckets: dict[str, set[tuple[str, str]]] = {}
    for r in rows:
        buckets.setdefault(r["source"] or "unknown", set()).add((r["src"], r["dst"]))
    return buckets


def run_references_diff() -> dict:
    print("\n=== Fixture FK ↔ Neo4j REFERENCES diff ===")
    catalog = os.environ.get("DBXCARTA_CATALOG", "")
    if not catalog:
        return {"status": "fail", "error": "DBXCARTA_CATALOG not set"}

    expected_declared = _parse_fixture_fks(catalog)
    print(f"  Fixture-declared FKs: {len(expected_declared)}")

    try:
        buckets = _neo4j_references_by_source(_make_ws())
    except Exception as exc:
        return {"status": "fail", "error": f"Neo4j query failed: {exc}"}

    actual_declared = buckets.get("declared", set())
    inferred = {k: v for k, v in buckets.items() if k != "declared"}
    inferred_total = sum(len(v) for v in inferred.values())

    print(f"  Neo4j REFERENCES (declared): {len(actual_declared)}")
    for source, edges in sorted(inferred.items()):
        print(f"  Neo4j REFERENCES ({source}, informational): {len(edges)}")
        for src, dst in sorted(edges):
            print(f"    {src} -> {dst}")

    extra = sorted(actual_declared - expected_declared)
    missing = sorted(expected_declared - actual_declared)
    if extra:
        print(f"  EXTRA in Neo4j declared bucket ({len(extra)}):")
        for src, dst in extra:
            print(f"    {src} -> {dst}")
    if missing:
        print(f"  MISSING in Neo4j declared bucket ({len(missing)}):")
        for src, dst in missing:
            print(f"    {src} -> {dst}")

    result = {
        "expected_declared_count": len(expected_declared),
        "actual_declared_count": len(actual_declared),
        "inferred_count": inferred_total,
        "inferred_by_source": {k: len(v) for k, v in inferred.items()},
    }
    if extra or missing:
        return {
            **result,
            "status": "fail",
            "extra_declared": [list(e) for e in extra],
            "missing_declared": [list(m) for m in missing],
        }
    print("  Declared-bucket match: OK.")
    return {**result, "status": "pass"}


# ---------------------------------------------------------------------------
# Output JSON
# ---------------------------------------------------------------------------


def run_write_output(phases: dict, catalog: str) -> dict:
    print("\n=== Write Output JSON ===")
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    overall_phases = {k: v for k, v in phases.items() if k != "output"}
    overall = "pass" if all(p["status"] == "pass" for p in overall_phases.values()) else "fail"

    output: dict = {
        "autotest_run_at": _now_iso(),
        "catalog": catalog,
        "fixture_schemas": FIXTURE_SCHEMAS,
        "phases": phases,
        "overall": overall,
    }
    if overall == "fail":
        output["failed_phases"] = [k for k, v in overall_phases.items() if v["status"] != "pass"]

    summary_volume = os.environ.get("DBXCARTA_SUMMARY_VOLUME", "")
    if not summary_volume:
        print("  WARNING: DBXCARTA_SUMMARY_VOLUME not set — skipping volume write")
        return {"status": "pass", "written": False}

    ws = _make_ws()
    remote_path = f"{summary_volume}/autotest/autotest_results_{ts}.json"
    content = json.dumps(output, indent=2).encode()

    ws.files.upload(remote_path, io.BytesIO(content), overwrite=True)
    print(f"  Written: {remote_path}")

    local_dir = Path(__file__).parent.parent / "outputs"
    local_dir.mkdir(exist_ok=True)
    local_file = local_dir / f"autotest_results_{ts}.json"
    local_file.write_bytes(content)
    print(f"  Local:   {local_file}")
    return {"status": "pass", "path": remote_path, "local_path": str(local_file)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _abort(phases: dict) -> None:
    failed = [k for k, v in phases.items() if v["status"] != "pass"]
    print(f"\nAborted — failed steps: {failed}")
    sys.exit(1)


def main() -> None:
    phases: dict[str, dict] = {}

    phases["preflight"] = run_preflight()
    if phases["preflight"]["status"] != "pass":
        _abort(phases)

    phases["unit_tests"] = run_unit_tests()
    if phases["unit_tests"]["status"] != "pass":
        _abort(phases)

    phases["schema_setup"] = run_schema_setup()
    if phases["schema_setup"]["status"] != "pass":
        _abort(phases)

    ingest = run_ingest()
    run_summary = ingest.pop("run_summary", {})
    phases["ingest_run"] = ingest
    if ingest["status"] != "pass":
        _abort(phases)

    phases["ingest_run"]["run_summary"] = run_summary
    phases["assertions"] = run_assertions(run_summary)
    phases["references_diff"] = run_references_diff()

    phases["output"] = run_write_output(phases, os.environ.get("DBXCARTA_CATALOG", ""))

    overall = "pass" if all(p["status"] == "pass" for p in phases.values()) else "fail"
    print(f"\n{'=' * 50}")
    print(f"Overall: {overall.upper()}")
    for name, result in phases.items():
        print(f"  {name}: {result['status']}")

    sys.exit(0 if overall == "pass" else 1)


if __name__ == "__main__":
    main()
