from __future__ import annotations

import ast
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _loaded_modules_after(import_statement: str) -> set[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"{import_statement}; import sys; print('\\n'.join(sorted(sys.modules)))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def _matching_modules(loaded: set[str], forbidden: set[str]) -> set[str]:
    return {
        module
        for module in loaded
        for prefix in forbidden
        if module == prefix or module.startswith(f"{prefix}.")
    }


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _layer_source_files(layer: str) -> list[Path]:
    package_root = _REPO_ROOT / "packages" / f"dbxcarta-{layer}" / "src" / "dbxcarta" / layer
    return sorted(package_root.rglob("*.py"))


def _matches_forbidden(module: str, forbidden: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden)


def _requirement_names(distribution: str) -> set[str]:
    """Return the bare package names from a distribution's Requires-Dist.

    Each requirement string carries version specifiers, extras, and
    environment markers (e.g. ``"neo4j>=5.0 ; extra == 'graph'"``); only
    the leading name token identifies the dependency.
    """
    requires = metadata.requires(distribution) or []
    return {re.split(r"[<>=!~;\[ ]", spec, maxsplit=1)[0].lower() for spec in requires}


def test_top_level_namespace_has_no_compatibility_reexports() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import dbxcarta; "
            "print(dbxcarta.__file__); "
            "print(hasattr(dbxcarta, 'run_dbxcarta')); "
            "print(hasattr(dbxcarta, 'Settings')); "
            "print(hasattr(dbxcarta, 'run_client'))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    file_value, has_run, has_settings, has_client = result.stdout.splitlines()
    assert file_value == "None"
    assert has_run == "False"
    assert has_settings == "False"
    assert has_client == "False"


def test_core_root_does_not_load_upstream_or_heavy_deps() -> None:
    # dbxcarta.core is the bottom layer: importing it must pull in neither the
    # spark nor client layers, nor the heavy Spark/Neo4j runtimes core exists
    # to keep out of the light packages.
    forbidden = {
        "dbxcarta.spark",
        "dbxcarta.client",
        "pyspark",
        "neo4j",
    }

    leaked = _matching_modules(_loaded_modules_after("import dbxcarta.core"), forbidden)

    assert not leaked, f"Forbidden modules loaded by dbxcarta.core: {sorted(leaked)}"


def test_client_root_does_not_load_spark_modules() -> None:
    forbidden = {
        "dbxcarta.spark",
        "delta",
        "py4j",
        "pyspark",
    }

    leaked = _matching_modules(_loaded_modules_after("import dbxcarta.client"), forbidden)

    assert not leaked, f"Forbidden modules loaded by dbxcarta.client: {sorted(leaked)}"


def test_spark_root_does_not_load_client_eval() -> None:
    # dbxcarta.spark must never reach into the client layer: the eval client
    # is a downstream consumer, so a top-level import of dbxcarta.spark
    # should not pull any dbxcarta.client module into sys.modules.
    forbidden = {
        "dbxcarta.client",
    }

    leaked = _matching_modules(_loaded_modules_after("import dbxcarta.spark"), forbidden)

    assert not leaked, f"Forbidden modules loaded by dbxcarta.spark: {sorted(leaked)}"


def test_materialize_root_does_not_load_sibling_layers_or_neo4j() -> None:
    # dbxcarta.materialize is a sibling of spark and client over core. It owns
    # the Spark shell, so pyspark is a legitimate dependency, but it must never
    # reach into either sibling layer or pull in Neo4j.
    forbidden = {
        "dbxcarta.spark",
        "dbxcarta.client",
        "neo4j",
    }

    leaked = _matching_modules(_loaded_modules_after("import dbxcarta.materialize"), forbidden)

    assert not leaked, f"Forbidden modules loaded by dbxcarta.materialize: {sorted(leaked)}"


@pytest.mark.parametrize("layer", ["core", "spark", "client", "materialize"])
def test_layer_root_does_not_load_job_runner(layer: str) -> None:
    # The job runner is the dependency the whole split exists to keep out
    # of the core and client closures. Importing either layer must not
    # pull it into sys.modules; only dbxcarta-submit may touch it.
    leaked = _matching_modules(
        _loaded_modules_after(f"import dbxcarta.{layer}"),
        {"databricks_job_runner"},
    )

    assert not leaked, f"dbxcarta.{layer} loaded the job runner: {sorted(leaked)}"


@pytest.mark.parametrize(
    "distribution",
    ["dbxcarta-core", "dbxcarta-spark", "dbxcarta-client", "dbxcarta-materialize"],
)
def test_distribution_does_not_require_job_runner(distribution: str) -> None:
    # A module-load check alone would miss a re-declared dependency that
    # is simply never imported at module top level. Guard the published
    # metadata too, so the runner cannot creep back into the closure.
    assert "databricks-job-runner" not in _requirement_names(distribution)


def test_source_imports_preserve_layer_boundaries() -> None:
    forbidden_by_layer: dict[str, tuple[str, ...]] = {
        "client": ("dbxcarta.spark",),
        "core": ("dbxcarta.spark", "dbxcarta.client"),
        "materialize": ("dbxcarta.spark", "dbxcarta.client"),
        "spark": ("dbxcarta.client",),
    }
    violations: list[str] = []

    for layer, forbidden in forbidden_by_layer.items():
        for path in _layer_source_files(layer):
            for module in sorted(_imported_modules(path)):
                if _matches_forbidden(module, forbidden):
                    rel = path.relative_to(_REPO_ROOT)
                    violations.append(f"{rel}: imports {module}")

    assert not violations, "Forbidden cross-layer imports:\n" + "\n".join(violations)
