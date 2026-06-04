"""Databricks identifier and path helpers shared across dbxcarta layers."""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")
_VOLUME_SUBPATH_PART_RE = re.compile(r"^[A-Za-z0-9._=-]+$")

# Catalogs that dbxcarta tooling must never create or drop. The build and
# teardown commands both refuse these so a typo in an overlay's volume path
# or teardown target cannot point setup or teardown at a shared system
# catalog. ``graph-enriched-lakehouse`` is included because the per-example
# config historically blocked it.
UC_PROTECTED_NAMES: frozenset[str] = frozenset(
    {"main", "system", "hive_metastore", "samples", "graph-enriched-lakehouse"}
)


def validate_identifier(value: str, *, label: str = "identifier") -> str:
    """Validate a single Databricks identifier part.

    Hyphens are accepted because Unity Catalog allows them when quoted.
    Backticks, dots, spaces, and leading digits are rejected so callers can
    safely quote the returned value with backticks.
    """
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"Invalid Databricks {label}: {value!r}")
    return value


def split_qualified_name(
    value: str,
    *,
    expected_parts: int | None = None,
    label: str = "qualified name",
) -> list[str]:
    parts = value.split(".")
    if expected_parts is not None and len(parts) != expected_parts:
        raise ValueError(
            f"Invalid Databricks {label}: {value!r}; expected {expected_parts} dot-separated parts"
        )
    for part in parts:
        validate_identifier(part, label=f"{label} part")
    return parts


def quote_identifier(value: str) -> str:
    return f"`{validate_identifier(value)}`"


def quote_qualified_name(value: str, *, expected_parts: int | None = None) -> str:
    return ".".join(
        quote_identifier(part)
        for part in split_qualified_name(value, expected_parts=expected_parts)
    )


def check_not_protected(value: str, *, label: str = "catalog") -> str:
    """Reject names on the protected blocklist.

    Guards both the build path (creating a catalog) and the teardown path
    (dropping a catalog or schema) so neither can act on a shared system
    catalog because of a typo in an overlay.
    """
    if value in UC_PROTECTED_NAMES:
        raise ValueError(f"refusing to operate on protected {label}: {value!r}")
    return value


def parse_volume_path(value: str) -> tuple[str, str, str]:
    """Split ``/Volumes/<catalog>/<schema>/<volume>`` into its three identifiers.

    Unlike :func:`validate_uc_volume_subpath`, this expects a bare volume path
    with no trailing subdirectory (exactly four parts), which is what the
    bootstrap command provisions. Each identifier is validated so the caller
    can quote it safely with backticks.
    """
    parts = value.strip().strip("/").split("/")
    if len(parts) != 4 or parts[0] != "Volumes":
        raise ValueError(f"volume path must be /Volumes/<catalog>/<schema>/<volume>, got {value!r}")
    catalog, schema, volume = parts[1], parts[2], parts[3]
    validate_identifier(catalog, label="volume catalog")
    validate_identifier(schema, label="volume schema")
    validate_identifier(volume, label="volume name")
    return catalog, schema, volume


def validate_uc_volume_subpath(value: str, *, label: str = "UC Volume path") -> str:
    """Validate /Volumes/<catalog>/<schema>/<volume>/<subdir> paths.

    DBxCarta writes run artifacts, staging data, and ledgers below a UC Volume,
    never at the volume root. Requiring a subdirectory prevents accidental
    truncation or file creation attempts at /Volumes/<cat>/<schema>/<volume>.
    """
    parts = value.rstrip("/").lstrip("/").split("/")
    if len(parts) < 5 or parts[0] != "Volumes":
        raise ValueError(
            f"{label} must be /Volumes/<catalog>/<schema>/<volume>/<subdir>, got {value!r}"
        )
    for name, part in zip(("catalog", "schema", "volume"), parts[1:4], strict=False):
        validate_identifier(part, label=f"volume {name}")
    for part in parts[4:]:
        if not part or part in (".", "..") or not _VOLUME_SUBPATH_PART_RE.match(part):
            raise ValueError(f"{label} contains an invalid path segment: {part!r}")
    return value.rstrip("/")


def validate_serving_endpoint_name(value: str, *, label: str = "serving endpoint") -> str:
    """Validate endpoint names interpolated into ai_query string literals."""
    return validate_identifier(value, label=label)


def uc_volume_parts(value: str) -> list[str]:
    validate_uc_volume_subpath(value)
    return value.rstrip("/").lstrip("/").split("/")


def uc_volume_parent(value: str) -> str:
    parts = uc_volume_parts(value)
    return "/" + "/".join(parts[:-1])
