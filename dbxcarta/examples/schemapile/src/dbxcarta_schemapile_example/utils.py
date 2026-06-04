"""Shared entrypoint helpers for the SchemaPile example."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def load_dotenv_file(path: Path) -> None:
    """Load a dotenv file when python-dotenv is installed and the file exists."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        logging.getLogger(__name__).warning(
            "python-dotenv is not installed; %s was not loaded and "
            "configuration will come from the process environment only",
            path,
        )
        return
    if path.is_file():
        load_dotenv(path, override=False)
