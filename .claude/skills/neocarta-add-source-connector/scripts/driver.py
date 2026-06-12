#!/usr/bin/env python
"""Scaffold and verify neocarta source/format connectors against the contract.

The connector contract lives in this skill's ``connector-contract.md`` and is
made executable by ``neocarta/connectors/_base.py`` (the runtime-checkable
``SourceConnectorProtocol`` / ``FormatConnectorProtocol``) plus the per-connector
``test_conformance.py`` files. This driver is the agent-facing handle on that
contract:

    scaffold  — generate a conformant connector package + conformance test
    verify    — statically check an existing connector against the contract
    list      — list connector packages and their detected kind

Run it through the managed environment, e.g.::

    uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py list
    uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py scaffold salesforce
    uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py verify salesforce

``<pkg>`` is a path under ``neocarta/connectors/`` — ``salesforce`` for a flat
single-data-type source, ``salesforce/schema`` for a data-type sub-connector.
"""

from __future__ import annotations

import argparse
import importlib
import pathlib
import re
import subprocess
import sys

from neocarta.connectors._base import FormatConnectorProtocol, SourceConnectorProtocol

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
CONNECTORS_DIR = REPO_ROOT / "neocarta" / "connectors"
TESTS_DIR = REPO_ROOT / "tests" / "unit" / "connectors"

# Packages that are infra, not connectors.
SKIP_DIRS = {"utils", "__pycache__"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _pkg_to_dotted(pkg: str) -> str:
    """Turn a slash path under connectors/ into a dotted module path."""
    return "neocarta.connectors." + pkg.strip("/").replace("/", ".")


def _class_name_from_pkg(pkg: str) -> str:
    """Derive a default ``FooConnector`` class name from a package path."""
    parts = [p for p in re.split(r"[/_]", pkg.strip("/")) if p]
    return "".join(p.capitalize() for p in parts) + "Connector"


def _module_id_from_pkg(pkg: str) -> str:
    """Human-friendly id used in log lines, e.g. ``salesforce schema``."""
    return pkg.strip("/").replace("/", " ").replace("_", " ")


def _relative_import_dots(pkg: str) -> str:
    """Number of leading dots to reach ``neocarta`` from inside the package."""
    depth = len([p for p in pkg.strip("/").split("/") if p])
    # connector.py sits at depth 1 (flat) or 2 (sub-connector) below connectors/;
    # connectors/ is itself two below neocarta/  -> dots = depth + 2
    return "." * (depth + 2)


# --------------------------------------------------------------------------- #
# scaffold
# --------------------------------------------------------------------------- #
def _connector_py(pkg: str, class_name: str, is_format: bool) -> str:
    dots = _relative_import_dots(pkg)
    mid = _module_id_from_pkg(pkg)
    export_method = ""
    if is_format:
        export_method = '''
    def export(self, output_path: str) -> None:
        """Read entities from Neo4j and write them out in this format.

        Export is a single public orchestrator; its internal stages
        (graph read, source-format build, file write) stay private.
        """
        raise NotImplementedError(f"TODO: write {type(self).__name__} output to {output_path}")
'''
    return f'''"""{class_name} connector."""

import logging
import warnings

from neo4j import Driver

from {dots}_logging import log_transform_counts
from {dots}errors import StateError
from {dots}ingest.rdbms import Neo4jRDBMSLoader
from .extract import {class_name[:-9]}Extractor
from .transform import {class_name[:-9]}Transformer

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
# log_transform_counts skips zero-count types, so an unfilled tuple stays quiet.
# TODO: add a pair per produced node / relationship list — e.g. a "tables" label
# for the "table_nodes" attribute; see csv/connector.py for a full example.
_TRANSFORM_COUNTS: tuple[tuple[str, str], ...] = ()


class {class_name}:
    """
    Connector for loading {mid} metadata into Neo4j.

    Follows an Extract → Transform → Load pipeline. :meth:`ingest` runs all
    three stages and records the neocarta graph metadata node at the end.

    Parameters
    ----------
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    """

    def __init__(self, neo4j_driver: Driver, database_name: str = "neo4j") -> None:
        """Initialize the {mid} connector."""
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = {class_name[:-9]}Extractor()
        self.transformer = {class_name[:-9]}Transformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def extract(self, source: str | None = None) -> None:
        """
        Read from the external system and populate the extractor cache.

        Each call replaces any previously cached extract state.

        Parameters
        ----------
        source : str, optional
            Source-specific input (e.g. a dataset id, file path, API handle).
        """
        self._extracted = False
        self._transformed = False
        self.extractor.extract(source)
        self._extracted = True

    def transform(self) -> None:
        """
        Convert cached extract state into graph data model objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "{class_name}.transform() called before extract(); call .extract() first.",
                suggestion="Call connector.extract(...) before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming {mid} metadata...")
        # TODO: drive self.transformer here, reading self.extractor.* caches.
        log_transform_counts(logger, self.transformer, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Write transformed objects into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "{class_name}.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        logger.info("Loading {mid} metadata into Neo4j...")
        # TODO: self.loader.load_*_nodes(self.transformer.*_nodes, ...)
        # The loader logs each write by its graph pattern + merge counts itself,
        # so don't re-log per-type counts here.

    def ingest(self, source: str | None = None) -> None:
        """
        Run the {mid} connector (extract → transform → load).

        Parameters
        ----------
        source : str, optional
            Source-specific input forwarded to :meth:`extract`.
        """
        # Extract-phase progress is logged by @log_stage on the extractor's
        # methods; transform() and load() emit their own phase lines.
        self.extract(source)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("{class_name} completed successfully")
{export_method}
    def run(self, source: str | None = None) -> None:
        """
        Run the {mid} connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "{class_name}.run() is deprecated; use {class_name}.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(source)
'''


def _extract_py(pkg: str, class_name: str) -> str:
    base = class_name[:-9]
    dots = _relative_import_dots(pkg)
    return f'''"""{base} extractor."""

from {dots}_logging import log_stage


class {base}Extractor:
    """Extractor for {base.lower()} metadata.

    Internal cached state is *not* part of the public API — callers interact
    only through the connector's stage methods. Expose extract results as
    read-only properties that :class:`{base}Transformer` consumes.
    """

    def __init__(self) -> None:
        """Initialize an empty extractor cache."""
        self._cache: dict = {{}}

    @log_stage
    def extract(self, source: str | None = None) -> None:
        """Read from the source and populate ``self._cache``.

        ``@log_stage`` logs a one-line INFO summary (target + row count +
        elapsed) for this call; it derives its logger from this module, never
        logs SQL or row values, and surfaces only allowlisted scalar kwargs as
        the target. TODO: replace this stub with concrete ``extract_*_info(...)``
        methods — decorate each with ``@log_stage`` — that populate
        ``self._cache``, plus ``@property`` accessors (``table_info``,
        ``column_info``, ...) for the transformer to read.
        """
        raise NotImplementedError(f"{{type(self).__name__}}.extract() not implemented for {{source!r}}")
'''


def _transform_py(pkg: str, class_name: str) -> str:
    base = class_name[:-9]
    dots = _relative_import_dots(pkg)
    return f'''"""Transform {base.lower()} data into graph nodes and relationships."""

from {dots}connectors.models import NodesCache, RelationshipsCache

# All node ids MUST be produced via helpers in
# neocarta.connectors.utils.generate_id — never inline an id f-string.


class {base}Transformer:
    """Transformer for {base.lower()} metadata."""

    def __init__(self) -> None:
        """Initialize the {base.lower()} transformer."""
        self._node_cache: NodesCache = NodesCache()
        self._relationships_cache: RelationshipsCache = RelationshipsCache()

    # TODO: add transform_to_*_nodes / transform_to_*_relationships methods
    # that read the extractor caches and build data_model objects, plus
    # @property accessors (table_nodes, ...) for the loader to read.
'''


def _init_py(class_name: str) -> str:
    return f'''"""{class_name} package."""

from .connector import {class_name}

__all__ = ["{class_name}"]
'''


def _readme_md(pkg: str, class_name: str, is_format: bool) -> str:
    kind = "format (ingest + export)" if is_format else "source (ingest only)"
    dotted = _pkg_to_dotted(pkg)
    return f"""# {class_name.replace("Connector", "")} Connector

## Overview

One paragraph: what source/format this reads, what entity types land in Neo4j,
and any attribution.

## Connector type

{kind}.

## Data model

```mermaid
graph LR
%% TODO: nodes + relationships this connector produces, with properties and KEY markers.
```

## Usage

```python
import os
from neo4j import GraphDatabase
from {dotted} import {class_name}

neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)

connector = {class_name}(neo4j_driver=neo4j_driver)
connector.ingest(source=...)  # TODO: real source argument
```

### Environment variables

- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` — Neo4j connection.
- TODO: source-specific auth variables, if any.

### Filtering options

TODO: which `NodeLabel` / `RelationshipType` values apply, once filtering is added.

## Known issues / limitations

TODO.
"""


def _conformance_test(pkg: str, class_name: str, is_format: bool) -> str:
    dotted = _pkg_to_dotted(pkg)
    proto = "FormatConnectorProtocol" if is_format else "SourceConnectorProtocol"
    proto_import = (
        "from neocarta.connectors._base import FormatConnectorProtocol"
        if is_format
        else "from neocarta.connectors._base import SourceConnectorProtocol"
    )
    methods = (
        '("extract", "transform", "load", "ingest", "export", "run")'
        if is_format
        else '("extract", "transform", "load", "ingest", "run")'
    )
    kind_assert = (
        "test_conforms_to_format_connector_protocol"
        if is_format
        else "test_conforms_to_source_connector_protocol"
    )
    run_args = '"out.file"' if is_format else ""
    return f'''"""Conformance tests for {class_name}.

Asserts conformance with the public connector standard defined in
``.claude/skills/neocarta-add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.
"""

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

{proto_import}
from {dotted} import {class_name}
from neocarta.errors import StateError

PACKAGE = "{dotted}"


def _make_connector() -> {class_name}:
    """Construct a {class_name} with mocked external dependencies."""
    return {class_name}(neo4j_driver=MagicMock())


def {kind_assert}():
    """{class_name} conforms to the {proto}."""
    assert isinstance(_make_connector(), {proto})


def test_has_public_stage_methods():
    """The standard public API exists."""
    for name in {methods}:
        assert callable(getattr({class_name}, name)), f"missing public method: {{name}}"


def test_run_emits_deprecation_warning():
    """run() must emit DeprecationWarning and delegate to ingest()."""
    connector = _make_connector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run({run_args})
    connector.ingest.assert_called_once()


def test_readme_present():
    """Every connector ships a README.md at its package root."""
    module = importlib.import_module(PACKAGE)
    package_dir = pathlib.Path(module.__file__).parent
    assert (package_dir / "README.md").exists()


def test_init_exports_are_minimal():
    """__init__.py exports only the connector class (no Extractor/Transformer/Loader)."""
    module = importlib.import_module(PACKAGE)
    exported = getattr(module, "__all__", None)
    assert exported is not None, "__init__.py must define __all__"
    for name in exported:
        assert not name.endswith(("Extractor", "Transformer", "Loader")), (
            f"{{name}} should not be re-exported from {{PACKAGE}}.__init__.py"
        )


def test_transform_before_extract_raises_state_error():
    """Calling transform() without a prior extract() raises StateError."""
    connector = _make_connector()
    with pytest.raises(StateError):
        connector.transform()


def test_load_before_transform_raises_state_error():
    """Calling load() without a prior transform() raises StateError."""
    connector = _make_connector()
    with pytest.raises(StateError):
        connector.load()
'''


def cmd_scaffold(args: argparse.Namespace) -> int:
    """Generate a conformant connector package and its conformance test."""
    pkg = args.pkg.strip("/")
    class_name = args.class_name or _class_name_from_pkg(pkg)
    if not class_name.endswith("Connector"):
        class_name += "Connector"
    is_format = args.format

    pkg_dir = CONNECTORS_DIR / pkg
    if pkg_dir.exists() and any(pkg_dir.iterdir()) and not args.force:
        print(f"ERROR: {pkg_dir} already exists and is non-empty. Use --force to overwrite.")
        return 1
    pkg_dir.mkdir(parents=True, exist_ok=True)

    files = {
        pkg_dir / "__init__.py": _init_py(class_name),
        pkg_dir / "connector.py": _connector_py(pkg, class_name, is_format),
        pkg_dir / "extract.py": _extract_py(pkg, class_name),
        pkg_dir / "transform.py": _transform_py(pkg, class_name),
        pkg_dir / "README.md": _readme_md(pkg, class_name, is_format),
    }
    for path, content in files.items():
        path.write_text(content)
        print(f"  wrote {path.relative_to(REPO_ROOT)}")

    # parent __init__.py for sub-connectors needs to re-export
    if "/" in pkg:
        parent = pkg_dir.parent
        parent_init = parent / "__init__.py"
        if not parent_init.exists():
            parent_init.write_text(f'"""{parent.name} connectors."""\n')
            print(f"  wrote {parent_init.relative_to(REPO_ROOT)} (stub — add re-exports)")

    test_dir = TESTS_DIR / pkg
    test_dir.mkdir(parents=True, exist_ok=True)
    init_f = test_dir / "__init__.py"
    if not init_f.exists():
        init_f.write_text("")
    test_f = test_dir / "test_conformance.py"
    test_f.write_text(_conformance_test(pkg, class_name, is_format))
    print(f"  wrote {test_f.relative_to(REPO_ROOT)}")

    print(
        f"\nScaffolded {class_name} ({'format' if is_format else 'source'}) at {pkg_dir.relative_to(REPO_ROOT)}"
    )
    print(
        f"Next: implement the TODOs, then run:\n  uv run {pathlib.Path(__file__).relative_to(REPO_ROOT)} verify {pkg}"
    )
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
ID_FSTRING_RE = re.compile(r"""_id\s*=\s*f["']|["']id["']\s*:\s*f["']|\bid=f["']""")
# Bare print( call — not pprint(, blueprint(, or console.print( (lookbehind rules
# out a preceding word char or dot). Connectors report progress via the module
# logger, never print() (contract §16).
PRINT_RE = re.compile(r"(?<![\w.])print\s*\(")


def cmd_verify(args: argparse.Namespace) -> int:
    """Check an existing connector against the contract; return a process exit code."""
    pkg = args.pkg.strip("/")
    dotted = _pkg_to_dotted(pkg)
    pkg_dir = CONNECTORS_DIR / pkg
    failures: list[str] = []
    warns: list[str] = []

    print(f"== verifying {dotted} ==")

    # 1. imports
    try:
        module = importlib.import_module(dotted)
    except Exception as exc:
        print(f"FAIL: cannot import {dotted}: {type(exc).__name__}: {exc}")
        return 1

    # 2. __all__ minimal + present
    exported = getattr(module, "__all__", None)
    if exported is None:
        failures.append("__init__.py must define __all__")
        exported = []
    for name in exported:
        if name.endswith(("Extractor", "Transformer", "Loader")):
            failures.append(f"{name} should not be re-exported from __init__.py")

    # 3. README at package root
    if not (pkg_dir / "README.md").exists():
        failures.append("missing README.md at package root")

    # 4. connector classes conform structurally
    connector_classes = [
        getattr(module, n)
        for n in exported
        if isinstance(getattr(module, n, None), type) and n.endswith("Connector")
    ]
    if not connector_classes:
        failures.append("no *Connector class exported in __all__")
    for cls in connector_classes:
        if issubclass(cls, FormatConnectorProtocol):
            kind = "format"
        elif issubclass(cls, SourceConnectorProtocol):
            kind = "source"
        else:
            missing = [
                m
                for m in ("extract", "transform", "load", "ingest", "run")
                if not callable(getattr(cls, m, None))
            ]
            failures.append(
                f"{cls.__name__} does not satisfy any connector protocol; missing: {missing}"
            )
            continue
        print(f"  {cls.__name__}: {kind} connector (protocol OK)")

    # 5. static line scans — inline f-string ids and stray print()
    for py in sorted(pkg_dir.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        for i, line in enumerate(py.read_text().splitlines(), 1):
            if ID_FSTRING_RE.search(line):
                warns.append(
                    f"{py.relative_to(REPO_ROOT)}:{i}: looks like an inline id f-string — "
                    "route ids through connectors/utils/generate_id.py"
                )
            if not line.lstrip().startswith("#") and PRINT_RE.search(line):
                warns.append(
                    f"{py.relative_to(REPO_ROOT)}:{i}: uses print() — report progress through "
                    "the module logger (logging.getLogger(__name__)); see contract §16"
                )

    # 6. report static results
    for w in warns:
        print(f"  WARN: {w}")
    for f in failures:
        print(f"  FAIL: {f}")

    # 7. run conformance pytest if present
    test_dir = TESTS_DIR / pkg
    test_file = test_dir / "test_conformance.py"
    pytest_rc = 0
    if test_file.exists():
        print(f"\n== running {test_file.relative_to(REPO_ROOT)} ==")
        # Fixed argv (uv on PATH), no shell, no untrusted input — agent tooling.
        pytest_rc = subprocess.run(  # noqa: S603
            ["uv", "run", "pytest", str(test_file), "-q"],  # noqa: S607
            cwd=REPO_ROOT,
            check=False,
        ).returncode
    else:
        warns.append(f"no conformance test at {test_file.relative_to(REPO_ROOT)}")
        print(f"  WARN: no conformance test at {test_file.relative_to(REPO_ROOT)}")

    ok = not failures and pytest_rc == 0
    print(
        f"\n{'PASS' if ok else 'FAIL'}: {dotted}" + (f" ({len(warns)} warning(s))" if warns else "")
    )
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #
def cmd_list(args: argparse.Namespace) -> int:
    """List connector packages and their detected kind (source/format)."""
    for entry in sorted(CONNECTORS_DIR.iterdir()):
        if not entry.is_dir() or entry.name in SKIP_DIRS:
            continue
        # a package is a "connector root" if it has an __init__ exporting *Connector
        dotted = f"neocarta.connectors.{entry.name}"
        try:
            module = importlib.import_module(dotted)
            exported = getattr(module, "__all__", []) or []
            classes = [
                getattr(module, n) for n in exported if isinstance(getattr(module, n, None), type)
            ]
            kinds = []
            for cls in classes:
                if issubclass(cls, FormatConnectorProtocol):
                    kinds.append(f"{cls.__name__} [format]")
                elif issubclass(cls, SourceConnectorProtocol):
                    kinds.append(f"{cls.__name__} [source]")
                else:
                    kinds.append(f"{cls.__name__} [?]")
            print(f"{entry.name:14} {', '.join(kinds) if kinds else '(no exported connector)'}")
        except Exception as exc:
            print(f"{entry.name:14} (import error: {type(exc).__name__})")
    return 0


def main() -> int:
    """Parse argv and dispatch to the chosen subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scaffold = sub.add_parser("scaffold", help="generate a conformant connector package")
    p_scaffold.add_argument(
        "pkg", help="path under neocarta/connectors/ (e.g. salesforce or salesforce/schema)"
    )
    p_scaffold.add_argument("--class-name", help="connector class name (default derived from pkg)")
    p_scaffold.add_argument(
        "--format", action="store_true", help="scaffold a format connector (ingest + export)"
    )
    p_scaffold.add_argument(
        "--force", action="store_true", help="overwrite a non-empty package dir"
    )
    p_scaffold.set_defaults(func=cmd_scaffold)

    p_verify = sub.add_parser("verify", help="check an existing connector against the contract")
    p_verify.add_argument(
        "pkg", help="path under neocarta/connectors/ (e.g. query_log or bigquery/schema)"
    )
    p_verify.set_defaults(func=cmd_verify)

    p_list = sub.add_parser("list", help="list connector packages and detected kind")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
