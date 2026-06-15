# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "databricks-sdk>=0.40",
#     "python-dotenv>=1.0",
# ]
# ///
"""Create a Databricks External Model serving endpoint that proxies OpenAI.

"External Model" is the Databricks Mosaic AI Model Serving term for a serving
endpoint that proxies an outside provider. This script registers one that proxies
OpenAI ``text-embedding-3-small`` (1536 dimensions) and exposes it under an
ordinary Databricks serving-endpoint name, callable with
``ai_query('<endpoint>', text)`` from SQL or Spark just like a native Databricks
model.

The Databricks connector's inline embedding mode calls
``ai_query('<endpoint>', ...)`` against a serving endpoint. Pointing
``NEOCARTA_DATABRICKS_EMBEDDING_ENDPOINT`` at the endpoint this script creates is
what makes inline embeddings run on OpenAI instead of a native Databricks model,
so they match an OpenAI-based neocarta graph. See the "Registering the OpenAI
endpoint (manual step)" section of ``neocarta/connectors/databricks/README.md``.

What it does:

* Creates the External Model serving endpoint (provider OpenAI, task
  ``llm/v1/embeddings``), reading the OpenAI key from a Databricks secret. The
  key value is never read locally. The endpoint stores a reference to the secret
  and authenticates to OpenAI itself at query time, so the key never appears in
  the connector run or the ingest notebook.
* Probes the endpoint through the same ``ai_query`` SQL path the connector uses
  and asserts the returned vector dimension.

Provision the OpenAI secret first, for example::

    databricks secrets create-scope neocarta-openai
    databricks secrets put-secret neocarta-openai OPENAI_API_KEY

Usage::

    uv run scripts/setup_openai_external_model_endpoint.py --profile <profile>

    # custom names / explicit warehouse for the probe
    uv run scripts/setup_openai_external_model_endpoint.py -p <profile> \
        --endpoint-name openai-text-embedding-3-small \
        --secret-scope neocarta-openai --secret-key OPENAI_API_KEY \
        --warehouse-id 1234567890abcdef

    # create only, skip the SQL dimension probe
    uv run scripts/setup_openai_external_model_endpoint.py -p <profile> --skip-verify
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    ExternalModel,
    ExternalModelProvider,
    OpenAiConfig,
    ServedEntityInput,
)
from databricks.sdk.service.sql import StatementState
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent

# Defaults match the connector README's recommendation for matching an
# OpenAI-based neocarta graph: text-embedding-3-small at 1536 dimensions.
DEFAULT_ENDPOINT_NAME = "openai-text-embedding-3-small"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_SECRET_SCOPE = "neocarta-openai"  # noqa: S105  scope NAME, not a secret value
DEFAULT_SECRET_KEY = "OPENAI_API_KEY"  # noqa: S105  key NAME, not a secret value
DEFAULT_DIMENSION = 1536
# Any text works for the probe; the vector length is what the check reads.
DEFAULT_PROBE_TEXT = "accounts grouped into detected fraud rings"
EMBEDDINGS_TASK = "llm/v1/embeddings"


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and verify the OpenAI external-models embedding endpoint.",
    )
    parser.add_argument(
        "-p",
        "--profile",
        required=True,
        help="Databricks profile from ~/.databrickscfg.",
    )
    parser.add_argument(
        "--endpoint-name",
        default=DEFAULT_ENDPOINT_NAME,
        help=f"Serving endpoint name to create. Default: {DEFAULT_ENDPOINT_NAME}.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI embedding model id. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--secret-scope",
        default=DEFAULT_SECRET_SCOPE,
        help=f"Databricks secret scope holding the OpenAI key. Default: {DEFAULT_SECRET_SCOPE}.",
    )
    parser.add_argument(
        "--secret-key",
        default=DEFAULT_SECRET_KEY,
        help=f"Secret key name within the scope. Default: {DEFAULT_SECRET_KEY}.",
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=DEFAULT_DIMENSION,
        help=f"Expected embedding dimension to assert in the probe. Default: {DEFAULT_DIMENSION}.",
    )
    parser.add_argument(
        "--warehouse-id",
        default=None,
        help="SQL warehouse id for the dimension probe. Default: DATABRICKS_WAREHOUSE_ID "
        "from --env-file or repo-root .env, else the first available warehouse.",
    )
    parser.add_argument(
        "-e",
        "--env-file",
        default=None,
        type=Path,
        help="Optional env file read only to resolve DATABRICKS_WAREHOUSE_ID for the probe.",
    )
    parser.add_argument(
        "--probe-text",
        default=DEFAULT_PROBE_TEXT,
        help="Sample text embedded by the dimension probe.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Create the endpoint only; skip the dimension probe.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the create confirmation prompt.",
    )
    return parser.parse_args()


def confirm(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def endpoint_exists(client: WorkspaceClient, name: str) -> bool:
    try:
        client.serving_endpoints.get(name)
        return True
    except NotFound:
        return False


def secret_present(client: WorkspaceClient, scope: str, key: str) -> bool:
    """Return True when the scope exists and holds the key.

    Secret values are never readable; key names are, which is enough to give a
    helpful error before creating an endpoint whose secret reference would not
    resolve.
    """
    try:
        return any(meta.key == key for meta in client.secrets.list_secrets(scope))
    except NotFound:
        return False


def resolve_warehouse_id(
    cli_value: str | None, env_file: Path | None, client: WorkspaceClient
) -> str | None:
    if cli_value:
        return cli_value
    sources = [env_file] if env_file else []
    sources.append(REPO_ROOT / ".env")
    for source in sources:
        if source and source.is_file():
            value = (dotenv_values(source).get("DATABRICKS_WAREHOUSE_ID") or "").strip()
            if value:
                return value
    warehouses = list(client.warehouses.list())
    return warehouses[0].id if warehouses else None


def query_scalar(client: WorkspaceClient, warehouse_id: str, statement: str) -> str | None:
    resp = client.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="50s",
    )
    statement_id = resp.statement_id
    state = resp.status.state if resp.status else None
    while state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        resp = client.statement_execution.get_statement(statement_id)
        state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        detail = ""
        if resp.status and resp.status.error:
            detail = f": {resp.status.error.message}"
        fail(f"dimension probe SQL failed ({state}){detail}\n  {statement}")
    rows = (resp.result.data_array if resp.result else None) or []
    if not rows or not rows[0]:
        return None
    return rows[0][0]


def create_endpoint(client: WorkspaceClient, args: argparse.Namespace, secret_ref: str) -> None:
    served = ServedEntityInput(
        name=args.endpoint_name,
        external_model=ExternalModel(
            name=args.model,
            provider=ExternalModelProvider.OPENAI,
            task=EMBEDDINGS_TASK,
            openai_config=OpenAiConfig(openai_api_key=secret_ref),
        ),
    )
    config = EndpointCoreConfigInput(name=args.endpoint_name, served_entities=[served])
    print(f"  creating endpoint {args.endpoint_name!r} (provider=openai, task={EMBEDDINGS_TASK})")
    print("  waiting for endpoint to become READY ...")
    try:
        details = client.serving_endpoints.create_and_wait(
            name=args.endpoint_name,
            config=config,
            timeout=timedelta(minutes=15),
        )
    except TimeoutError:
        fail("timed out waiting for endpoint to become READY; check the Serving UI")
    ready = details.state.ready if details.state else None
    print(f"  endpoint state: {ready}")


def verify_endpoint(
    client: WorkspaceClient, args: argparse.Namespace, warehouse_id: str | None
) -> None:
    details = client.serving_endpoints.get(args.endpoint_name)
    ready = details.state.ready if details.state else None
    print(f"  endpoint {args.endpoint_name!r} state: {ready}")

    if warehouse_id is None:
        print("  no SQL warehouse resolved; skipping the ai_query dimension probe.")
        print("  pass --warehouse-id to run it.")
        return

    # Single-quote the SQL string literals defensively: endpoint names are
    # constrained, but a custom --probe-text could contain a quote.
    safe_name = args.endpoint_name.replace("'", "''")
    safe_text = args.probe_text.replace("'", "''")
    statement = f"SELECT size(ai_query('{safe_name}', '{safe_text}')) AS dim"
    print(f"  running dimension probe on warehouse {warehouse_id}")
    raw = query_scalar(client, warehouse_id, statement)
    if raw is None:
        fail("dimension probe returned no rows")
    try:
        dim = int(raw)
    except (TypeError, ValueError):
        fail(f"dimension probe returned a non-integer result: {raw!r}")
    if dim != args.dimension:
        fail(
            f"dimension mismatch: endpoint returned {dim}-dim vectors, expected "
            f"{args.dimension}. Set NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION to {dim} "
            "or check the model."
        )
    print(f"  OK: endpoint returns {dim}-dim vectors (matches expected {args.dimension}).")


def main() -> None:
    args = parse_args()
    client = WorkspaceClient(profile=args.profile)
    secret_ref = f"{{{{secrets/{args.secret_scope}/{args.secret_key}}}}}"

    print(f"profile        : {args.profile}")
    print(f"endpoint name  : {args.endpoint_name}")
    print(f"openai model   : {args.model}")
    print(f"secret ref     : {secret_ref}")

    if not secret_present(client, args.secret_scope, args.secret_key):
        fail(
            f"secret {args.secret_key!r} not found in scope {args.secret_scope!r}. "
            "Provision it first, for example:\n"
            f"  databricks secrets create-scope {args.secret_scope}\n"
            f"  databricks secrets put-secret {args.secret_scope} {args.secret_key}"
        )

    if endpoint_exists(client, args.endpoint_name):
        print(f"\nendpoint {args.endpoint_name!r} already exists; skipping creation.")
    else:
        if not args.yes and not confirm(
            f"\nCreate serving endpoint {args.endpoint_name!r}? [y/N] "
        ):
            print("aborted.")
            return
        print("\ncreate endpoint")
        create_endpoint(client, args, secret_ref)

    if args.skip_verify:
        print("\nverify skipped (--skip-verify).")
        return

    print("\nverify")
    warehouse_id = resolve_warehouse_id(args.warehouse_id, args.env_file, client)
    verify_endpoint(client, args, warehouse_id)

    print("\ndone.")


if __name__ == "__main__":
    main()
