"""Slice runner: shell out to the upstream schemapile slice.py.

Reads slice parameters from `.env`, runs `uv run slice.py ...` inside the
upstream schemapile checkout, and writes the JSON output to the example's
local cache directory. Idempotent on the cache file when the requested
parameters have not changed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from dbxcarta_schemapile_example.config import SchemaPileConfig, load_config
from dbxcarta_schemapile_example.utils import load_dotenv_file

_UPSTREAM_REPO_URL = "https://github.com/amsterdata/schemapile"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dbxcarta-schemapile-slice",
        description="Produce a SchemaPile slice using the upstream slice.py.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run slice.py even when the cache file already matches the parameters.",
    )
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".env",
        help="Path to the .env file to load before reading variables (default: example directory .env)",
    )
    args = parser.parse_args()

    load_dotenv_file(args.dotenv)
    config = load_config()
    preflight(config)

    if not args.force and _cache_is_current(config):
        print(
            f"[schemapile] slice cache up to date: {config.slice_cache}",
            file=sys.stderr,
        )
        return 0

    return _run_slice(config)


def preflight(config: SchemaPileConfig) -> None:
    """Reject unusable configurations before any work happens."""
    if not config.repo.is_dir():
        raise FileNotFoundError(
            f"SCHEMAPILE_REPO={config.repo} is not a directory. Clone {_UPSTREAM_REPO_URL} first."
        )
    if not config.upstream_slice_script.is_file():
        raise FileNotFoundError(
            f"slice.py not found at {config.upstream_slice_script}."
            f" Confirm you cloned {_UPSTREAM_REPO_URL} into SCHEMAPILE_REPO."
        )
    if not config.input_path.is_file():
        raise FileNotFoundError(
            f"{config.input_path} is missing. Follow the {_UPSTREAM_REPO_URL}"
            " README to download the schemapile-perm.json artifact."
        )
    if shutil.which("uv") is None:
        raise RuntimeError(
            "uv is required to invoke slice.py via inline script metadata"
            " but was not found on PATH. Install uv (https://docs.astral.sh/uv/)."
        )


def _cache_is_current(config: SchemaPileConfig) -> bool:
    """True when the existing cache JSON was produced with the same params."""
    cache = config.slice_cache
    sidecar = _params_sidecar(cache)
    if not cache.is_file() or not sidecar.is_file():
        return False
    try:
        recorded = json.loads(sidecar.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return bool(recorded == _params_fingerprint(config))


def _params_fingerprint(config: SchemaPileConfig) -> dict[str, object]:
    """Stable subset of config that determines slice output identity."""
    return {
        "input": str(config.input_path),
        "input_size": config.input_path.stat().st_size,
        "target_tables": config.target_tables,
        "strategy": config.strategy,
        "seed": config.seed,
        "min_tables": config.min_tables,
        "max_tables": config.max_tables,
        "min_fk_edges": config.min_fk_edges,
        "require_self_contained": config.require_self_contained,
        "require_data": config.require_data,
    }


def _params_sidecar(cache: Path) -> Path:
    return cache.with_suffix(cache.suffix + ".params.json")


def _run_slice(config: SchemaPileConfig) -> int:
    config.slice_cache.parent.mkdir(parents=True, exist_ok=True)
    sidecar = _params_sidecar(config.slice_cache)
    args = [
        "uv",
        "run",
        str(config.upstream_slice_script),
        "--input",
        str(config.input_path),
        "--output",
        str(config.slice_cache.resolve()),
        "--target-tables",
        str(config.target_tables),
        "--strategy",
        config.strategy,
        "--seed",
        str(config.seed),
        "--min-tables",
        str(config.min_tables),
        "--max-tables",
        str(config.max_tables),
        "--min-fk-edges",
        str(config.min_fk_edges),
    ]
    if config.require_self_contained:
        args.append("--require-self-contained")
    if config.require_data:
        args.append("--require-data")

    print(f"[schemapile] running: {' '.join(args)}", file=sys.stderr)
    result = subprocess.run(args, cwd=config.repo, check=False)
    if result.returncode != 0:
        print(
            f"[schemapile] slice.py exited with code {result.returncode}",
            file=sys.stderr,
        )
        return result.returncode

    sidecar.write_text(json.dumps(_params_fingerprint(config), indent=2))
    print(
        f"[schemapile] slice written to {config.slice_cache} (params recorded in {sidecar.name})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
