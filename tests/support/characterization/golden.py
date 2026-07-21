"""Golden-file comparison for the characterization harness.

Goldens are plain JSON committed next to the test that owns them: canonical form is
``json.dumps(indent=2, sort_keys=True, ensure_ascii=False)`` plus a trailing newline,
so a diff is human-reviewable and stable across the CI Python-version matrix. There is
no snapshot-library dependency — stdlib ``json`` + ``difflib`` only.

Regeneration is opt-in and explicit: set ``UPDATE_GOLDENS=1``. The harness never
writes a golden on comparison failure.
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import Any

_ENV_FLAG = "UPDATE_GOLDENS"
_TRUTHY = frozenset({"1", "true", "yes"})


def canonical_json(data: Any) -> str:
    """Serialize ``data`` to the canonical golden form (sorted keys, 2-space indent)."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _should_update(update: bool | None) -> bool:
    """Resolve whether to regenerate: explicit ``update`` wins over the env flag."""
    if update is not None:
        return update
    return os.environ.get(_ENV_FLAG, "").strip().lower() in _TRUTHY


def assert_matches_golden(path: str | Path, data: Any, *, update: bool | None = None) -> None:
    """Assert ``data`` matches the committed golden at ``path`` (else raise).

    Args:
        path: The golden file path.
        data: The JSON-serializable snapshot to compare.
        update: Force-regenerate (``True``) or force-compare (``False``); when
            ``None``, the ``UPDATE_GOLDENS`` env flag decides. Meta-tests pass an
            explicit value so a repo-wide regeneration run cannot subvert them.

    Raises:
        AssertionError: If the golden is missing (and not updating) or differs.
    """
    path = Path(path)
    payload = canonical_json(data)

    if _should_update(update):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return

    if not path.exists():
        raise AssertionError(
            f"Golden file missing: {path}\n"
            "Generate it with UPDATE_GOLDENS=1 (or --update-goldens) and commit it."
        )

    expected = path.read_text(encoding="utf-8")
    if expected != payload:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                payload.splitlines(keepends=True),
                fromfile=f"{path.name} (committed golden)",
                tofile=f"{path.name} (current output)",
            )
        )
        raise AssertionError(
            f"Characterization mismatch for {path}:\n{diff}\n"
            "If this change is intentional, regenerate with UPDATE_GOLDENS=1 and review the diff."
        )
