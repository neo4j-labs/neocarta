"""Top-level Click entry point for the Neocarta CLI.

Run ``neocarta --help`` to see the command tree, or
``neocarta agent-context`` for the machine-readable shape used by AI agents.
"""

from __future__ import annotations

import click

from .. import __version__
from .agent_context import agent_context
from .commands.bigquery import bigquery
from .commands.csv import csv
from .commands.dataplex import dataplex
from .commands.query_log import query_log
from .output import make_consoles


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-v", "--version", prog_name="neocarta")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Default when stdout is not a TTY.",
)
@click.option("--debug", is_flag=True, default=False, help="Verbose diagnostics on stderr.")
@click.option("--no-color", is_flag=True, default=False, help="Suppress ANSI colors.")
@click.pass_context
def cli(ctx: click.Context, *, as_json: bool, debug: bool, no_color: bool) -> None:
    """Neocarta: build a semantic layer in Neo4j from your data sources.

    Run a connector with `neocarta <source> <verb>`, e.g.
    `neocarta bigquery schema --project-id my-proj --dataset-id my_dataset`
    or `neocarta bigquery logs --dataset-id my_dataset --limit 500
    --no-embeddings`. See `neocarta agent-context` for the full machine-
    readable command shape.
    """
    stdout, stderr = make_consoles(no_color=no_color)
    # stdout-not-a-TTY auto-enables JSON, per AGENTS-CLI §4.2.
    if not as_json and not stdout.is_terminal:
        as_json = True
    ctx.obj = {
        "as_json": as_json,
        "debug": debug,
        "no_color": no_color,
        "stdout": stdout,
        "stderr": stderr,
    }


cli.add_command(bigquery)
cli.add_command(csv)
cli.add_command(dataplex)
cli.add_command(query_log)
cli.add_command(agent_context)


def main() -> None:
    """Console-script entry point.

    :class:`neocarta._cli.errors.CLIError` inherits from
    :class:`click.ClickException`, so Click handles the exit-code mapping and
    structured rendering natively.
    """
    cli()


if __name__ == "__main__":
    main()
