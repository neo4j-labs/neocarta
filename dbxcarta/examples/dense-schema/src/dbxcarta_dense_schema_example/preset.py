"""dbxcarta preset for this example.

Per-example dbxcarta config lives in the committed dbxcarta-overlay.env beside
this example, and the bundled questions.json is the only per-example data. The
shared StandardPreset provides the readiness check and the question upload, so
every example's preset is the same.

Resolvable via:
    uv run dbxcarta preset <package>:preset --check-ready
    uv run dbxcarta preset <package>:preset --upload-questions
"""

from __future__ import annotations

from pathlib import Path

from dbxcarta.core.presets import StandardPreset

preset = StandardPreset(questions_file=Path(__file__).resolve().parents[2] / "questions.json")

__all__ = ["preset"]
