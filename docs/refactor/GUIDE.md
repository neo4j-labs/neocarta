# Neocarta Refactor — Contributor Guide

> **Who this is for:** contributors (human or agent) executing tickets from the neocarta production
> refactor. It holds the shared context every ticket relies on so individual tickets can stay focused.
> When a ticket says *"see GUIDE §X"*, it's this file.
>
> **Read this once**, then read your ticket's **Baseline reading** list before writing code.

---

## 1. What the refactor is

Neocarta is being re-architected from a labs codebase into a production-shaped, deduplicated, decoupled
core — **at full runtime parity**. The first phase (the **1.0.0 band**) rebuilds the *ingest half*:
connectors → a standardized **normalized schema** → one **central transform** → **canonical ontology
objects** → a **generic writer** → Neo4j.

The one intentional backwards-incompatible change is the **connector-authoring contract** (a public API
for developer-authored connectors), which is why the band culminates in a **major** version. End-users
and the `ingest()`/CLI surface are unaffected.

## 2. How we work: additive dual-path

We do **not** break the codebase and rebuild. New components are built **alongside** the originals
(mergeable, non-breaking), the originals are marked for deprecation, and the single break is
**concentrated at the connector cutover**. Practically, for most 1.0.0 tickets:

- Add the new thing next to the old thing; keep the old path working and tested.
- Prove the new path is byte-for-byte equivalent (see §4 characterization) before anything is removed.
- Removal of legacy code happens only at the designated cutover ticket.

## 3. Release milestones

| Milestone | Meaning | Semver |
|---|---|---|
| **0.8.1** | Safety net (coverage, markers, CI gate, characterization harness, scaffolding). **Zero behavior change.** | patch |
| **0.9.x** | New normalized schema, canonical ontology, central transform, generic pipeline/writer — **alongside** the legacy path, parity held. | minor |
| **1.0.0** | Connector cutover: connectors emit only the normalized schema; legacy per-connector transform/model path removed; connector-authoring contract breaks; `run()` removed. Runtime parity preserved. | major |

A ticket's milestone tells you what guarantees apply. A `0.8.1` ticket that changes runtime behavior is
wrong by definition.

## 4. Invariants (every ticket obeys these)

- **Parity.** Behavior after your change is identical to before, verified at each release point.
- **Characterization-first.** Capture current behavior as golden-masters *before* refactoring the code
  they guard. The harness for this is built in `S0-SPIKE-1`; reuse its reference pattern.
- **No coverage / test-count regression.** Never drop a test or lower coverage. Moves must preserve the
  collected test set (see `S0-3`). The CI gate (`S0-4`) enforces this.
- **Additive-only ontology extension.** Extend the model by adding node/rel/property types; never modify
  or remove existing shape.
- **Model-Placement Convention.** A model's *publicity scope* is expressed by *where it lives*: a model
  shared by multiple areas lives at the **lowest common ancestor** directory of its referencers
  (`root/models` global → `etl/models` → `consumption/models` → `.../api/models`). One owner per piece
  of state.

## 5. Target architecture & directory mapping

The ingest half is moving to this shape (1.0.0-relevant packages):

```
etl/
  models/                 # canonical model objects
  ontology/               # NodeType/RelType/PropertySpec + per-type identity (KeySpec)
  metadata_normalizer/
    normalized_schema/    # the shared, source-agnostic tabular contract (S1)
  transform/              # the one central transform + generic KeySpec ID builder (S3)
  enrichment/             # embeddings, ontology-driven target selection (S5)
  pipeline/               # extract→normalize→transform→load→metadata orchestrator + generic writer (S5)
extensions/
  connectors/             # connectors as extension artifacts (base types + per-source) (S4)
  enrichments/            # enrichment extension point (S5)
```

**Parent package** (ratified in `S0-5`, #286): the target tree hangs off the existing `neocarta/`
package — the `etl/` and `extensions/` paths below are `neocarta/etl/…` and `neocarta/extensions/…`.
**Status:** the empty packages are scaffolded; **no code has moved yet** (additive dual-path, §2).

**Current → target mapping** (ratified in `S0-5`; nothing moves until its ticket, then additively):

| Today | Target |
|---|---|
| `connectors/<src>/extract.py` | `extensions/connectors/<src>` (+ base `information-schema-table` / `query` / `log_parser`) |
| per-connector `transform.py` | **central** `etl/transform` (S3) |
| `connectors/models.py` | `extensions/connectors/models` (private cache) **+** `etl/metadata_normalizer/normalized_schema` (shared contract) |
| `connectors/utils/generate_id.py` | `etl/transform` as an ontology-KeySpec-driven **generic** ID builder |
| `data_model/*` | `etl/models` + `etl/ontology` |
| `enrichment/` | `etl/enrichment` + `extensions/enrichments` |
| `ingest/` | `etl/pipeline` + generic writer |
| `agent/` | **removed** (later band) |

## 6. Glossary of terms

- **Normalized schema** — the flat, standardized, source-agnostic tabular contract a connector emits.
  Identity-agnostic (no graph IDs), source-derived fields only. Decouples connectors from the ontology.
- **Canonical ontology objects** — the graph-shaped model the transform produces, carrying IDs.
- **KeySpec** — the per-NodeType identity declaration in the ontology; the generic ID builder uses it to
  construct node IDs, replacing the ~15 hand-written `generate_*_id` functions.
- **Central transform** — the single ontology-aware component that turns normalized schema (and the
  graph/semantic intermediate) into canonical ontology objects.
- **Graph Spec** (a.k.a. **import-spec**, the `neo4j/import-spec` artifact) — Neo4j's native import
  configuration format (`sources → targets → actions`, with `SourceProvider`/`EntityTargetExtensionProvider`
  SPIs). It is **mapping/ETL-shaped**, so the whole normalized-schema → ingest stack can be expressed as one
  Neo4j-native Graph Spec JSON lineage, and its `SourceProvider` SPI is a leading candidate for the
  connector-mapping mechanism. Treat the exact format as an **evolving external dependency** (it is RC) — adapt
  behind our boundary, don't block on it.
- **Characterization / golden-master** — a captured snapshot of current output used to prove a refactor
  didn't change behavior.

## 7. Delta glossary (design decisions tickets cite)

These are **settled** decisions. A ticket citing `D#` means "this constraint is fixed — don't relitigate."

- **D2** — the Text2SQL `agent/` is removed in a later band; don't build durable dependencies on it.
- **D4** — test selection moves from directory paths to pytest markers (see `S0-3`).
- **D5** — a connector's extractor cache is **private**; its only public output is the normalized schema.
- **D6** — identity is an ontology-declared **KeySpec** per NodeType; connector mappings are
  **identity-agnostic**; one generic ID builder replaces the per-connector `generate_*_id` functions; a
  rare explicit-ID override exists for cross-source alignment. The override is specified and tested in
  `docs/refactor/explicit-id-override.md` (`S1-4`).
- **D7** — normalization needs value coercions (not just field renames). The standardized field
  vocabulary both halves resolve onto is ratified in `docs/refactor/field-vocabulary.md` (`S1-5`).
- **D10** — sparse rows are supported with a **non-clobber merge** contract (partial data never erases
  fuller data). Specified and tested in `docs/refactor/merge-contract.md` (`S1-3`).
- **D11** — two ingestion paradigms: **tabular** (→ normalized schema) and **graph/semantic** (OSI now),
  each decoupled, converging on one canonical model.
- **D12** — legacy `export()` (graph → file) is kept alive through the 1.0.0 cutover for parity; its
  redesign is a later band.
- **D13** — the Neo4j-native ontology format is an **evolving external dependency**; we keep an internal
  LPG model behind an adapter and adapt rather than block.
- **D14** — the normalized-schema mapping and the ontology converge on **one Neo4j-native Graph Spec
  (import-spec) JSON lineage**; Graph Spec is a leading candidate for both the normalization intermediate
  standard and the connector-mapping mechanism (see `S1-SPIKE-1`).
- **D16** — the graph/semantic transform is built **OSI-minimal** now but the seam is designed to later
  accommodate other graph-shaped schema paradigms without rework.
- **D17** — connectors are built as **spin-out-ready extension artifacts**: even our own connectors
  consume only the public extension API + categorical templates, behind an enforced boundary.

## 8. Working agreement

- **Environment:** this project uses **`uv`**. Always run code via `uv run`. Install dev deps with
  `uv sync --all-groups`.
- **Tests:** `make test-unit` · `make test-it` (Docker) · `make test-mcp` (Docker) · `make test-cli` ·
  `make test-smoke` · `make test-all` (Docker). Coverage: `make test-cov` (added in `S0-1`).
- **Formatting/linting:** `make fmt` (ruff format) and `make lint` (ruff check) — both must pass.
- **Docstrings & style:** follow the conventions in the repo-root **`CLAUDE.md`** (authoritative; don't
  restate it here).
- **Every PR:** tests added/updated, all tests pass, ruff clean, **`CHANGELOG.md` updated**.

## 9. How to read a ticket

Each refactor ticket carries these sections — use them as intended:

- **Baseline reading** — read these files *first* to orient. The audit already found the relevant code;
  this list is it. Don't go spelunking beyond it unless you need to.
- **Current mechanism (from audit)** — the as-built state, pre-derived so you don't have to.
- **Fixed decisions (immutable)** — settled design; **do not relitigate or "improve"** these. If one
  seems wrong, raise it — don't silently deviate.
- **Latitude (your call)** — where you're expected to exercise judgment and problem-solve. Make the call,
  justify it briefly in the PR.
- **Acceptance criteria** — the definition of done; each item should be objectively checkable.
- **References** — where to find more (this guide, code, skills).
