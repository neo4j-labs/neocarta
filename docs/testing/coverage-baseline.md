# Coverage baseline

> **Purpose.** The refactor GUIDE's central safety invariant (§4) is *"No coverage / test-count
> regression — never drop a test or lower coverage."* That invariant is **relative** (a ratchet), so it
> needs a committed reference point to ratchet against. This document — together with the machine-readable
> [`coverage-baseline.toml`](coverage-baseline.toml) — **is** that reference point. #287 added the
> *measurement* (`make test-cov`); the raw outputs are git-ignored, so S0.2 (#288) records the curated
> baseline. The **enforcing** CI gate is deferred to **#290** (the coverage CI job is report-only today —
> its step name reads *"report only; failing gate lands in #290"*).

## How it's measured

`make test-cov` runs:

```
uv run pytest tests/unit -m unit -v \
  --ignore=tests/unit/_mcp --ignore=tests/unit/_cli --ignore=tests/unit/agent \
  --cov=neocarta --cov-report=term-missing --cov-report=xml --cov-report=html
```

Branch coverage is **on** (`[tool.coverage.run] branch = true`), `source = ["neocarta"]`,
`precision = 2`. Coverage tool: `coverage.py` 7.15.2 via `pytest-cov`. Outputs `coverage.xml` (Cobertura),
`htmlcov/`, `.coverage` — all git-ignored; this baseline is the deliberately-tracked artifact derived
from them.

## Per-package baseline (`make test-cov` scope)

Floors are the measured value **truncated down to a whole percent** (≈≤1pp jitter headroom). These are the
enforceable floors #290 gates against.

| Package (Cobertura name) | Line % | Line floor | Branch % | Branch floor |
|---|---:|---:|---:|---:|
| `data_model` | 99.69 | 99 | **96.15** | 83 |
| `root` (`neocarta/*.py` = `.`) | 95.50 | 95 | 86.84 | 86 |
| `enrichment` | 79.57 | 79 | 63.64 | 63 |
| `connectors` | 78.45 | 78 | 60.41 | 60 |
| `ingest` | 67.73 | 65 | **43.14** | 37 |
| **TOTAL** | **69.43** | **68** | **50.25** | **49** |

`ingest`'s measured values were refreshed by S1.3 (#294), which added merge-contract unit tests
(line 65.44 → 67.73, branch 37.23 → 43.14). Its floors are deliberately left at 65 / 37: the policy
raises floors after a *sustained* gain, and `trunc(43.14) = 43` would leave 0.14pp of headroom —
the zero-margin fragility that turned the #290 gate red before. Ratchet to 67 / 43 once these hold
across a few PRs.

`data_model` and TOTAL were refreshed the same way by S1.4 (#295), whose blank/NaN override
parametrization exercises the remaining `_validators.py` branches (`data_model` line 99.66 → 99.69,
branch 83.33 → 96.15; TOTAL line 68.53 → 69.43, branch 49.30 → 50.25). Floors held for the same
reason: a 13pp branch jump driven by one suite is exactly the case to let settle before ratcheting.

Measured against `main` for the 0.8.1 safety net: the 0.9.x normalization stack (its
100%-covered `normalization` / `data_model/normalized` packages) is not on this branch, so
there is no `normalization` row and `data_model`'s branch floor reflects main-only code.
`connectors` dominates the total. `ingest`'s **43% branch coverage** is still the weakest area and
a refactor target (see [test-quality-inventory.md](test-quality-inventory.md) → gap list), though
S1.3 (#294) closed that list's "golden-master the emitted merge patterns" gap for the shared
node/relationship query builders.

## Scope caveat — `_mcp` and `_cli` (read this before trusting a `_mcp`/`_cli` number)

`make test-cov` deliberately **excludes** the `tests/unit/_mcp`, `tests/unit/_cli`, and `tests/unit/agent`
suites (they run in the separate `make test-mcp` / `make test-cli` / `make test-agent` CI jobs). But
`neocarta._mcp` and `neocarta._cli` are still inside the coverage `source`, so under the `make test-cov`
scope they read as **artifacts, not real coverage**:

| Package | `make test-cov` reading (ARTIFACT) | Honest reading (dedicated suite) |
|---|---|---|
| `_mcp` | 0.00 line / 0.00 branch | **55.32 / 25.0** — `pytest tests/unit/_mcp --cov=neocarta._mcp` (unit only; integration needs Docker) |
| `_cli` | 41.70 line / 0.00 branch | **91.82 / 73.14** — `pytest tests/unit/_cli --cov=neocarta._cli` (217 tests) |

These honest numbers live under `[informational.*]` in the TOML and are **not** gated by a `make test-cov`
coverage.xml. `neocarta/agent/` and `eval/` are outside `source` entirely (omitted), so they never appear.

> **Reproducibility note.** The `_cli` supplementary run passes 217/217 in a clean environment. On a
> developer machine that has a real `.env`, one test (`test_common.py::test_apply_neo4j_overrides_leaves_
> env_values_when_flags_absent`) can fail because `neocarta/_cli/config.py::load_dotenv()` mutates the real
> `os.environ` (leaking e.g. `NEO4J_DATABASE`) into a pydantic-settings default. Run the supplementary
> `_cli` command with `NEO4J_DATABASE=neo4j` (or no `.env`) to reproduce the CI-clean 217/217. This is a
> test-hygiene note, recorded in [test-quality-inventory.md](test-quality-inventory.md) — not a code change
> for S0.2.

## Test-count baseline

GUIDE §4 also forbids dropping tests. Authoritative `pytest --collect-only -q` counts (the audit's "903"
was stale):

| Scope | Collected |
|---|---:|
| `make test-cov` (tests/unit minus `_mcp`/`_cli`/`agent`) | 1,042 |
| full `tests/unit` | 1,286 |
| all `tests/` (unit + integration + smoke) | 1,396 |

Ratcheted by each PR's own delta, which keeps the main-vs-branch margin intact rather than absorbing
another branch's tests into the floor: the `main` baseline was 878 / 1,122 / 1,218, S1.3 (#294)
added +59 unit / +14 integration, and S1.4 (#295) added +105 unit / +0 integration (the
explicit-ID override guards plus the csv / query_log passthrough parity suites).

## Reproduce

```bash
uv sync --all-groups --all-extras
make test-cov                                        # regenerates coverage.xml (gate-faithful scope)
# per-package line/branch rates: parse coverage.xml <package> line-rate / branch-rate,
# aggregated by top-level subpackage (Cobertura groups per directory).

# honest informational numbers (Both-scope decision):
uv run pytest tests/unit/_mcp --cov=neocarta._mcp --cov-report=term
NEO4J_DATABASE=neo4j uv run pytest tests/unit/_cli --cov=neocarta._cli --cov-report=term

# authoritative counts:
uv run pytest tests/unit --ignore=tests/unit/_mcp --ignore=tests/unit/_cli --ignore=tests/unit/agent --collect-only -q | tail -1
```

Every committed `*_floor` in the TOML is ≤ the freshly measured value (floors are truncated), so a
re-run must not fall below any floor unless coverage genuinely regressed.

## #290 consumption contract

The enforcing gate #290 wires should:

1. Run `make test-cov`, producing a fresh `coverage.xml`.
2. Load [`coverage-baseline.toml`](coverage-baseline.toml). For `[total]` and each `[packages.*]`, compare
   the fresh run's package `line-rate` / `branch-rate` (×100) against `line_floor` / `branch_floor`. **Fail**
   the build if any measured value drops below its floor. Map TOML key `root` → Cobertura package `.`.
3. Optionally gate `[test_count].gated_unit` — fail if the collected `make test-cov` count drops below it
   (the "never drop a test" half of the invariant).
4. **Ignore** the `[informational.*]` tables for a `make test-cov`-scoped gate; `_mcp`/`_cli` are gated by
   the `test-mcp` / `test-cli` jobs. Folding them into one unified measurement (and moving selection from
   directory `--ignore` to pytest markers) is an **S0-3 / #290** decision, out of scope for S0.2.

## Update / ratchet policy

Raise floors after a genuine, sustained coverage gain (ratchet up). **Never** hand-lower a floor to make a
change pass — that is exactly the regression the invariant forbids. When floors change, regenerate the
measured values in the same commit so `measured` and `floor` stay consistent.
