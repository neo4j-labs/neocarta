# Architecture-docs pipeline (scripts)

Reproduction scripts for the C4 architecture artifacts in [`docs/architecture/`](../).
They reconstruct the steps used to produce this documentation set and are the seed for
a future **automated documentation pipeline** (CI-rendered diagrams + board-derived
traceability).

## Contents

| Script | What it does | Prereqs |
|---|---|---|
| [`render-diagrams.sh`](render-diagrams.sh) | Validate + render every `*.mmd` (Mermaid) and `*.d2` (D2) source in `docs/architecture/` to `docs/architecture/rendered/*.svg`. Non-zero exit = a diagram failed to compile (so it doubles as a syntax check). | Node/`npx`; `curl`+`tar` (only if `d2` isn't on `PATH` — a pinned binary is fetched to `/tmp`, nothing installed system-wide). |
| [`fetch-tickets.sh`](fetch-tickets.sh) | Snapshot GitHub Project 12 (Production Refactor) to JSON + a compact TSV; print release-band / granularity distributions. Backs the traceability matrix in `target-state.md`. | Authenticated `gh` CLI; `jq`. |

## Usage

```bash
# from the repo root
docs/architecture/scripts/render-diagrams.sh
docs/architecture/scripts/fetch-tickets.sh          # writes to /tmp by default
docs/architecture/scripts/fetch-tickets.sh ./out    # or a chosen dir
```

## What's in `docs/architecture/`

- **Current state:** `current-context.mmd`, `current-containers.mmd`,
  `current-components-*.mmd`, and the prose doc `current-state.md`.
- **Target state:** `target-context.mmd`, `target-containers.d2`,
  `target-components-core-pipeline.d2`, `target-components-consumption.mmd`,
  `target-components-administration.mmd`, per-band overlays
  `target-containers-band-*.mmd`, and the prose doc `target-state.md` (with the
  ticket → change → source-path traceability matrix).
- **Rendered:** `rendered/*.svg` — pre-rendered D2 diagrams (Mermaid renders live in
  most markdown previews; D2 does not, so the two `.d2` views are embedded as SVG).
  **These are snapshots — re-run `render-diagrams.sh` after editing any `.d2`.**

## Format choices (why two tools)

Mermaid for everything that stays legible; **D2 for the dense views** (the target
container view and the core-pipeline component view), whose many-to-many
auth / observability / config edges render as spaghetti in Mermaid. See the density
readouts at the end of `current-state.md` and `target-state.md`.

## Later refinement (the "automated pipeline" goal)

- Wrap these in a `make` target (mirroring the existing `refresh-mermaid-*` targets in
  the root `Makefile`).
- Run `render-diagrams.sh` in CI on changes under `docs/architecture/**` to keep
  `rendered/` in sync and fail the build on invalid diagram syntax.
- Consider **Structurizr** (model-once, generate-many-views) if maintaining the current
  + target sets by hand across two renderers becomes a drift risk — noted in the
  `target-state.md` density readout.
