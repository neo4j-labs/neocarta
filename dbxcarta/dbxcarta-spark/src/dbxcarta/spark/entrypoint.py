"""`python -m dbxcarta.spark.entrypoint` — Databricks job entrypoint.

Parses leading KEY=VALUE positional arguments into the environment, then runs
the ingest pipeline.
"""

from __future__ import annotations

from dbxcarta.core.env import inject_params
from dbxcarta.spark.run import run_dbxcarta


def main() -> None:
    inject_params()
    run_dbxcarta()


if __name__ == "__main__":
    main()
