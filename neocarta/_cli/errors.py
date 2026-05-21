"""Exit-code map and structured error envelope for the Neocarta CLI.

The exit codes follow the contract documented in ``.local/build-cli/AGENTS-CLI.md``
§5.1. Field names in :func:`error_envelope` are a public API — additive-only
changes after a release.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

# Closed exit-code map. Renaming a code's meaning is a breaking change.
EXIT_SUCCESS = 0
EXIT_GENERAL_FAILURE = 1
EXIT_USAGE_ERROR = 2
EXIT_NOT_FOUND = 3
EXIT_AUTH_ERROR = 4
EXIT_CONFLICT = 5
EXIT_VALIDATION_ERROR = 6
EXIT_RATE_LIMITED = 7
EXIT_UPSTREAM_ERROR = 8
EXIT_TIMEOUT = 124

EXIT_CODES: dict[str, dict[str, Any]] = {
    "success": {"code": EXIT_SUCCESS, "description": "Success — including empty results."},
    "general_failure": {
        "code": EXIT_GENERAL_FAILURE,
        "description": "General/unexpected failure.",
    },
    "usage_error": {
        "code": EXIT_USAGE_ERROR,
        "description": "Bad flag, missing required argument, or malformed input.",
    },
    "not_found": {"code": EXIT_NOT_FOUND, "description": "Named resource does not exist."},
    "auth_error": {
        "code": EXIT_AUTH_ERROR,
        "description": "Missing or invalid credentials.",
    },
    "conflict": {
        "code": EXIT_CONFLICT,
        "description": "Resource already exists or concurrent modification.",
    },
    "validation_error": {
        "code": EXIT_VALIDATION_ERROR,
        "description": "Input was syntactically valid but semantically rejected.",
    },
    "rate_limited": {
        "code": EXIT_RATE_LIMITED,
        "description": "Rate limited or quota exceeded.",
    },
    "upstream_error": {
        "code": EXIT_UPSTREAM_ERROR,
        "description": "Transient upstream service failure.",
    },
    "timeout": {"code": EXIT_TIMEOUT, "description": "Operation exceeded its timeout."},
}


class CLIError(click.ClickException):
    """An expected CLI error mapped to a documented exit code.

    Inheriting from :class:`click.ClickException` means Click's standard
    invocation path — including ``CliRunner.invoke`` in tests — automatically
    routes through :meth:`show` and exits with :attr:`exit_code`.

    Parameters
    ----------
    code : str
        Stable error-code string from :data:`EXIT_CODES`.
    message : str
        Single-line human-readable summary. Goes to stderr.
    suggestion : str, optional
        Concrete next step the user can take.
    retryable : bool
        Whether an agent should consider retrying the command.
    details : dict, optional
        Additional structured fields to include in the JSON envelope.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        suggestion: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in EXIT_CODES:
            raise ValueError(f"Unknown error code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion
        self.retryable = retryable
        self.details = details or {}
        # click.ClickException uses .exit_code as the process exit code.
        self.exit_code = EXIT_CODES[code]["code"]

    def show(self, file: Any = None) -> None:  # noqa: ARG002
        """Render the error to stdout/stderr.

        In JSON mode the structured envelope goes to stdout under
        ``{"error": ...}`` so agents see it; a one-line human summary always
        goes to stderr. ``--json`` is detected from ``stdout.isatty()`` since
        the surrounding Click context may not be available at this point.
        """
        as_json = not sys.stdout.isatty()
        if as_json:
            sys.stdout.write(json.dumps({"error": error_envelope(self)}, indent=2))
            sys.stdout.write("\n")
            sys.stdout.flush()
        click.echo(f"Error: {self.message}", err=True)
        if self.suggestion:
            click.echo(f"  Suggestion: {self.suggestion}", err=True)


def error_envelope(err: CLIError) -> dict[str, Any]:
    """
    Build the JSON error envelope for ``--json`` output.

    Parameters
    ----------
    err : CLIError
        The error to serialise.

    Returns:
    -------
    dict
        Structured error object suitable for printing to stdout under
        ``{"error": ...}``.
    """
    envelope: dict[str, Any] = {
        "code": err.code,
        "exit_code": err.exit_code,
        "message": err.message,
        "retryable": err.retryable,
    }
    if err.suggestion:
        envelope["suggestion"] = err.suggestion
    envelope.update(err.details)
    return envelope
