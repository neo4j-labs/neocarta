"""Single-shot embedding diagnostic.

Exercises the embedding endpoint with one input (or N copies) and reports
success, vector length, and any error. Use this for a sub-second check that
the endpoint works, instead of inferring it from a full client eval run.

Usage:
    dbxcarta-embed-probe "how many accounts are active?"
    dbxcarta-embed-probe --count 150 "ping"
    dbxcarta-embed-probe --endpoint databricks-gte-large-en "question text"
"""

from __future__ import annotations

import argparse
import os
import sys

from dbxcarta.client.embed import embed_questions
from dbxcarta.core.workspace import build_workspace_client

_DEFAULT_ENDPOINT = "databricks-gte-large-en"


def _resolve_endpoint(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    return os.environ.get("DBXCARTA_EMBEDDING_ENDPOINT") or _DEFAULT_ENDPOINT


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dbxcarta-embed-probe",
        description="Embed one text (or N copies) against the embedding endpoint.",
    )
    parser.add_argument("text", help="Text to embed.")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Send N copies of the text in one call to probe the batch path.",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Serving endpoint name. Defaults to DBXCARTA_EMBEDDING_ENDPOINT, "
        "then databricks-gte-large-en.",
    )
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be >= 1")

    endpoint = _resolve_endpoint(args.endpoint)
    ws = build_workspace_client()
    texts = [args.text] * args.count

    print(f"endpoint: {endpoint}")
    print(f"inputs:   {len(texts)}")

    embeddings, error = embed_questions(ws, endpoint, texts)

    if embeddings is None:
        print("result:   FAILED")
        print(f"error:    {error}")
        sys.exit(1)

    print("result:   OK")
    print(f"vectors:  {len(embeddings)}")
    print(f"dim:      {len(embeddings[0]) if embeddings else 0}")
    head = embeddings[0][:5] if embeddings else []
    print(f"head[0]:  {head}")


if __name__ == "__main__":
    main()
