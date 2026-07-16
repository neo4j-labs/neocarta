"""Neocarta CLI.

Exposes the top-level ``cli`` Click group and the ``main`` console-script entry
point. See ``neocarta._cli.main`` for the command tree.
"""

from .main import cli, main

__all__ = ["cli", "main"]
