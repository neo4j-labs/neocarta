#!/usr/bin/env python3
"""Inspect package artifacts and write build provenance.

The checks are intentionally standard-library only so they can run in CI before
optional security scanners are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DENIED_PATH_PARTS = frozenset(
    {
        ".codex",
        ".git",
        ".github",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "outputs",
        "venv",
        "wheels",
        "worklog",
    }
)

DENIED_FILE_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".mcp.json",
        "credentials.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "token.json",
    }
)

DENIED_SUFFIXES = (
    ".crt",
    ".key",
    ".p12",
    ".pem",
    ".pyc",
    ".pyo",
)

DENIED_NAME_FRAGMENTS = ("credential", "secret")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="inspect wheel and sdist contents",
    )
    inspect_parser.add_argument(
        "dist",
        type=Path,
        help="directory containing built artifacts",
    )

    provenance_parser = subparsers.add_parser(
        "provenance",
        help="write artifact provenance JSON",
    )
    provenance_parser.add_argument(
        "dist",
        type=Path,
        help="directory containing built artifacts",
    )
    provenance_parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/supply-chain-provenance.json"),
        help="provenance JSON output path",
    )

    args = parser.parse_args()
    if args.command == "inspect":
        return inspect(args.dist)
    if args.command == "provenance":
        return write_provenance(args.dist, args.output)
    parser.error(f"unknown command: {args.command}")
    return 2


def inspect(dist: Path) -> int:
    artifacts = find_artifacts(dist)
    errors: list[str] = []
    for artifact in artifacts:
        errors.extend(inspect_artifact(artifact))

    if errors:
        print("Artifact inspection failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Artifact inspection passed for {len(artifacts)} artifact(s).")
    return 0


def write_provenance(dist: Path, output: Path) -> int:
    artifacts = find_artifacts(dist)
    output.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "project": read_project_metadata(Path("pyproject.toml")),
        "source": {
            "git_commit": git(["rev-parse", "HEAD"]),
            "git_dirty": git_dirty(),
            "lockfile_sha256": sha256_file(Path("uv.lock")) if Path("uv.lock").exists() else None,
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "uv_version": uv_version(),
        },
        "artifacts": [artifact_metadata(path) for path in artifacts],
    }

    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote provenance for {len(artifacts)} artifact(s): {output}")
    return 0


def find_artifacts(dist: Path) -> list[Path]:
    if not dist.exists():
        raise SystemExit(f"artifact directory does not exist: {dist}")
    artifacts = sorted([*dist.glob("*.whl"), *dist.glob("*.tar.gz")])
    if not artifacts:
        raise SystemExit(f"no wheel or source distribution artifacts found in {dist}")
    return artifacts


def inspect_artifact(path: Path) -> list[str]:
    errors: list[str] = []
    for member in artifact_members(path):
        reason = denied_reason(member)
        if reason:
            errors.append(f"{path.name}: {member} ({reason})")
    return errors


def artifact_members(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return [info.filename for info in archive.infolist() if not info.is_dir()]
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return [member.name for member in archive.getmembers() if member.isfile()]
    raise SystemExit(f"unsupported artifact type: {path}")


def denied_reason(member: str) -> str | None:
    normalized = member.replace("\\", "/")
    if normalized.startswith("/") or "/../" in f"/{normalized}/":
        return "unsafe archive path"

    parts = [part for part in normalized.split("/") if part]
    lowered_parts = [part.lower() for part in parts]
    basename = lowered_parts[-1] if lowered_parts else ""

    denied_part = DENIED_PATH_PARTS.intersection(lowered_parts)
    if denied_part:
        return f"development-only path part: {sorted(denied_part)[0]}"

    if basename in DENIED_FILE_NAMES:
        return f"denied filename: {basename}"

    if basename.startswith(".env."):
        return "environment file"

    if basename.endswith(DENIED_SUFFIXES):
        return "sensitive or generated file suffix"

    for fragment in DENIED_NAME_FRAGMENTS:
        if fragment in basename:
            return f"sensitive filename fragment: {fragment}"

    return None


def artifact_metadata(path: Path) -> dict[str, Any]:
    return {
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "members": len(artifact_members(path)),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_project_metadata(pyproject: Path) -> dict[str, str | None]:
    name: str | None = None
    version: str | None = None
    if not pyproject.exists():
        return {"name": None, "version": None}

    in_project = False
    for raw_line in pyproject.read_text().splitlines():
        line = raw_line.strip()
        if line == "[project]":
            in_project = True
            continue
        if in_project and line.startswith("["):
            break
        if in_project and line.startswith("name = "):
            name = line.split("=", 1)[1].strip().strip('"')
        if in_project and line.startswith("version = "):
            version = line.split("=", 1)[1].strip().strip('"')
    return {"name": name, "version": version}


def git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def git_dirty() -> bool | None:
    value = git(["status", "--porcelain"])
    if value is None:
        return None
    return bool(value)


def uv_version() -> str | None:
    try:
        result = subprocess.run(
            ["uv", "--version"],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "UV_NO_PROGRESS": "1"},
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


if __name__ == "__main__":
    raise SystemExit(main())
