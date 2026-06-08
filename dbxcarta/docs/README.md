# Documentation

The docs tree is organized by purpose:

- `assets/` — the graph-schema diagram (`graph-schema.png` and its editable
  `graph-schema.excalidraw` source).
- `reference/` — stable technical references for the current codebase:
  - `architecture.md` — the semantic-layer thesis, the three storage planes,
    and the validation model (canonical architecture reference).
  - `pipeline.md` — plain-English, stage-by-stage walkthrough of the Spark build.
  - `best-practices.md` — the authoritative pipeline design rules, with sources,
    plus operational lessons.
  - `design-decisions.md` — deliberate trade-offs (key-like columns, foreign-key
    discovery order).
  - `public-api.md` — per-distribution public surfaces and the import migration table.
- `schema/SCHEMA.md` — the normative graph contract (nodes, relationships,
  identifiers, embeddings, versioning).
- `security/supply-chain.md` — supply-chain and security reference material.
