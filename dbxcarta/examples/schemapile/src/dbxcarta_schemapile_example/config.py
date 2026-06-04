"""Load SchemaPile example configuration from environment.

Centralizes the `.env` reads so every entrypoint (slice runner, candidate
selector, materializer, question generator, preset) sees the same values
and validation errors fail loudly at one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dbxcarta.core.config import derive_ops_config

if TYPE_CHECKING:
    from collections.abc import Mapping

_PROJECT_CATALOGS_BLOCKLIST: frozenset[str] = frozenset(
    {
        "graph-enriched-lakehouse",
        "dbxcarta-catalog",
        "main",
        "hive_metastore",
        "samples",
        "system",
    }
)

# The blueprint is committed under the example dir, not generated into .cache,
# so the default resolves against the package location rather than the cwd.
_BLUEPRINT_DIR = Path(__file__).resolve().parents[2] / "blueprint"


@dataclass(frozen=True)
class SchemaPileConfig:
    """Parsed configuration for the SchemaPile example.

    Read once at the entrypoint boundary. Downstream modules accept the
    parsed object rather than re-reading os.environ themselves.
    """

    repo: Path
    input_filename: str
    target_tables: int
    strategy: str
    seed: int
    min_tables: int
    max_tables: int
    min_fk_edges: int
    require_self_contained: bool
    require_data: bool
    slice_cache: Path
    candidate_cache: Path
    candidate_min_tables: int
    candidate_max_tables: int
    candidate_min_fk_edges: int
    candidate_require_data: bool
    candidate_limit: int
    catalog: str
    # Ops volume path, sourced verbatim from DATABRICKS_VOLUME_PATH. The ops
    # plane lives in its own catalog (dbxcarta-catalog.schemapile_ops), separate
    # from the data catalog this config materializes tables into, so data
    # discovery never sweeps it in. There is no in-catalog derivation: a missing
    # DATABRICKS_VOLUME_PATH fails loudly rather than routing ops into the data
    # catalog.
    volume_path: str
    questions_path: str
    question_model: str
    questions_per_schema: int
    question_temperature: float

    @property
    def slice_path(self) -> Path:
        return self.slice_cache

    @property
    def candidate_path(self) -> Path:
        return self.candidate_cache

    @property
    def input_path(self) -> Path:
        return self.repo / self.input_filename

    @property
    def upstream_slice_script(self) -> Path:
        return self.repo / "slice.py"


def load_config(env: Mapping[str, str] | None = None) -> SchemaPileConfig:
    """Build a SchemaPileConfig from environment variables.

    Defaults match `.env.sample`. Missing required values raise ValueError
    with a message that names the variable so the user can fix `.env`.
    """
    e = env if env is not None else os.environ

    repo_str = _required(e, "SCHEMAPILE_REPO")
    repo = Path(repo_str).expanduser().resolve()

    catalog = _required(e, "DBXCARTA_CATALOG")
    if catalog.casefold() in _PROJECT_CATALOGS_BLOCKLIST:
        raise ValueError(
            f"DBXCARTA_CATALOG={catalog!r} collides with a known project catalog;"
            " choose a dedicated catalog for the schemapile example"
        )

    # The ops plane is separate from the data catalog. DATABRICKS_VOLUME_PATH
    # (the overlay/.env points it at the ops catalog) is required: there is no
    # in-catalog fallback, so a missing value fails loudly instead of silently
    # routing ops into the data-only catalog.
    volume_path = _required(e, "DATABRICKS_VOLUME_PATH")

    return SchemaPileConfig(
        repo=repo,
        input_filename=e.get("SCHEMAPILE_INPUT", "schemapile-perm.json"),
        target_tables=int(e.get("SCHEMAPILE_TARGET_TABLES", "1000")),
        strategy=e.get("SCHEMAPILE_STRATEGY", "random"),
        seed=int(e.get("SCHEMAPILE_SEED", "42")),
        min_tables=int(e.get("SCHEMAPILE_MIN_TABLES", "2")),
        max_tables=int(e.get("SCHEMAPILE_MAX_TABLES", "100")),
        min_fk_edges=int(e.get("SCHEMAPILE_MIN_FK_EDGES", "1")),
        require_self_contained=_truthy(e.get("SCHEMAPILE_REQUIRE_SELF_CONTAINED", "true")),
        require_data=_truthy(e.get("SCHEMAPILE_REQUIRE_DATA", "false")),
        slice_cache=Path(e.get("SCHEMAPILE_SLICE_CACHE", ".cache/slice_random_1000.json")),
        candidate_cache=Path(
            e.get("SCHEMAPILE_CANDIDATE_CACHE") or _BLUEPRINT_DIR / "candidates_random_1000.json"
        ),
        candidate_min_tables=int(e.get("SCHEMAPILE_CANDIDATE_MIN_TABLES", "3")),
        candidate_max_tables=int(e.get("SCHEMAPILE_CANDIDATE_MAX_TABLES", "20")),
        candidate_min_fk_edges=int(e.get("SCHEMAPILE_CANDIDATE_MIN_FK_EDGES", "2")),
        candidate_require_data=_truthy(e.get("SCHEMAPILE_CANDIDATE_REQUIRE_DATA", "false")),
        candidate_limit=int(e.get("SCHEMAPILE_CANDIDATE_LIMIT", "20")),
        catalog=catalog,
        volume_path=volume_path,
        # Single core rule for "given the ops volume root, where questions
        # live". Derived only when the var is unset, so a malformed volume_path
        # is not validated on the explicit-value path.
        questions_path=e.get("DBXCARTA_CLIENT_QUESTIONS")
        or derive_ops_config(volume_path).client_questions,
        question_model=e.get(
            "SCHEMAPILE_QUESTION_MODEL",
            "databricks-meta-llama-3-3-70b-instruct",
        ),
        questions_per_schema=int(e.get("SCHEMAPILE_QUESTIONS_PER_SCHEMA", "6")),
        question_temperature=float(e.get("SCHEMAPILE_QUESTION_TEMPERATURE", "0.2")),
    )


def _required(env: Mapping[str, str], key: str) -> str:
    val = env.get(key, "").strip()
    if not val:
        raise ValueError(f"{key} is not set; check examples/schemapile/.env")
    return val


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
