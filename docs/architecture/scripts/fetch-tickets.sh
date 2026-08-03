#!/usr/bin/env bash
#
# fetch-tickets.sh — pull the Production Refactor board into JSON + a compact TSV.
#
# This is the data step behind target-state.md's traceability matrix: it snapshots
# every item in GitHub Project 12 (title, number, release band, change-type, status,
# labels) so the target-state delta can be re-derived when the board changes.
#
# Prerequisites: an authenticated `gh` CLI + `jq`.
# Usage:  docs/architecture/scripts/fetch-tickets.sh [OUTPUT_DIR]   (default: /tmp)
#
set -euo pipefail

OWNER="neo4j-labs"
PROJECT=12
OUT="${1:-/tmp}"
mkdir -p "$OUT"

JSON="$OUT/proj${PROJECT}_items.json"
TSV="$OUT/proj${PROJECT}_items.tsv"

gh project item-list "$PROJECT" --owner "$OWNER" --format json --limit 500 > "$JSON"
echo "items: $(jq '.items | length' "$JSON")  → $JSON"

# number | granularity | release | change-type | status | labels | title
jq -r '.items[] | [.content.number, .granularity, .release, ."change Type", .status, (.labels | join(",")), .title] | @tsv' \
   "$JSON" > "$TSV"
echo "wrote $TSV"

echo "== distribution by release band =="
jq -r '.items[].release // "none"' "$JSON" | sort | uniq -c | sort -rn
echo "== distribution by granularity =="
jq -r '.items[].granularity // "none"' "$JSON" | sort | uniq -c | sort -rn

# Note: project items had zero comments at authoring time. If that changes, pull
# per-issue detail with:  gh issue view <n> --repo neo4j-labs/neocarta --json body,comments
