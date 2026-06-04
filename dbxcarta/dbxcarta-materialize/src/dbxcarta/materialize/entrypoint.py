"""`python -m dbxcarta.materialize.entrypoint` — Databricks job entrypoint.

Parses leading KEY=VALUE positional arguments into the environment, then runs
the materialize job that turns the staged blueprint into Delta tables.
"""

from __future__ import annotations

from dbxcarta.core.env import inject_params
from dbxcarta.materialize.run import run_materialize


def main() -> None:
    inject_params()
    run_materialize()


if __name__ == "__main__":
    main()
