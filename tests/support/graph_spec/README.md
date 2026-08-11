# Vendored Neo4j Graph Spec schema

`spec.v1.json` is copied verbatim from the upstream **`neo4j/import-spec`** repository:

| | |
|---|---|
| Source | `core/src/main/resources/spec.v1.json` |
| URL | <https://raw.githubusercontent.com/neo4j/import-spec/v1.0.0-rc21/core/src/main/resources/spec.v1.json> |
| Tag | **`v1.0.0-rc21`** (released 2026-07-29) |
| Maven artifact | `org.neo4j.importer:import-spec` |
| SHA-256 | `d0cf4ca989435a2e450f1fb754b39b8eb43e89baf377077e6dc4e6eb3daa3151` |

## Why it is vendored

The S1.6 (#297) mapping-mechanism verdict turns on what the Graph Spec format *can express*.
That is a property of the schema, so `tests/unit/etl/test_graph_spec_ceiling.py` asserts it
directly. Vendoring at a fixed tag is what makes the verdict **reproducible and
re-checkable** rather than a claim about a moving target.

This also closes the gap S1.5 had to declare open: `docs/refactor/field-vocabulary.md` notes
that `neo4j-pe-refs/README.md` — the external field-naming reference the ticket cites — is
not vendored, so its alignment claim was structural rather than name-level. The normative
artifact is the schema, and that *is* now in the tree.

## What it is not

- **Not a dependency.** Nothing under `neocarta/` imports this package. There is no runtime
  Graph Spec dependency and no JVM anywhere in the ingest path.
- **Not a contract we track continuously.** Upstream is an RC (rc01 … rc21, no GA), so
  GUIDE §6 applies: *"adapt behind our boundary, don't block on it."*

## Upgrading the pin

The ceiling tests are deliberately written to **fail** if a newer RC widens the format —
that failure is the D13 signal that the verdict deserves a fresh look. To re-pin:

```bash
TAG=v1.0.0-rcNN
curl -sSL "https://raw.githubusercontent.com/neo4j/import-spec/$TAG/core/src/main/resources/spec.v1.json" \
  -o tests/support/graph_spec/spec.v1.json
shasum -a 256 tests/support/graph_spec/spec.v1.json
```

Then update `SPEC_VERSION` in `__init__.py`, the table above, and — if a ceiling test now
fails — `docs/refactor/mapping-mechanism.md`, because the verdict's premise has changed.
