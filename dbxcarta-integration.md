# dbxcarta Integration: Design Decisions

Design decisions for integrating the dbxcarta Databricks pipeline into
neocarta as a first-class connector.

## Databricks external connections and why embedding models are now shared

A Databricks **model serving endpoint** is a URL inside your workspace that
serves a model. Usually that model runs on Databricks, but Databricks also
supports **external models**: an admin registers a third-party model, for
example OpenAI `text-embedding-3-small`, behind a serving endpoint. The
endpoint then acts as a governed proxy. Clients call the Databricks URL with
Databricks credentials, and Databricks forwards the request to OpenAI using a
centrally stored API key. The enterprise gets one place for governance, audit
logging, rate limits, and billing, and no OpenAI keys spread across teams.

dbxcarta registered OpenAI's embedding model as an external endpoint and
calls it from the Spark job like any native Databricks model. With this in
place, the dbxcarta pipeline and neocarta's enrichment layer can produce
identical vectors from the same endpoint, so where the embedding step runs
becomes a deployment choice, not a compatibility problem.

## Question 1: embeddings in the spark data pipeline, after it, or both

The integration branch removed the embed stage from the Spark job. Embeddings
are added afterward by neocarta's existing enrichment layer, the same path
every other connector uses. That is a clean default, and we would like to keep
it. The question is whether to also offer an **opt-in flag** to embed during
the Spark job, because for enterprises with large catalogs the in-pipeline
path is much more performant:

- **Very large node counts**, especially if Value nodes are embedded. Sampled
  values can be 10-100x the column count. Millions of API calls plus millions
  of Neo4j property writes is where the driver-based write-back becomes the
  slow part.
- **Databricks serving endpoints with provisioned throughput**, where you
  control the capacity and can actually consume executor-level parallelism.
- **Data locality**: no round trip of reading descriptions out of Neo4j that
  the Spark job just wrote in.

And some customers will simply want the whole flow native to Databricks: one
job, one platform, nothing running outside the workspace.

The two paths compose well. Enrichment only touches nodes missing an
`embedding`, so in-pipeline embedding pre-pays work and enrichment no-ops.
The costs of offering both: two embedding implementations to maintain, and
both must agree on model and dimension or the vector index breaks.

**Proposed**: enrichment-after stays the default; add `embed_during_ingest`
as an opt-in setting for large-catalog and Databricks-native deployments.

## Question 2: should we offer an alternative to LiteLLM for Databricks-native shops

LiteLLM backs neocarta's embeddings connector and is currently a **base
dependency**, imported eagerly by the enrichment package. That means every
install pulls it, including `neocarta[databricks-spark]` on a cluster, and
pip has no way to exclude a declared dependency. A Databricks-native shop
running a Spark pipeline with in-pipeline embeddings would carry LiteLLM
without ever calling it.

We have seen customers becoming more security conscious after the recent
supply chain attacks, so it is worth weighing the pros and cons here. LiteLLM
is widely adopted and genuinely the right tool for the multi-provider default
path. At the same time, it carries adapters for 100+ providers and a broad
dependency tree, and Databricks customers in particular may push back on
extra libraries landing on a governed cluster that their workload never
calls. For details, see the overview of the LiteLLM supply chain attack at
the bottom of this document.

A related hardening step regardless of what we decide: neocarta pins
`litellm>=1.55.0` with no upper bound, so a fresh install always resolves to
the newest release, and a freshly poisoned release would land the day it is
published. Adding a version ceiling shrinks that window, and pinned, locked
versions at deployment time (a lockfile, or the pinned dependency closure the
dbxcarta cluster install already uses) close it further, since malicious
releases tend to be caught within days. Ceilings on a published library do
carry a cost, since tight upper bounds can cause resolution conflicts for
users, so the proposal is a sane ceiling plus locked deployments rather than
aggressive pinning.

Two changes would address the dependency-footprint concern directly:

- **Make LiteLLM excludable.** Move `litellm` from base dependencies to an
  extra and load it lazily, the same pattern the integration branch already
  uses for pyspark: importing the package stays cheap, and using the LiteLLM
  connector without the extra raises a clear, actionable `ImportError`. The
  trade-off is a packaging break: plain `pip install neocarta` would no longer
  embed out of the box, so the default install story needs care.
- **Add a native Databricks backend.** The enrichment package is already
  built for pluggable providers: a shared base class owns the workflow, and
  each provider supplies only the "embed this text" call. A small
  `DatabricksEmbeddingsConnector` built directly on `databricks-sdk`, which is
  already a base dependency on the branch, would slot in beside the existing
  LiteLLM and OpenAI connectors. Databricks shops get ambient SDK auth and a
  pure-Databricks dependency chain, with no LiteLLM anywhere in the path.

**Proposed**: add the native connector; decide separately whether moving
LiteLLM behind an extra is worth the packaging break.

## Question 3: should the verify and run-summary ops features come along

dbxcarta-spark ships two operational features the integration branch did not
port: a `verify` package that checks the finished graph against the source
catalog after a run, and a step that persists the run summary to a Delta
table. We would like to include both. Neither affects the ingest itself:

- **Verify runs after the writes finish**, as a separate read-only pass that
  compares the graph against what the catalog said should exist: catalog and
  graph counts, sampled values, and reference integrity. It adds some
  wall-clock time at the end of the job and can sit behind a flag, but the
  ingest writes are untouched. The value: a scheduled job stops meaning "the
  job exited zero" and starts meaning "the graph matches the source." Silent
  partial writes, stale nodes, and broken references get caught before an
  agent ever queries the graph.
- **The run summary is already computed.** The branch's `run_ingest` builds
  and returns an in-memory `RunSummary`; only the step that writes it to a
  Delta table was dropped. Persisting one small record at the end of a run
  costs nothing. The value: a queryable history of every run, what was
  ingested, counts, and timing, sitting in Delta where ops teams already
  build monitoring, alerting, and run-over-run drift checks, instead of
  digging through job logs.

**Proposed**: port both with the connector, behind the same
`databricks-spark` extra, with verify controlled by a settings flag.

## Validation Needed: how enrichment talks to Databricks serving

If embeddings run outside the pipeline, the enrichment layer must reach the
Databricks serving endpoint. LiteLLM, which backs neocarta's embeddings
connector, has a native Databricks provider: `databricks/<endpoint-name>`.
Two things to validate with a test pass:

- **Ambient SDK credentials.** Many enterprises will not accept static token
  auth. LiteLLM documents that when no credentials are passed it falls back to
  the Databricks SDK's unified auth chain: cluster-ambient credentials, OAuth
  M2M service principals, Azure AD. We should test this, since it is the auth
  model Databricks shops expect.
- **External model endpoints.** Confirm `databricks/<endpoint>` works the
  same against an external-model endpoint as against a native one.

## Other decisions on the list

- **What embedding text gets embedded.** Enrichment embeds the node's
  `description`, which for this connector is the Unity Catalog comment.
  dbxcarta's contract instead defined a composite `embedding_text` per label,
  joined with `" | "` and skipping empty comments:
  - Schema: `catalog.schema | comment`
  - Table: `catalog.schema.table | comment`
  - Column: `catalog.schema.table.column | data_type | comment`
  - Database: `name`; Value: the sampled `value` itself

  The fully qualified path and the column data type make the vector match
  name- and type-shaped questions even when comments are sparse or missing. 
  Decide whether the connector should write that richer text into `description` 
  at ingest so post-hoc embedding matches dbxcarta quality.
- **Connector contract conformance.** The ported connector exposes
  `run(spark)` only. neocarta's `SourceConnectorProtocol` expects
  `extract` / `transform` / `load` / `ingest`. Proposed: map the Spark phases
  onto those names; fall back to a documented exemption only if that proves
  artificial.

## Appendix: the LiteLLM supply chain attack (March 2026)

Context for the security discussion in Question 2.

On March 24, 2026, two LiteLLM releases on PyPI, versions 1.82.7 and 1.82.8,
were found to contain malicious code. The attacker, tracked as TeamPCP,
obtained the maintainer's PyPI credentials by first compromising Trivy, an
open source security scanner used in LiteLLM's own CI/CD pipeline, and
published the poisoned versions from the legitimate account. LiteLLM was
being downloaded roughly 3.4 million times per day at the time.

The payload had three stages: a credential harvester targeting over 50
categories of secrets including cloud credentials, SSH keys, and Kubernetes
secrets; a Kubernetes lateral-movement toolkit capable of compromising
entire clusters; and a persistent backdoor providing ongoing remote code
execution. In 1.82.8 the malware shipped as a `.pth` file at the wheel root,
which Python executes automatically at interpreter startup. Importing
litellm was never required; installing it was enough.

Two points make this relevant to neocarta's packaging decisions:

- **Floor-only pins maximize exposure.** Any environment that resolved
  `litellm>=...` during the compromise window pulled the newest, poisoned
  release. The malicious versions were identified and removed within days,
  which is exactly the window that version ceilings and locked deployments
  are designed to cover.
- **Surface area is the multiplier.** LiteLLM ships adapters for 100+
  providers and pulls a correspondingly broad dependency tree, including
  `openai`, `httpx`, `aiohttp`, `jinja2`, and tokenizer libraries, most of
  which a single-provider deployment never exercises. Beyond the supply
  chain event it has a steady CVE history, though largely in its proxy
  server, which neocarta never runs. Security scanners flag by package and
  version rather than by usage, so the review burden lands on every install
  either way.

Sources:

- [Trend Micro: Inside the LiteLLM Supply Chain Compromise](https://www.trendmicro.com/en_us/research/26/c/inside-litellm-supply-chain-compromise.html)
- [Snyk: How a Poisoned Security Scanner Became the Key to Backdooring LiteLLM](https://snyk.io/blog/poisoned-security-scanner-backdooring-litellm/)
- [Datadog Security Labs: Tracing the TeamPCP supply chain campaign](https://securitylabs.datadoghq.com/articles/litellm-compromised-pypi-teampcp-supply-chain-campaign/)
- [Bitsight: Supply Chain Compromise in LiteLLM Versions 1.82.7 and 1.82.8](https://www.bitsight.com/blog/litellm-versions-1-82-7-1-82-8-supply-chain-compromise)
- [Sonatype: Compromised litellm PyPI Package Delivers Multi-Stage Credential Stealer](https://www.sonatype.com/blog/compromised-litellm-pypi-package-delivers-multi-stage-credential-stealer)
- [Vulners: LiteLLM CVE list](https://vulners.com/search/vendors/litellm/products/litellm)
