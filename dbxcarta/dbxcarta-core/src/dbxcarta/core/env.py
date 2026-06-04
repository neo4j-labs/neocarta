"""Env-file overlay resolution and cluster bootstrap helpers.

Per-example config is supplied as an ``--env-file`` overlay layered over the
base ``.env`` (see :func:`resolve_env_files`). On the cluster, the runner
forwards those values as ``KEY=VALUE`` args parsed by :func:`inject_params`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_ENV_FILE_KEY = "DBXCARTA_ENV_FILE"
_ENV_FILE_OPT = "--env-file"
_BASE_ENV_FILE = Path(".env")

# Default bounded driver-pool size for the materialize Spark job. The job
# overlaps the independent CREATE TABLE statements in a ThreadPoolExecutor of
# this size; the foreign-key pass stays serial after it.
_DEFAULT_MATERIALIZE_WORKERS = 5


class EnvFileError(Exception):
    """A selected env overlay file could not be resolved.

    Raised only for an *explicitly selected* overlay (``--env-file`` or
    ``DBXCARTA_ENV_FILE``). A missing base ``.env`` is not an error: it
    preserves the historical no-overlay behaviour where ``load_dotenv``
    silently no-ops on a missing file.
    """


def resolve_env_files(argv: list[str]) -> tuple[list[Path], list[str]]:
    """Resolve the ordered env files to load and strip the CLI option.

    Returns ``(files, cleaned_argv)`` where *files* is overlay-then-base
    so a sequence of ``load_dotenv(f, override=False)`` calls yields the
    required precedence: real process env over overlay over base. With no
    overlay selected the list is just the base ``.env``, which reproduces
    today's behaviour exactly.

    The overlay is selected from ``--env-file`` on *argv*, else the
    ``DBXCARTA_ENV_FILE`` environment variable. When both are set the
    ``--env-file`` CLI option wins. A selected overlay that does not
    resolve to a readable file is a hard :class:`EnvFileError`; it never
    silently falls back to a base-only run.
    """
    selected, cleaned_argv = _select_overlay(argv)
    if selected is None:
        return [_BASE_ENV_FILE], cleaned_argv

    overlay = Path(selected)
    if not overlay.is_file():
        raise EnvFileError(
            f"selected env overlay {str(overlay)!r} does not exist or is "
            "not a readable file. Fix the path or unset the selection; "
            "the run is not silently continued on the base .env alone."
        )
    return [overlay, _BASE_ENV_FILE], cleaned_argv


def _select_overlay(argv: list[str]) -> tuple[str | None, list[str]]:
    """Resolve the selected overlay value and strip the CLI option.

    ``--env-file`` on *argv* wins over the ``DBXCARTA_ENV_FILE``
    environment variable. Returns ``(value_or_None, cleaned_argv)``. A
    bare or empty ``--env-file`` is a hard :class:`EnvFileError`, since
    silently ignoring a malformed selection reintroduces the
    wrong-catalog risk.
    """
    cli_value, cleaned_argv = _extract_env_file_option(argv)
    selected = cli_value
    if selected is None:
        selected = os.environ.get(_ENV_FILE_KEY) or None
    return selected, cleaned_argv


def _extract_env_file_option(argv: list[str]) -> tuple[str | None, list[str]]:
    """Pull ``--env-file VALUE`` / ``--env-file=VALUE`` out of *argv*.

    The option is stripped so the per-command argparse parsers never
    see it.
    """
    value: str | None = None
    remaining: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == _ENV_FILE_OPT:
            if i + 1 >= len(argv):
                raise EnvFileError(f"{_ENV_FILE_OPT} requires a path argument")
            value = argv[i + 1]
            i += 2
            continue
        if arg.startswith(f"{_ENV_FILE_OPT}="):
            value = arg.split("=", 1)[1]
            i += 1
            continue
        remaining.append(arg)
        i += 1
    if value is not None and not value:
        raise EnvFileError(f"{_ENV_FILE_OPT} requires a non-empty path argument")
    return value, remaining


def select_overlay_path(argv: list[str] | None = None) -> Path | None:
    """Return the selected overlay path, or ``None``, without side effects.

    Pure selection for the stderr banner and runner construction: it
    does not strip argv, load files, or check existence. Existence is
    enforced downstream by :func:`resolve_env_files` (the
    ``verify``/``preset`` loader) and by the runner's ``from_env_file``
    (the submit path), so a nonexistent overlay is still a hard error
    wherever it is actually consumed. A malformed ``--env-file`` is
    swallowed here so the consuming path raises the clean error.
    """
    args = sys.argv[1:] if argv is None else argv
    try:
        selected, _ = _select_overlay(args)
    except EnvFileError:
        return None
    return Path(selected) if selected else None


def load_env_files(files: list[Path]) -> None:
    """Load *files* in order with ``override=False``.

    *files* is overlay-then-base from :func:`resolve_env_files`. With
    ``override=False`` the first writer of each key wins, so loading
    overlay first makes the overlay beat the base, and any value already
    exported in the real process environment beats both. A missing file
    is a silent no-op, matching ``python-dotenv`` semantics and today's
    no-overlay behaviour for the base ``.env``.
    """
    from dotenv import load_dotenv

    for env_file in files:
        load_dotenv(env_file, override=False)


def inject_params() -> None:
    """Parse KEY=VALUE argv parameters into os.environ.

    The CLI runner forwards .env variables as positional KEY=VALUE args.
    Uses setdefault so pre-existing environment variables take precedence,
    matching standard 12-factor semantics.
    """
    remaining: list[str] = []
    for arg in sys.argv[1:]:
        if "=" in arg and not arg.startswith("-"):
            key, _, value = arg.partition("=")
            os.environ.setdefault(key, value)
        else:
            remaining.append(arg)
    sys.argv[1:] = remaining


def read_required_warehouse_id(
    override: str | None,
    *,
    operation: str,
    extra_hint: str = "",
) -> str:
    """Return the SQL warehouse id from a CLI override or the environment.

    ``override`` (a ``--warehouse-id`` flag value) wins when set; otherwise the
    value comes from ``DATABRICKS_WAREHOUSE_ID``. Raises ``ValueError`` naming
    ``operation`` when neither yields a non-blank id, with ``extra_hint``
    appended when a caller has an additional escape (for example
    ``--skip-validate``).
    """
    warehouse_id = (override or os.environ.get("DATABRICKS_WAREHOUSE_ID", "")).strip()
    if not warehouse_id:
        hint = f" {extra_hint}" if extra_hint else ""
        raise ValueError(
            f"DATABRICKS_WAREHOUSE_ID is required for {operation};"
            f" set it in .env or pass --warehouse-id{hint}"
        )
    return warehouse_id


def read_materialize_workers(env: Mapping[str, str] | None = None) -> int:
    """Return the bounded materialize table-build worker count.

    Sourced from ``DBXCARTA_MATERIALIZE_WORKERS`` (default 5). A blank value
    uses the default; a non-integer or a value ``< 1`` fails loudly, since a
    driver pool needs at least one worker. The materialize Spark job reads this
    to size the ThreadPoolExecutor that overlaps the per-table ``CREATE``s.
    """
    source = os.environ if env is None else env
    raw = source.get("DBXCARTA_MATERIALIZE_WORKERS", "").strip()
    if not raw:
        return _DEFAULT_MATERIALIZE_WORKERS
    try:
        workers = int(raw)
    except ValueError:
        raise ValueError(f"DBXCARTA_MATERIALIZE_WORKERS must be an integer (got {raw!r})") from None
    if workers < 1:
        raise ValueError(f"DBXCARTA_MATERIALIZE_WORKERS must be >= 1 (got {workers})")
    return workers
