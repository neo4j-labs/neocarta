"""Workspace connection and secret helpers shared across dbxcarta layers."""

from __future__ import annotations

import base64
import os

from databricks.sdk import WorkspaceClient


def build_workspace_client() -> WorkspaceClient:
    """Build a WorkspaceClient from DATABRICKS_PROFILE or default SDK auth."""
    profile = os.environ.get("DATABRICKS_PROFILE")
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def read_workspace_secret(ws: WorkspaceClient, scope: str, key: str) -> str:
    """Fetch and base64-decode a workspace secret value.

    ``WorkspaceClient.secrets.get_secret`` returns the value base64-encoded,
    and ``.value`` is ``None`` when the secret is absent. Surface a missing
    secret as an explicit error rather than letting ``b64decode(None)`` raise
    an opaque ``TypeError`` deep in the call stack.
    """
    value = ws.secrets.get_secret(scope=scope, key=key).value
    if value is None:
        raise RuntimeError(f"secret {key!r} not found in scope {scope!r}")
    return base64.b64decode(value).decode()
