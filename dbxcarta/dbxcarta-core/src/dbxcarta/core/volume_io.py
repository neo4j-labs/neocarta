"""Shared UC Volume I/O helpers used across the stages.

The summary emitters (ingest, client, materialize) all write a JSON file under a
UC Volume FUSE path, and the host-side tools (preset question upload, materialize
blueprint staging) all push a local file to a Volume through the Files API. Both
patterns were copy-pasted per stage; this module is their single home so the
managed-prefix depth rule and the upload contract live in one place.

Core stays SDK-light: the ``WorkspaceClient`` type is only referenced under
``TYPE_CHECKING`` and the SDK error is imported inside the function that needs
it, so importing this module pulls in neither the SDK nor PySpark.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from databricks.sdk import WorkspaceClient


def ensure_volume_subdirs(dirpath: Path) -> None:
    """Create the directories needed to write a file at ``dirpath``.

    A UC Volume exposes a FUSE mount whose managed prefix
    (``/Volumes/<catalog>/<schema>/<volume>``) is provisioned by ``CREATE
    VOLUME`` and rejects a ``parents=True`` mkdir (errno 95). Only the subpath
    levels below that prefix (depth >= 6) are created, one at a time. A
    non-Volumes path takes the ordinary recursive mkdir.
    """
    parts = dirpath.parts
    if len(parts) > 1 and parts[1] == "Volumes":
        from pathlib import Path as _Path

        for depth in range(6, len(parts) + 1):
            _Path(*parts[:depth]).mkdir(exist_ok=True)
    else:
        dirpath.mkdir(parents=True, exist_ok=True)


def ensure_volume_parent_dir(ws: WorkspaceClient, dest: str) -> None:
    """Best-effort create the parent directory of a ``/Volumes/...`` dest path.

    Uses the Files API (the host-side tools have no FUSE mount). ``create_directory``
    is recursive, and an already-present directory is suppressed, so this is
    idempotent.
    """
    from databricks.sdk.errors import ResourceAlreadyExists

    parent = dest.rsplit("/", 1)[0]
    with contextlib.suppress(ResourceAlreadyExists):
        ws.files.create_directory(parent)


def upload_file_to_volume(ws: WorkspaceClient, local: Path, dest: str) -> None:
    """Upload a local file to a UC Volume path, creating the parent dir first."""
    ensure_volume_parent_dir(ws, dest)
    with local.open("rb") as fh:
        ws.files.upload(file_path=dest, contents=fh, overwrite=True)


def load_json_file(path: Path, *, label: str) -> Any:
    """Read and parse a JSON file, raising ``ValueError`` on malformed JSON.

    ``label`` names the artifact in the error message (e.g. "blueprint",
    "questions file"). A missing file surfaces as the usual ``FileNotFoundError``
    from ``read_text``; callers that want a friendlier message check existence
    first.
    """
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
