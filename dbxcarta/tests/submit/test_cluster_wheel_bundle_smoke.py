"""Smoke test: the bundled entrypoint wheels physically carry dbxcarta/core.

The runner bootstrap installs a single application wheel with ``--no-deps`` and
has no slot for a separate ``dbxcarta-core`` wheel, so each entrypoint package
(spark, client, materialize) must ship ``dbxcarta/core`` inside its own wheel.
``dbxcarta-submit publish-wheels`` arranges this by copying the core source into
each entrypoint package for the build (``_core_bundled_into``). This test builds
those wheels exactly the way publish-wheels does and asserts each one contains
both ``dbxcarta/core/`` and its own entrypoint module.

It guards the path logic across the move into neocarta: the package dirs now sit
directly under the dbxcarta directory root (no ``packages/`` layer), and a stale
path would leave the wheels missing core and only surface as an ImportError on
the cluster. The build needs ``uv`` on PATH but no live credentials, so it is
kept out of the fast lane and run via ``make dbxcarta-test-wheel``.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from dbxcarta.submit import cli

# Package dir name -> the entrypoint module dir that must appear alongside core.
_ENTRYPOINT_MODULE = {
    "dbxcarta-spark": "dbxcarta/spark/",
    "dbxcarta-client": "dbxcarta/client/",
    "dbxcarta-materialize": "dbxcarta/materialize/",
}

# The dbxcarta directory root: tests/submit/<file> -> tests -> dbxcarta root.
_DBXCARTA_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to build wheels")
def test_bundled_entrypoint_wheels_carry_core(tmp_path: Path) -> None:
    # The set of packages publish-wheels bundles core into must match the set
    # we know how to assert on, so a newly added entrypoint can't slip through.
    assert set(cli._CORE_BUNDLE_PACKAGES) == set(_ENTRYPOINT_MODULE)

    # Bundle core into every entrypoint package exactly as publish-wheels does,
    # then build each wheel and assert it carries both core and its own module.
    with cli._core_bundled_into(_DBXCARTA_ROOT):
        for package, module_prefix in _ENTRYPOINT_MODULE.items():
            subprocess.run(
                [
                    "uv",
                    "build",
                    "--wheel",
                    "--quiet",
                    "--package",
                    package,
                    "--out-dir",
                    str(tmp_path),
                ],
                cwd=_DBXCARTA_ROOT,
                check=True,
            )
            wheels = list(tmp_path.glob(f"{package.replace('-', '_')}-*.whl"))
            assert wheels, f"no wheel built for {package}"
            built = max(wheels, key=lambda p: p.stat().st_mtime)
            with zipfile.ZipFile(built) as zf:
                names = zf.namelist()
            assert any(n.startswith("dbxcarta/core/") for n in names), (
                f"{built.name} does not bundle dbxcarta/core"
            )
            assert any(n.startswith(module_prefix) for n in names), (
                f"{built.name} is missing its own {module_prefix} module"
            )

    # The context manager must leave the working tree clean: no copied core
    # under any entrypoint package after the build.
    for package in cli._CORE_BUNDLE_PACKAGES:
        leftover = _DBXCARTA_ROOT / package / "src" / "dbxcarta" / "core"
        assert not leftover.exists(), f"core copy left behind in {package}"
