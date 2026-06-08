"""``neocarta agent-context`` — machine-readable introspection for AI agents.

Emits the full CLI shape (commands, flags, exit codes, env vars) as a single
JSON object on stdout. The ``schema_version`` field increments on breaking
changes; field names below are part of the CLI's public contract.
"""

from __future__ import annotations

from typing import Any

import click

from .. import __version__
from .config import ENV_VARS
from .errors import EXIT_CODES
from .output import emit_json

SCHEMA_VERSION = 1


def _describe_command(cmd: click.Command, parent: click.Context | None) -> dict[str, Any]:
    """Recursively serialise a Click command into the agent-context schema."""
    ctx = click.Context(cmd, info_name=cmd.name, parent=parent)
    info: dict[str, Any] = {
        "description": (cmd.help or "").strip().splitlines()[0]
        if cmd.help
        else (cmd.short_help or ""),
    }

    flags: dict[str, dict[str, Any]] = {}
    for param in cmd.get_params(ctx):
        if not isinstance(param, click.Option):
            continue
        # Pick the longest --long-form as the canonical key.
        name = next(
            (opt for opt in param.opts if opt.startswith("--")),
            param.opts[0] if param.opts else param.name or "",
        )
        flags[name] = {
            "type": _flag_type(param),
            "default": param.default if not callable(param.default) else None,
            "required": bool(param.required),
            "help": (param.help or "").strip(),
        }
        if isinstance(param.type, click.Choice):
            flags[name]["choices"] = list(param.type.choices)
    if flags:
        info["flags"] = flags

    if isinstance(cmd, click.Group):
        subcommands: dict[str, dict[str, Any]] = {}
        for sub_name in cmd.list_commands(ctx):
            sub = cmd.get_command(ctx, sub_name)
            if sub is not None and not sub.hidden:
                subcommands[sub_name] = _describe_command(sub, ctx)
        if subcommands:
            info["subcommands"] = subcommands

    return info


def _flag_type(param: click.Option) -> str:
    """Best-effort serialisation of a Click parameter's type."""
    if param.is_flag:
        return "bool"
    if isinstance(param.type, click.Choice):
        return "enum"
    type_name = getattr(param.type, "name", None) or type(param.type).__name__
    return str(type_name).lower()


@click.command("agent-context")
@click.pass_context
def agent_context(ctx: click.Context) -> None:
    """Emit the full CLI shape as JSON for AI agents to read.

    The output includes the command tree, flags, exit codes, and recognised
    environment variables. ``schema_version`` increments on breaking changes.
    """
    root = ctx.find_root().command
    payload = {
        "schema_version": SCHEMA_VERSION,
        "cli_version": __version__,
        "commands": _describe_command(root, parent=None).get("subcommands", {}),
        "exit_codes": {
            name: {"code": meta["code"], "description": meta["description"]}
            for name, meta in EXIT_CODES.items()
        },
        "error_codes": list(EXIT_CODES.keys()),
        "env_vars": ENV_VARS,
        "output_formats": ["json", "table"],
    }
    emit_json(payload)
