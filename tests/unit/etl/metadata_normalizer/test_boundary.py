"""Architectural boundaries around the normalizer, asserted instead of described.

Two claims the repo has been making in prose since S1.6, in four files each, with nothing that
would fail if they stopped being true:

1. **Graph Spec has zero runtime dependency.** S1.6 (#297) rejected it as both the mapping
   mechanism and the normalization standard, retaining it only as a possible *emit-only* ontology
   expression that is deliberately not built yet. That is the whole of #298's "boundary isolates
   Graph Spec" criterion: there is no adapter to write, because there is nothing to adapt — so
   what has to be guarded is the *absence*.
2. **``normalized_schema/`` names no frame library.** The shared contract is the lowest-common
   ancestor model package (GUIDE §4 Model-Placement), and the pandas adapter is a sibling of the
   binder one level above it.

Both are checked over the **source**, with ``ast``, not over ``sys.modules``. A runtime check
would be wrong for two separate reasons: it would false-positive on the prose mentions of Graph
Spec in docstrings under ``neocarta/``, and — measurably — importing ``normalized_schema`` *does* pull pandas
today, transitively, because ``data_model/_validators.py`` imports ``isna`` to power the very
coercions the contract is built on. The architectural rule is about what a package *names*, which
is what an author controls and a reviewer reads.
"""

import ast
from pathlib import Path

import pytest

import neocarta

REPO_ROOT = Path(neocarta.__file__).parents[1]
PACKAGE = Path(neocarta.__file__).parent
NORMALIZED_SCHEMA = PACKAGE / "etl" / "metadata_normalizer" / "normalized_schema"
METADATA_NORMALIZER = PACKAGE / "etl" / "metadata_normalizer"

#: Any spelling of the import-spec artifact, plus the SPI a "Graph Spec as the mechanism" design
#: would have had to adopt.
GRAPH_SPEC_TOKENS = (
    "graph_spec",
    "import_spec",
    "importspec",
    "sourceprovider",
    "entitytargetextensionprovider",
)

FRAME_LIBRARIES = ("pandas", "numpy")


def _python_files(root):
    if not root.is_dir():
        pytest.skip("sources not available (installed distribution)")
    return sorted(root.rglob("*.py"))


def _imported_modules(path):
    """Every module name a file imports, from its AST rather than from its text.

    An ``ImportFrom`` contributes **both** its module path and the names it binds, because
    ``from tests.support import graph_spec`` reaches the same package as
    ``from tests.support.graph_spec import x`` while its ``node.module`` is only
    ``tests.support`` — a guard reading the module path alone would wave it through.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def _top_level(module):
    return module.split(".")[0]


class TestGraphSpecHasNoRuntimeDependency:
    """The S1.6 verdict, made checkable."""

    def test_no_production_module_imports_anything_graph_spec(self):
        offenders = []
        for path in _python_files(PACKAGE):
            for module in _imported_modules(path):
                lowered = module.lower()
                if any(token in lowered for token in GRAPH_SPEC_TOKENS):
                    offenders.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
        assert not offenders, (
            "Graph Spec is an emit-only ontology format with zero runtime dependency "
            f"(mapping-mechanism.md §3). Found: {offenders}"
        )

    def test_the_vendored_schema_is_test_support_only(self):
        """It is evidence for the verdict, not a dependency of the product."""
        assert not (PACKAGE / "graph_spec").exists()
        assert (REPO_ROOT / "tests" / "support" / "graph_spec" / "spec.v1.json").is_file()

    @pytest.mark.parametrize(
        "violation",
        [
            "from tests.support.graph_spec import load_spec_schema",
            "import tests.support.graph_spec",
            "from tests.support import graph_spec",
            "from tests.support import graph_spec as gs",
            "from neocarta.ontology.import_spec import emit",
        ],
    )
    def test_the_absence_search_is_not_vacuous(self, tmp_path, violation):
        """A guard that cannot fire guards nothing — including on the alias-only spellings.

        ``from tests.support import graph_spec`` reaches the vendored schema just as directly as
        the dotted form, but its ``node.module`` is only ``tests.support``. Each spelling below
        must be caught.
        """
        offender = tmp_path / "offender.py"
        offender.write_text(violation, encoding="utf-8")
        modules = _imported_modules(offender)
        assert any(token in name.lower() for name in modules for token in GRAPH_SPEC_TOKENS)


class TestNormalizedSchemaNamesNoFrameLibrary:
    """GUIDE §4 Model-Placement: the shared contract stays expressible without pandas."""

    def test_the_contract_package_imports_no_frame_library(self):
        offenders = [
            f"{path.relative_to(REPO_ROOT)} imports {module}"
            for path in _python_files(NORMALIZED_SCHEMA)
            for module in _imported_modules(path)
            if _top_level(module) in FRAME_LIBRARIES
        ]
        assert not offenders, f"normalized_schema must stay frame-free. Found: {offenders}"

    def test_pandas_is_confined_to_the_adapter_module(self):
        """One owner for frame handling, so the binder can be written against the general shape."""
        importers = {
            path.name
            for path in _python_files(METADATA_NORMALIZER)
            for module in _imported_modules(path)
            if _top_level(module) in FRAME_LIBRARIES
        }
        assert importers == {"_frames.py"}
