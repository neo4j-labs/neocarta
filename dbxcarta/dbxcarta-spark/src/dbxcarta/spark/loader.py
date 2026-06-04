"""Resolve a preset object from a `module.path:attr` import spec."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from dbxcarta.core.presets import Preset


def load_preset(spec: str) -> Preset:
    """Resolve a `package.module:attr` spec to a preset object.

    Raises ValueError if the spec is malformed, ImportError if the module
    cannot be imported, and AttributeError if the attribute does not exist.
    The operational CLI then checks for the optional capabilities it needs
    (readiness, upload_questions); per-example config comes from the committed
    dbxcarta-overlay.env, not the preset.
    """
    module_path, sep, attr = spec.partition(":")
    if not sep or not module_path or not attr:
        raise ValueError(f"invalid preset spec {spec!r}: expected 'module.path:attr'")
    module = importlib.import_module(module_path)
    return cast("Preset", getattr(module, attr))
