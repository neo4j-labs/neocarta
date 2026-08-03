#!/usr/bin/env bash
#
# render-diagrams.sh — validate + render every C4 architecture diagram to SVG.
#
# Renders all Mermaid (*.mmd) and D2 (*.d2) sources in docs/architecture/ into
# docs/architecture/rendered/*.svg. A non-zero exit means a diagram failed to
# compile — so this doubles as a syntax validator (used that way in the original
# authoring pass).
#
# Prerequisites:
#   - Node.js + npx (Mermaid runs via `npx @mermaid-js/mermaid-cli`, no global install)
#   - curl + tar   (only if `d2` is not already on PATH — a pinned binary is
#                    fetched to /tmp as a fallback; nothing is installed system-wide)
#
# Usage:  docs/architecture/scripts/render-diagrams.sh
#
set -euo pipefail

ARCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RENDERED="$ARCH_DIR/rendered"
mkdir -p "$RENDERED"

echo "== Mermaid =="
shopt -s nullglob
for f in "$ARCH_DIR"/*.mmd; do
  base="$(basename "${f%.mmd}")"
  echo "  render $base.mmd"
  npx -y -p @mermaid-js/mermaid-cli mmdc -i "$f" -o "$RENDERED/$base.svg" >/dev/null
done

# --- Resolve a d2 binary: prefer PATH, else fetch a pinned release to /tmp ---
D2_BIN="$(command -v d2 || true)"
if [ -z "$D2_BIN" ]; then
  D2_VER="v0.7.1"
  case "$(uname -m)" in arm64|aarch64) A=arm64 ;; x86_64) A=amd64 ;; *) A="$(uname -m)" ;; esac
  OS="$(uname -s | tr '[:upper:]' '[:lower:]')"; [ "$OS" = "darwin" ] && OS=macos
  D2_DIR="/tmp/d2-${D2_VER}"
  if [ ! -x "$D2_DIR/bin/d2" ]; then
    echo "  (fetching pinned d2 ${D2_VER} to /tmp — not on PATH)"
    curl -fsSL "https://github.com/terrastruct/d2/releases/download/${D2_VER}/d2-${D2_VER}-${OS}-${A}.tar.gz" -o "/tmp/d2-${D2_VER}.tar.gz"
    tar -xzf "/tmp/d2-${D2_VER}.tar.gz" -C /tmp
  fi
  D2_BIN="$D2_DIR/bin/d2"
fi

echo "== D2 ($D2_BIN) =="
for f in "$ARCH_DIR"/*.d2; do
  base="$(basename "${f%.d2}")"
  echo "  render $base.d2"
  "$D2_BIN" "$f" "$RENDERED/$base.svg" >/dev/null
done

echo "Done → $RENDERED"
