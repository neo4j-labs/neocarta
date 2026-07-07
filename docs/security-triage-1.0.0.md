# Security triage — `security-patch-1.0.0`

This document records the disposition of the findings from two automated security reports
("Purple Phoenix Agentic Code Triager"): an exploit hunt (V-01..V-05) and an AI-BOM
supply-chain assessment of `litellm` (SC-*/RT-*/AI-*). Every claim was verified against the
source. It is the durable record of what was fixed, what was consciously not changed, and why.

## Threat model

Neocarta ships as an operator-run CLI **and** as a library / MCP server that may be embedded
behind a service exposed to third parties. Triage therefore treats two boundaries differently:

- **Operator inputs** — CLI flags / env vars supplied by the person running neocarta with their
  own credentials (JDBC URL, driver/SchemaCrawler JAR paths, schema filter, `litellm_kwargs`,
  Neo4j credentials). The operator already has code execution on the host; a tool doing what its
  own operator tells it is **not** a privilege-boundary crossing.
- **Untrusted inputs** — data that can originate from a third party in a service deployment:
  MCP tool `text_content` (from an agent / MCP client), and OSI `spec_source` URLs when a wrapper
  passes them through. These are hardened.

## Summary

| ID | Report severity | Verdict | Disposition |
|----|-----------------|---------|-------------|
| V-04 | MEDIUM | Real, low severity | **Fixed** |
| V-03 | MEDIUM | Real (injection under service model + robustness) | **Fixed** |
| V-02 | HIGH | Real defense-in-depth under service model | **Fixed** |
| RT-04 | MEDIUM | Report advice would *regress* a deliberate control | **Won't fix (by design)** |
| V-01 | HIGH | Operator input; documented feature; no boundary | **Won't fix (by design)** |
| V-05 | HIGH | By design — the tool loads the operator's JARs | **Won't fix (by design)** |
| RT-01 / RT-02 | HIGH | Operator config; documented LiteLLM feature | **Won't fix (by design)** |
| SC-01 / SC-02 | HIGH | Factually incorrect | **No action (incorrect)** |
| AI-01 / AI-02 | MED / LOW | Inherent to RAG-over-metadata; mitigation belongs to the consuming agent | **Out of scope** |

---

## Fixed

### V-04 — MCP `neo4j_password` stored as plain `str`
**Real.** [neocarta/_mcp/settings.py](../neocarta/_mcp/settings.py) declared `neo4j_password: str`
while the CLI deliberately uses `SecretStr` ([neocarta/_cli/config.py:88-91](../neocarta/_cli/config.py)).
The MCP settings object could leak the raw password via `repr`, `str`, or `model_dump_json` (e.g. if a
framework logs settings at startup).
**Fix.** Field is now `SecretStr`; unwrapped inline with `.get_secret_value()` at the sole consumption
site ([neocarta/_mcp/server.py](../neocarta/_mcp/server.py) driver auth). Tests:
`tests/unit/_mcp/test_settings.py`.
**Residual risk.** Low — the value still lives in the environment and in memory at connect time;
`SecretStr` only prevents accidental serialisation.

### V-03 — Lucene query sanitiser stripped instead of escaping
**Real** (elevated under the service threat model, where `text_content` is untrusted). The old
`remove_lucene_chars` replaced special characters with spaces but left the bare boolean operators
`AND`/`OR`/`NOT` live and could produce Lucene parse errors (a per-call DoS). It also silently
dropped content (`C++` → `C  `), degrading search. Note there was **never** a Cypher-injection
surface: the value is passed as the `$queryText` *parameter* to `db.index.fulltext.queryNodes`, not
interpolated.
**Fix.** Replaced with `escape_lucene_query` ([neocarta/_mcp/utils.py](../neocarta/_mcp/utils.py)):
backslash-escapes every Lucene special character and lower-cases the bare boolean operators, so an
untrusted query is matched literally and cannot inject Lucene syntax or crash the parser, while
preserving the search terms. All 10 call sites (full-text / hybrid / business-term-hybrid tools ×
table/column/metric, plus the CLI mirror) use it. Tests: `tests/unit/_mcp/test_utils.py`; two CLI
tests updated to the escape contract.
**Residual risk.** Low — the tools search only metadata they are designed to return; escaping hardens
the Lucene layer.

### V-02 — SSRF in the OSI spec URL fetch
**Real defense-in-depth** (matters when a service passes untrusted `spec_source` URLs). The fetch
resolved only the URL scheme and called `httpx.get(..., follow_redirects=True)` with no address
guard, so `http://169.254.169.254/…` (cloud metadata) or internal hosts could be reached, and an
open redirect on an allowed host could pivot inward.
**Fix.** [neocarta/connectors/osi/ingest/extract.py](../neocarta/connectors/osi/ingest/extract.py)
now calls `_assert_public_url` before fetching — it resolves the host and rejects loopback,
link-local (incl. `169.254.169.254`), private, reserved, multicast, and unspecified addresses — and
sets `follow_redirects=False`, rejecting redirect responses with a clear error so a redirect cannot
pivot past the initial check. Raises the connector's typed `ConfigError`. Tests:
`tests/unit/connectors/osi/test_ingest_extract.py`.
**Residual risk.** Low–medium: a TOCTOU / DNS-rebinding window remains (the name is validated, then
`httpx` re-resolves it). Closing that fully requires pinning the resolved IP into the connection,
which `httpx` does not support ergonomically; acceptable for a library where the caller ultimately
chooses the source.

---

## Won't fix (by design)

### RT-04 — broad `except` logs only the exception type
**The report's advice would regress a deliberate control.** Both embedding connectors
([openai_embeddings.py](../neocarta/enrichment/embeddings/openai_embeddings.py),
[litellm_embeddings.py](../neocarta/enrichment/embeddings/litellm_embeddings.py)) log `type(e).__name__`
only — **on purpose**. Provider SDK error bodies echo the input text (node descriptions — potential
PII) and API keys; logging the full message would leak them. This is asserted by
`tests/unit/enrichment/embeddings/test_logging.py::test_provider_error_logs_type_only_without_leak`
(the `_LEAKY_ERROR` fixture contains `sk-proj-LEAKED`). We keep type-only logging and added a
matching regression test for the LiteLLM path. Diagnosability is preserved at the batch layer, which
re-raises the full exception to the caller.

### V-01 — SchemaCrawler `--schemas` "regex injection"
`schemas` is an operator CLI input joined into SchemaCrawler's documented `--schemas=<regex>` and
passed as an **argv list, not a shell string** ([extract.py:295](../neocarta/connectors/jdbc/schema/extract.py),
[extract.py:315](../neocarta/connectors/jdbc/schema/extract.py)). Supplying `.*` scans your own
database; ReDoS is self-inflicted. No trust boundary is crossed.

### V-05 — JAR classpath "RCE"
`--jdbc-driver-jar` / `--schemacrawler-jar` are operator inputs the connector exists to load
(`java -cp <jars>`, [extract.py:277-282](../neocarta/connectors/jdbc/schema/extract.py)). An operator
who can set them already has code execution on the host. A service must never expose these to
untrusted callers; that is a deployment constraint, documented here, not a code fix.

### RT-01 / RT-02 — `litellm_kwargs` / `api_base` passthrough
Operator-supplied connector configuration
([litellm_embeddings.py:84,113](../neocarta/enrichment/embeddings/litellm_embeddings.py)), forwarded
verbatim as documented for LiteLLM Proxy / custom endpoints. Not third-party input.

---

## No action (factually incorrect)

### SC-01 / SC-02 — "unpinned litellm / no hash integrity"
`uv.lock` pins `litellm==1.86.1` from PyPI with per-artifact **sha256 hashes** (the lockfile carries
2948 hashes total). `>=1.55.0` in `pyproject.toml` is the correct dependency floor for a *published
library* (over-constraining a library breaks downstream resolution); reproducible installs come from
the lockfile. The HIGH ratings do not hold. A `<2.0.0` upper bound could be added as a minor
courtesy but is optional.

---

## Out of scope

### AI-01 / AI-02 — prompt injection via graph metadata / no output moderation
Source-catalog descriptions flow into agent prompts and MCP results; malicious metadata could carry
injection text. This is inherent to any RAG-over-metadata system, and mitigation (input framing,
output moderation, guardrails) belongs to the consuming agent, not the neocarta core library.

---

## Positive posture (under-credited by the reports)
- DB password passed to SchemaCrawler via env, never argv ([extract.py:293](../neocarta/connectors/jdbc/schema/extract.py)).
- `subprocess` invoked with argv lists, never `shell=True`.
- Bundled template resolved via `importlib.resources`, not a mutable path.
- `yaml.safe_load` for OSI specs.
- Parameterized Cypher throughout production code (f-string Cypher appears only in tests / dataset scripts).
- `.env` is git-ignored and never committed.
