"""Single owner of the rule mapping the ops volume root to where runs and
questions live.

The ops-side config values are not independent: they are one base path with a
tail. ``DATABRICKS_VOLUME_PATH`` (``/Volumes/<ops_catalog>/<ops_schema>/<vol>``)
fixes the run-summary volume, the summary table, the client-questions path, and
the schema half of the teardown target. This module derives all of them from
that one base so no consumer hand-writes (and drifts) a value another consumer
also spells out.

Derivation is pure, non-secret string work, so the same function serves both
the host-side tools (bootstrap, teardown, presets) and the cluster-side
Settings: the cluster derives from the compact base itself rather than relying
on a pre-expanded parameter set. Core stays Spark- and SDK-free; the only
dependency is :mod:`dbxcarta.core.identifiers`.
"""

from __future__ import annotations

from dataclasses import dataclass

from dbxcarta.core.identifiers import parse_volume_path

# The questions filename is a genuine per-example choice, not pure derivation:
# dense ships ``dense_questions.json`` while schemapile and finance use the
# default below. It stays an argument so one rule serves every example.
DEFAULT_QUESTIONS_FILENAME = "questions.json"

# The blueprint filename is likewise a per-example choice (dense ships
# ``candidates_<n>.json``, schemapile ``candidates_random_1000.json``), so it is
# an argument with a generic default rather than a hardcoded constant. The
# materialize submit path stages the committed blueprint to this Volume path and
# the materialize Spark job reads it from there, the way client questions are.
DEFAULT_BLUEPRINT_FILENAME = "blueprint.json"

# Fixed tails appended to the one base. Kept as constants so the two test
# surfaces (the resolver unit test and the committed-overlay golden test) assert
# against one definition rather than two hand-copied literals.
_VOLUME_SUBDIR = "dbxcarta"
_RUNS_TAIL = "runs"
_BLUEPRINT_TAIL = "blueprint"
_SUMMARY_TABLE_NAME = "dbxcarta_run_summary"


@dataclass(frozen=True)
class DerivedOpsConfig:
    """The ops-side values derived from one volume-path base.

    ``blueprint_volume`` is where the committed materialize blueprint is staged
    on the ops Volume for the materialize Spark job to read, mirroring
    ``client_questions``.

    ``teardown_schema_target`` is the ``<ops_catalog>.<ops_schema>`` schema half
    of ``DBXCARTA_TEARDOWN_TARGET``. The ``catalog:`` half is the data catalog,
    a genuine example choice (present when the example owns its catalog, absent
    when an upstream project does, as in finance-genie), so it is not derived
    here.
    """

    summary_volume: str
    summary_table: str
    client_questions: str
    blueprint_volume: str
    teardown_schema_target: str


def derive_ops_config(
    volume_path: str,
    *,
    questions_filename: str = DEFAULT_QUESTIONS_FILENAME,
    blueprint_filename: str = DEFAULT_BLUEPRINT_FILENAME,
) -> DerivedOpsConfig:
    """Derive the ops-side config from ``DATABRICKS_VOLUME_PATH``.

    A malformed base fails loudly through :func:`parse_volume_path`, which
    names the expected ``/Volumes/<catalog>/<schema>/<volume>`` shape, rather
    than silently producing a wrong derived path.
    """
    ops_catalog, ops_schema, _volume = parse_volume_path(volume_path)
    base = volume_path.strip().rstrip("/")
    return DerivedOpsConfig(
        summary_volume=f"{base}/{_VOLUME_SUBDIR}/{_RUNS_TAIL}",
        summary_table=f"{ops_catalog}.{ops_schema}.{_SUMMARY_TABLE_NAME}",
        client_questions=f"{base}/{_VOLUME_SUBDIR}/{questions_filename}",
        blueprint_volume=f"{base}/{_VOLUME_SUBDIR}/{_BLUEPRINT_TAIL}/{blueprint_filename}",
        teardown_schema_target=f"{ops_catalog}.{ops_schema}",
    )
