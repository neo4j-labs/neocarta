#!/usr/bin/env bash
# Provisions a per-example Databricks Neo4j secret scope for each integration
# under examples/.
#
# For every example the script reads the scope name from that example's
# committed dbxcarta-overlay.env (DATABRICKS_SECRET_SCOPE, the single source of
# truth) and writes NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD into it from the
# gitignored standalone .env. Each example may target a different workspace, so
# the scope is created with that example's own DATABRICKS_PROFILE unless
# --profile overrides it.
#
# Usage:
#   ./setup_secrets.sh [--profile NAME] [--example NAME ...]
#
#   --profile NAME   Use this Databricks profile for every example, overriding
#                    the DATABRICKS_PROFILE in each example .env.
#   --example NAME   Provision only examples/NAME. Repeatable.
#
# Per example the script reads:
#   dbxcarta-overlay.env  DATABRICKS_SECRET_SCOPE  required (else skipped)
#   .env  DATABRICKS_PROFILE  optional, used when --profile is not provided
#   .env  NEO4J_URI           required to provision (absent => example skipped)
#   .env  NEO4J_USERNAME      required
#   .env  NEO4J_PASSWORD      required
#
# Secret key names are uppercase by design. They match the keys read by the
# Databricks jobs and databricks-job-runner secret injection.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES_DIR="${ROOT_DIR}/examples"
PROFILE_OVERRIDE=""
ONLY_EXAMPLES=()

# ENV_FILE is set per example in the loop; the parsing helpers read it.
ENV_FILE=""

usage() {
  sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

env_value() {
  local key="$1"
  local line raw_key raw_value value

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(trim "$line")"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == export\ * ]] && line="$(trim "${line#export }")"
    [[ "$line" != *=* ]] && continue

    raw_key="$(trim "${line%%=*}")"
    [[ "$raw_key" != "$key" ]] && continue

    raw_value="$(trim "${line#*=}")"
    if [[ "$raw_value" == \"*\" && "$raw_value" == *\" ]]; then
      value="${raw_value:1:${#raw_value}-2}"
    elif [[ "$raw_value" == \'*\' && "$raw_value" == *\' ]]; then
      value="${raw_value:1:${#raw_value}-2}"
    else
      value="$raw_value"
    fi
    printf '%s' "$value"
    return 0
  done < "$ENV_FILE"

  return 1
}

is_placeholder() {
  local value="$1"
  [[ -z "$value" || "$value" == *\<* || "$value" == *\>* ]]
}

required_env() {
  local key="$1"
  local value
  value="$(env_value "$key" || true)"
  if is_placeholder "$value"; then
    echo "Error: $key is not set in $ENV_FILE." >&2
    exit 1
  fi
  printf '%s' "$value"
}

ensure_scope() {
  local scope="$1"
  local output rc

  set +e
  output="$(databricks secrets create-scope "$scope" 2>&1)"
  rc=$?
  set -e

  if [[ "$rc" -eq 0 ]]; then
    echo "  created scope: $scope"
  elif [[ "$output" == *"already exists"* || "$output" == *"RESOURCE_ALREADY_EXISTS"* ]]; then
    echo "  scope exists:  $scope"
  else
    echo "Error creating scope $scope: $output" >&2
    exit 1
  fi
}

put_secret() {
  local scope="$1"
  local key="$2"
  local value="$3"
  printf '    - %s/%s\n' "$scope" "$key"
  databricks secrets put-secret "$scope" "$key" --string-value "$value"
}

wants_example() {
  local name="$1"
  [[ ${#ONLY_EXAMPLES[@]} -eq 0 ]] && return 0
  local want
  for want in "${ONLY_EXAMPLES[@]}"; do
    [[ "$want" == "$name" ]] && return 0
  done
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile)
      [[ $# -lt 2 ]] && { echo "Error: --profile requires a value." >&2; exit 1; }
      PROFILE_OVERRIDE="$2"
      shift 2
      ;;
    -e|--example)
      [[ $# -lt 2 ]] && { echo "Error: --example requires a value." >&2; exit 1; }
      ONLY_EXAMPLES+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v databricks >/dev/null 2>&1; then
  echo "Error: databricks CLI not found." >&2
  exit 1
fi

if [[ ! -d "$EXAMPLES_DIR" ]]; then
  echo "Error: $EXAMPLES_DIR not found." >&2
  exit 1
fi

provisioned=0
for dir in "$EXAMPLES_DIR"/*/; do
  name="$(basename "$dir")"
  wants_example "$name" || continue

  echo
  echo "=== $name ==="

  # The committed overlay is the single source of the scope name.
  overlay="${dir}dbxcarta-overlay.env"
  if [[ ! -f "$overlay" ]]; then
    echo "  skip: ${overlay} not found (committed overlay missing)"
    continue
  fi
  ENV_FILE="$overlay"
  scope="$(env_value DATABRICKS_SECRET_SCOPE || true)"
  if is_placeholder "$scope"; then
    echo "  skip: DATABRICKS_SECRET_SCOPE not set in $overlay"
    continue
  fi

  # Secrets live only in the gitignored standalone .env.
  ENV_FILE="${dir}.env"
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "  skip: ${ENV_FILE} not found (copy .env.sample to .env and fill in NEO4J_* values)"
    continue
  fi

  uri="$(env_value NEO4J_URI || true)"
  if is_placeholder "$uri"; then
    echo "  skip: NEO4J_URI not set in $ENV_FILE"
    continue
  fi

  profile="${PROFILE_OVERRIDE:-$(env_value DATABRICKS_PROFILE || true)}"
  if is_placeholder "$profile"; then
    echo "  skip: no DATABRICKS_PROFILE in $ENV_FILE and no --profile given" >&2
    continue
  fi
  export DATABRICKS_CONFIG_PROFILE="$profile"

  username="$(required_env NEO4J_USERNAME)"
  password="$(required_env NEO4J_PASSWORD)"

  echo "  profile:       $profile"
  echo "  scope:         $scope (from overlay)"
  ensure_scope "$scope"
  put_secret "$scope" "NEO4J_URI" "$uri"
  put_secret "$scope" "NEO4J_USERNAME" "$username"
  put_secret "$scope" "NEO4J_PASSWORD" "$password"
  provisioned=$((provisioned + 1))
done

echo
if [[ "$provisioned" -eq 0 ]]; then
  echo "No examples provisioned."
  if [[ ${#ONLY_EXAMPLES[@]} -gt 0 ]]; then
    echo "Checked: ${ONLY_EXAMPLES[*]}"
    exit 1
  fi
else
  echo "Done. Provisioned $provisioned example scope(s)."
  echo "Jobs read these with dbutils.secrets.get(scope, key)."
fi
