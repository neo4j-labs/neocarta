# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "dbxcarta-submit>=1.1.0",
# ]
# ///
r"""Submit the finance-genie ingest job to Databricks with dbxcarta-submit.

Build the neocarta connector wheel first, following
``neocarta/connectors/databricks/README.md`` ("Build a wheel from source"). That
produces ``dist/neocarta-<version>-py3-none-any.whl``. Then run from the repo:

    uv run examples/databricks/submit_finance_genie.py

This uses ``dbxcarta-submit`` to stage that wheel on a UC Volume and submit the
ingest job. The job runs on the cluster and writes the finance-genie semantic
graph into Neo4j.

By default the newest ``dist/neocarta-*.whl`` is used; pass an explicit wheel
path as the first argument to override. Only ``dbxcarta-submit`` is a script
dependency: it is the submit tool. neocarta is not imported here, and the
cluster installs the connector from the staged wheel.

Configuration comes from ``submit_finance_genie.env`` beside this script (copy
the ``.sample`` and fill in the infra values). It is secret-free; the cluster
reads Neo4j credentials from the Databricks secret scope it names.

Prerequisites:
- A classic (non-serverless) cluster with the Neo4j Spark Connector attached.
- A reachable Neo4j instance and a provisioned Databricks secret scope holding
  its credentials (the scope named by ``NEOCARTA_DATABRICKS_SECRET_SCOPE``).
- Databricks auth for the profile named in the config.
- A built neocarta wheel (see above).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dbxcarta.submit import submit_neocarta_ingest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_ENV_FILE = _HERE / "submit_finance_genie.env"


def _resolve_neocarta_wheel(argv: list[str]) -> Path:
    """Return the neocarta wheel to submit: an explicit argument or newest in dist/."""
    if argv:
        wheel = Path(argv[0]).expanduser()
        if not wheel.is_file():
            raise SystemExit(f"neocarta wheel not found: {wheel}")
        return wheel
    wheels = sorted(
        (_REPO_ROOT / "dist").glob("neocarta-*.whl"),
        key=lambda p: p.stat().st_mtime,
    )
    if not wheels:
        raise SystemExit(
            f"no neocarta wheel found in {_REPO_ROOT / 'dist'}. Build it first, "
            "following neocarta/connectors/databricks/README.md "
            '("Build a wheel from source"), or pass a wheel path as the first argument.'
        )
    return wheels[-1]


def main() -> int:
    """Stage the prebuilt connector wheel and submit the ingest job."""
    if not _ENV_FILE.is_file():
        raise SystemExit(
            f"config not found: {_ENV_FILE}\n"
            "Copy submit_finance_genie.env.sample to submit_finance_genie.env "
            "and fill in the infra values."
        )

    # dbxcarta-submit resolves the config from DBXCARTA_ENV_FILE, exactly as the
    # `dbxcarta` CLI does. setdefault lets an already-exported value win.
    os.environ.setdefault("DBXCARTA_ENV_FILE", str(_ENV_FILE))

    wheel = _resolve_neocarta_wheel(sys.argv[1:])
    print(f"submitting neocarta wheel: {wheel}")
    # Stages the wheel and submits the ingest job on classic compute (its default).
    submit_neocarta_ingest(wheel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
