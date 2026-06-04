"""The curated bootstrap closures must exclude DBR-provided packages.

The closures are installed by the runner bootstrap with ``--no-deps``
into the shared driver environment. Reinstalling a package the
Databricks Runtime already provides (the Spark runtime, or the
DBR-managed SDK and its auth subtree) would shadow the platform copy, so
the closures are hand-curated to omit them. This guards that policy as
the dependency pins change.
"""

from __future__ import annotations

import pytest
from dbxcarta.submit import cli


def _package_names(closure: tuple[str, ...]) -> set[str]:
    return {spec.split("==", 1)[0].lower() for spec in closure}


@pytest.mark.parametrize(
    "closure",
    [cli._INGEST_PINNED_CLOSURE, cli._CLIENT_PINNED_CLOSURE],
    ids=["ingest", "client"],
)
def test_closure_excludes_dbr_provided_packages(closure: tuple[str, ...]) -> None:
    names = _package_names(closure)
    overlap = names & {p.lower() for p in cli._DBR_PROVIDED_PACKAGES}
    assert not overlap, f"closure must not reinstall DBR-provided packages: {overlap}"
    # Spell out the runtime explicitly so a future edit that adds pyspark
    # back fails loudly rather than silently shipping it.
    assert "pyspark" not in names
    assert "py4j" not in names
    assert "databricks-sdk" not in names


def test_closures_are_fully_pinned() -> None:
    for closure in (cli._INGEST_PINNED_CLOSURE, cli._CLIENT_PINNED_CLOSURE):
        for spec in closure:
            assert "==" in spec, f"closure entry not exact-pinned: {spec!r}"
