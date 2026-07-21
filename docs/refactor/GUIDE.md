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
  they guard. The harness for this is built in `S0.6`; reuse its reference pattern.
- **No coverage / test-count regression.** Never drop a test or lower coverage. Moves must preserve the
  collected test set (see `S0.3`). The CI gate (`S0.4`) enforces this.
- **Testing cadence — every ticket.** A behavior-changing ticket adds or updates tests *as part of the
  ticket*. **Refactors:** characterize the current behavior into the `S0.6` golden-master harness first,
  then prove the change reproduces it (parity). **Net-new code:** ship its own tests and never lower the
  coverage floor — a new package should raise it. Your ticket's **Characterization/Test plan** and
  **Parity check** are acceptance criteria: the ticket is *not done* until its behavior is captured. The
  harness is a **living artifact** — extend it with your change, don't just consume it.
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

**Current → target mapping** (ratified in `S0.5`; nothing moves until its ticket, then additively):

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
- **D4** — test selection moves from directory paths to pytest markers (see `S0.3`).
- **D5** — a connector's extractor cache is **private**; its only public output is the normalized schema.
- **D6** — identity is an ontology-declared **KeySpec** per NodeType; connector mappings are
  **identity-agnostic**; one generic ID builder replaces the per-connector `generate_*_id` functions; a
  rare explicit-ID override exists for cross-source alignment.
- **D7** — normalization needs value coercions (not just field renames).
- **D10** — sparse rows are supported with a **non-clobber merge** contract (partial data never erases
  fuller data).
- **D11** — two ingestion paradigms: **tabular** (→ normalized schema) and **graph/semantic** (OSI now),
  each decoupled, converging on one canonical model.
- **D12** — legacy `export()` (graph → file) is kept alive through the 1.0.0 cutover for parity; its
  redesign is a later band.
- **D13** — the Neo4j-native ontology format is an **evolving external dependency**; we keep an internal
  LPG model behind an adapter and adapt rather than block.
- **D14** — the normalized-schema mapping and the ontology converge on **one Neo4j-native Graph Spec
  (import-spec) JSON lineage**; Graph Spec is a leading candidate for both the normalization intermediate
  standard and the connector-mapping mechanism (see `S1.6`).
- **D16** — the graph/semantic transform is built **OSI-minimal** now but the seam is designed to later
  accommodate other graph-shaped schema paradigms without rework.
- **D17** — connectors are built as **spin-out-ready extension artifacts**: even our own connectors
  consume only the public extension API + categorical templates, behind an enforced boundary.

**Section deltas (RP-B / RP-C — S6–S9).** Settled decisions the consumption / interface / extension /
administration tickets cite by code:

- **D-S6-1** — consumption is **sans-I/O op-specs + two once-declared executors** (sync, async); each interface binds one mode. (S6.6/7/8)
- **D-S6-2** — adaptive availability moves **into the corpus** as an executor-driven method; CLI gains gate/warn instead of blind runtime errors. (S6.9)
- **D-S6-3** — **preserve 1:1** op-spec per existing tool at the 1.1.0 cutover; matrix-collapse deferred to S8. (S6.6)
- **D-S6-4** — the corpus raises **typed `NeocartaError` domain errors**; interfaces map them (CLI exit / MCP error / HTTP status). (S6.11)
- **D-S6-5** — *discrepancy:* the CLI `tool` group omits metric-search + OSI tools; closed for free by the shared corpus. (S6.6)
- **D-S6-6** — *discrepancy:* consumption→connectors backward import of `generate_osi_semantic_model_id`; closed by routing IDs through the D6 KeySpec builder. (S6.10)
- **D-S7-1** — two parallel settings systems + MCP `neo4j_password` stored as plain `str`; the unified settings core fixes it to `SecretStr`, env names kept as aliases. (S7.4)
- **D-S7-2** — an interface is a **thin adapter over the corpus** (bind executor once; op-spec→surface; typed-error→contract; DTO→envelope); MCP/CLI generated, not hand-maintained. (S7.1/2/3)
- **D-S7-3** — **API/UI deferred to RP-D / 2.0.0** (post-authN); 1.1.0 ships the adapter abstraction + MCP/CLI onto it. (S7 scope)
- **D-S7-4** — RP-B is **minor (1.1.0) by default**; forced-break tripwire → major. (band semver)
- **D-S7-5** — S7 lands the settings **model**; **S9 builds management** (rotation / storage / admin UX) on top. (S7.4/5 → S9)
- **D-S7-6** — the settings core administers **per-connector source-location + source-auth** as typed config+credential bundles (each connector self-declares its schema); env-only/`SecretStr`. (S7.5)
- **D-S8-1** — consolidate the ad-hoc connector (S4.7/8) + enrichment (S5.3.2) machinery into **one SPI / discovery / boundary**; retrofit both (dogfood, parity-guarded). (S8.2/3/4/5)
- **D-S8-2** — 1.2.0 extension-point coverage = **connectors + enrichments + methods**; model/interface extension deferred. (S8 scope)
- **D-S8-3** — **core-vs-licensed:** separate packages / same SPI now + a **pluggable entitlement-gate hook (default allow-all)** a future license-key provider can back. (S8.2/8)
- **D-S8-4** — **one uniform discovery mechanism:** import-spec-SPI-aligned entry points with per-type namespaces (not per-type registries). (S8.2)
- **D-S8-5** — *discrepancy:* `BaseEmbeddingsConnector` misnaming (the enrichment base is not a source connector); renamed. (S8.5)
- **D-S9-1** — the **config-as-code manifest** is the declared-config source of truth, per **OpenGitOps** (desired-state + reconcile; reverses "no YAML"). Runtime state → graph; secrets → env via provider. (S9.3)
- **D-S9-2** — the S5.1 orchestrator **consumes the pipeline manifest** (named insertion points), not a hardcoded sequence. (S9.4)
- **D-S9-3** — **administration is a separate corpus** parallel to S6 (shared pattern, own registry); the first surface S10 gates. (S9.2)
- **D-S9-4** — authorization = **PEP/PDP with an AuthZEN-shaped PEP** delegating to an external PDP (OPA/Cedar/OpenFGA); no in-house engine or permission model (see §10). (S9.2/9.9)
- **D-S9-5** — enterprise identity via **OIDC/SAML/SCIM** (Entra/Okta); integrate proven libraries, don't build auth (see §10). (S9.9)
- **D-S9-6** — observability standardizes on **OpenTelemetry** (API + semantic conventions + OTLP); supersedes bespoke metrics (see §10). (S9.8)
- **D-S9-7** — secrets via a **pluggable secret-provider interface** (env default; external managers / SPIFFE later); env-only invariant preserved. (S9.3/9.5)
- **D-S9-8** — config precedence gains a **manifest layer** (flag > env > manifest > default); parity preserved when the manifest is absent. (S9.3)
- **D-S9-9** — as of **1.2.0**, adherence to the §10 external standards is **mandatory** for application-admin code (REVIEW.md-enforced). (S9.12)

## 8. Working agreement

- **Environment:** this project uses **`uv`**. Always run code via `uv run`. Install dev deps with
  `uv sync --all-groups`.
- **Tests:** `make test-unit` · `make test-it` (Docker) · `make test-mcp` (Docker) · `make test-cli` ·
  `make test-smoke` · `make test-all` (Docker). Coverage: `make test-cov` (added in `S0.1`).
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
- **Characterization / Test plan** — which golden-masters guard this change (refactors), or the new tests
  you must add (net-new). **Binding:** extend the `S0.6` harness with your change — a behavior change isn't
  done without it (see §4 testing cadence).
- **Parity check** — how you prove behavior is unchanged; for refactors this must pass *before* any legacy
  removal.
- **References** — where to find more (this guide, code, skills).

## 10. External standards (application administration)

> **Scope:** these bind the **application-administration** seams introduced in the **S9 (Administration,
> 1.2.0)** and **S10 (AuthN & Permissions, 2.0.0)** bands — *not* the 1.0.0 ingest work above. Application
> administration (identity, authorization, secrets, observability) is a solved, standardized problem:
> neocarta **integrates and delegates to these standards rather than inventing its own**. When an S9/S10
> ticket says *"per GUIDE §10"*, bind to the named standard here; do not hand-roll an equivalent.

**Identity / authentication (federation with enterprise IdPs — Microsoft Entra, Okta, …)**
- **OpenID Connect (OIDC) / OAuth 2.x** — modern app + API authentication. <https://openid.net/connect/>
- **SAML 2.0** (OASIS) — enterprise web SSO. <https://docs.oasis-open.org/security/saml/v2.0/>
- **SCIM 2.0** (RFC 7643/7644) — user & group provisioning lifecycle (joiner/mover/leaver).
  <https://datatracker.ietf.org/doc/html/rfc7644>
- *Rule:* integrate a proven library (e.g. Authlib for OIDC/OAuth, python3-saml for SAML); assign access by
  **groups / app-roles**, never per-user. neocarta does **not** implement authentication.

**Authorization (permissions)**
- **PEP/PDP separation** — the enforcement point (PEP) intercepts; the decision point (PDP) decides.
  Formalized in **NIST SP 800-162 (ABAC)**'s functional decomposition (Enforcement · Decision ·
  Access-Control-Data · Administration). <https://nvlpubs.nist.gov/nistpubs/specialpublications/nist.sp.800-162.pdf>
- **AuthZEN Authorization API** (OpenID Foundation) — the **standard PEP↔PDP API**; lets you swap policy
  engines without rewriting enforcement. <https://openid.net/wg/authzen/>
- **Access-control models** — NIST **RBAC** (roles), **ABAC** (attributes, SP 800-162), **ReBAC** (Zanzibar
  relationships). neocarta ships an **AuthZEN-shaped PEP** and delegates the model + engine to an external
  **PDP** — it does **not** build a policy engine or own a permission model.
- **Policy engines** (the pluggable PDP): OPA/Rego <https://www.openpolicyagent.org/> · AWS Cedar
  <https://www.cedarpolicy.com/> · OpenFGA (Zanzibar) <https://openfga.dev/> ·
  engine comparison <https://www.osohq.com/learn/opa-vs-cedar-vs-zanzibar>.

**Secrets**
- **12-Factor config** — secrets from the environment (the floor; neocarta's default). <https://12factor.net/config>
- **External secret managers** (storage + rotation): HashiCorp Vault, cloud KMS/Secret Manager. neocarta
  resolves secrets through a **provider interface** (`ref: env://…` today; `vault://…`/cloud later).
  <https://developer.hashicorp.com/vault>
- **SPIFFE/SPIRE** (CNCF) — keyless workload identity (future). <https://spiffe.io/>

**Observability**
- **OpenTelemetry** (CNCF, graduated 2026) — the vendor-neutral standard: OTel API/SDK + **semantic
  conventions** + **OTLP** export. neocarta instruments to the **OTel API** (SDK as an optional extra) and
  bridges its existing logging to OTel logs; it does **not** invent a bespoke metrics format.
  <https://opentelemetry.io/> · semantic conventions <https://opentelemetry.io/docs/specs/semconv/>
- **Health checks** — Kubernetes liveness/readiness conventions.

**Declarative configuration**
- **OpenGitOps** (CNCF) — declarative · versioned+immutable · pulled · **continuously reconciled**
  (desired-vs-actual). neocarta's config-as-code manifest is *desired state*; admin apply is *reconciliation*.
  <https://opengitops.dev/>
