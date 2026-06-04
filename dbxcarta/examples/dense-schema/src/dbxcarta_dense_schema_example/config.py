"""Load DenseSchema example configuration from environment."""

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
class DenseSchemaConfig:
    catalog: str
    table_count: int
    uc_schema: str
    seed: int
    candidate_cache: Path
    # Ops volume path, sourced verbatim from DATABRICKS_VOLUME_PATH. The ops
    # plane lives in its own catalog (dbxcarta-catalog.dense-ops), separate from
    # the data catalog this config materializes tables into, so data discovery
    # never sweeps it in. There is no in-catalog derivation: a missing
    # DATABRICKS_VOLUME_PATH fails loudly rather than routing ops into the data
    # catalog.
    volume_path: str
    questions_path: str
    question_model: str
    questions_target: int
    questions_per_batch: int
    question_temperature: float


def load_config(env: Mapping[str, str] | None = None) -> DenseSchemaConfig:
    e = env if env is not None else os.environ
    catalog = _required(e, "DBXCARTA_CATALOG")
    if catalog.casefold() in _PROJECT_CATALOGS_BLOCKLIST:
        raise ValueError(f"DBXCARTA_CATALOG={catalog!r} collides with a known project catalog")
    table_count = int(e.get("DENSE_TABLE_COUNT", "500"))
    uc_schema = e.get("DENSE_SCHEMA_NAME", f"dense_{table_count}")
    # The ops plane is separate from the data catalog. DATABRICKS_VOLUME_PATH
    # (the overlay/.env points it at the ops catalog) is required: there is no
    # in-catalog fallback, so a missing value fails loudly instead of silently
    # routing ops into the data-only catalog.
    volume_path = _required(e, "DATABRICKS_VOLUME_PATH")
    return DenseSchemaConfig(
        catalog=catalog,
        table_count=table_count,
        uc_schema=uc_schema,
        seed=int(e.get("DENSE_SEED", "42")),
        candidate_cache=Path(
            e.get("DENSE_CANDIDATE_CACHE") or _BLUEPRINT_DIR / f"candidates_{table_count}.json"
        ),
        volume_path=volume_path,
        # Single core rule for "given the ops volume root, where questions
        # live"; dense's example-specific filename is the one parameter. The
        # derived path is computed only when the var is unset, so a malformed
        # volume_path is not validated on the explicit-value path.
        questions_path=e.get("DBXCARTA_CLIENT_QUESTIONS")
        or derive_ops_config(
            volume_path, questions_filename="dense_questions.json"
        ).client_questions,
        question_model=e.get(
            "DENSE_QUESTION_MODEL",
            "databricks-meta-llama-3-3-70b-instruct",
        ),
        questions_target=int(e.get("DENSE_QUESTIONS_TARGET", "60")),
        questions_per_batch=int(e.get("DENSE_QUESTIONS_PER_BATCH", "3")),
        question_temperature=float(e.get("DENSE_QUESTION_TEMPERATURE", "0.2")),
    )


def _required(env: Mapping[str, str], key: str) -> str:
    val = env.get(key, "").strip()
    if not val:
        raise ValueError(f"{key} is not set; check examples/dense-schema/.env")
    return val
