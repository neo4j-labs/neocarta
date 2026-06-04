"""Preset protocols and the shared StandardPreset for dbxcarta integrations.

A preset is a Python object a downstream example publishes in its own package
and passes (by import path) to the operational dbxcarta CLI. Per-example
dbxcarta config lives in the committed ``examples/<name>/dbxcarta-overlay.env``,
not in the preset; the preset exists only to provide the optional capabilities
below (readiness checks, question upload) without making the Spark package
depend on the client package.

Every example uses the one concrete :class:`StandardPreset`, constructed with
its bundled ``questions.json``. The readiness rule and the upload behavior are
identical across examples, so they live here once.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from dbxcarta.core.catalogs import resolve_catalogs
from dbxcarta.core.identifiers import quote_identifier
from dbxcarta.core.volume_io import load_json_file, upload_file_to_volume

if TYPE_CHECKING:
    from pathlib import Path

    from databricks.sdk import WorkspaceClient


# Unity Catalog auto-creates these in every catalog, so they are not evidence
# that anything has been materialized. Readiness excludes both.
_NON_DATA_SCHEMAS = frozenset({"information_schema", "default"})


@runtime_checkable
class Preset(Protocol):
    """Marker protocol for a dbxcarta preset.

    There is no required method: a preset's behavior comes from the optional
    capability protocols below (:class:`ReadinessCheckable`,
    :class:`QuestionsUploadable`).
    """


@dataclass(frozen=True)
class ReadinessReport:
    """Result of a preset's readiness check.

    ``present`` and ``missing_required`` hold catalog names: a catalog is
    present when it holds a data schema and missing when it does not.
    ``catalog`` holds the comma-joined resolved catalog list and ``schema`` is
    empty, because readiness no longer targets a single schema.
    """

    catalog: str
    schema: str
    present: tuple[str, ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]

    def ok(self, *, strict_optional: bool = False) -> bool:
        if self.missing_required:
            return False
        return not (strict_optional and self.missing_optional)

    def format(self, *, strict_optional: bool = False) -> str:
        scope = self.catalog if not self.schema else f"{self.catalog}.{self.schema}"
        lines = [
            f"scope: {scope}",
            f"present catalogs: {len(self.present)}",
        ]
        if self.missing_required:
            lines.append("missing required: " + ", ".join(self.missing_required))
        else:
            lines.append("catalogs: ready")
        # No example populates missing_optional under the one-rule design: every
        # listed catalog is required. The field and the strict_optional flag are
        # kept so ok() and the CLI --strict-optional flag need no signature
        # change, but the report stays silent on optional catalogs unless one is
        # ever surfaced, rather than printing a category the design removed.
        if self.missing_optional:
            label = "missing optional"
            if not strict_optional:
                label += " (warning)"
            lines.append(f"{label}: " + ", ".join(self.missing_optional))
        lines.append(
            "status: ready" if self.ok(strict_optional=strict_optional) else "status: not ready"
        )
        return "\n".join(lines)


@runtime_checkable
class ReadinessCheckable(Protocol):
    """Optional capability: a preset can report on the UC data it expects."""

    def readiness(self, ws: WorkspaceClient, warehouse_id: str) -> ReadinessReport: ...


@runtime_checkable
class QuestionsUploadable(Protocol):
    """Optional capability: a preset can ship and upload a demo question set."""

    def upload_questions(self, ws: WorkspaceClient) -> None: ...


@dataclass(frozen=True)
class StandardPreset:
    """The one preset every dbxcarta example uses.

    Behavior only: the per-example dbxcarta config lives in the committed
    dbxcarta-overlay.env, and the per-example data is the bundled questions
    file. Readiness and upload read the catalog list and destination from the
    environment the CLI has already loaded, so the preset holds no catalog,
    schema, or table config that could drift from the overlay.
    """

    questions_file: Path

    def readiness(self, ws: WorkspaceClient, warehouse_id: str) -> ReadinessReport:
        """Report whether each ingested catalog holds a data schema.

        Resolves the catalog list from DBXCARTA_CATALOG and DBXCARTA_CATALOGS
        through the same parser the pipeline uses, then checks each catalog for
        a schema other than the UC-auto-created information_schema and default.
        A catalog holding only those two has nothing materialized and is not
        ready. Fails loud when DBXCARTA_CATALOG is unset, the same way an ingest
        run would.
        """
        catalog = os.environ.get("DBXCARTA_CATALOG", "").strip()
        if not catalog:
            raise RuntimeError(
                "DBXCARTA_CATALOG is not set; cannot resolve the catalogs to"
                " check. Select an integration overlay with --env-file."
            )
        catalogs = resolve_catalogs(catalog, os.environ.get("DBXCARTA_CATALOGS", ""))
        present: list[str] = []
        missing: list[str] = []
        for cat in catalogs:
            if _has_data_schema(ws, warehouse_id, cat):
                present.append(cat)
            else:
                missing.append(cat)
        return ReadinessReport(
            catalog=",".join(catalogs),
            schema="",
            present=tuple(present),
            missing_required=tuple(missing),
            missing_optional=(),
        )

    def upload_questions(self, ws: WorkspaceClient) -> None:
        dest = os.environ.get("DBXCARTA_CLIENT_QUESTIONS", "")
        if not dest:
            raise RuntimeError(
                "DBXCARTA_CLIENT_QUESTIONS is not set; cannot determine upload destination."
            )
        if not dest.startswith("/Volumes/") or not dest.endswith(".json"):
            raise ValueError(
                f"DBXCARTA_CLIENT_QUESTIONS must be a /Volumes/... .json path, got {dest!r}"
            )
        _validate_questions_file(self.questions_file)
        upload_file_to_volume(ws, self.questions_file, dest)


def _has_data_schema(
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
) -> bool:
    """True when the catalog holds a schema beyond information_schema/default."""
    return any(
        (cleaned := name.strip()) and cleaned not in _NON_DATA_SCHEMAS
        for name in _fetch_schema_names(ws, warehouse_id, catalog)
    )


def _fetch_schema_names(
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
) -> list[str]:
    from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout

    response = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=(
            f"SELECT schema_name FROM {quote_identifier(catalog)}.information_schema.schemata"
        ),
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
    )
    rows = getattr(getattr(response, "result", None), "data_array", None) or []
    return [row[0] for row in rows if row]


def _validate_questions_file(path: Path) -> None:
    """Validate a questions file before upload.

    A light structural check with the stdlib only, so dbxcarta-spark stays free
    of a client dependency (the cross-layer import boundary forbids it). The
    file must be a non-empty JSON array whose entries each carry a non-empty
    question_id and question. The client package validates the full Question
    model when it loads the uploaded file at query time.
    """
    if not path.is_file():
        raise FileNotFoundError(f"questions file not found at {path}; generate it first")
    questions = load_json_file(path, label="questions file")
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"questions file must be a non-empty JSON array: {path}")
    for item in questions:
        if not isinstance(item, dict):
            # ValueError is the deliberate, uniform error contract for an
            # invalid questions file (not a programmer type error).
            raise ValueError(f"each question must be a JSON object: {path}")  # noqa: TRY004
        for field in ("question_id", "question"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"each question needs a non-empty {field!r}: {path}")
