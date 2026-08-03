"""Parity: the CSV connector's id passthrough, reproduced through the contract (S1.4, #295).

The ticket's parity check is *"passthrough IDs must match today's values exactly"*, so the
oracle here is the **real** ``CSVExtractor`` — never a hand-written expected string. Each
case drives the shipped extractor over a one-row CSV and asserts the same row, validated as
a normalized record and resolved, lands on the identical id — both when the ``*_id`` column
is absent (generated) and when it is present (the override wins, verbatim).

Nothing here flips the connector; that is S4. This pins the id *values* S4 must not change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from neocarta.connectors.csv.extract import CSVExtractor
from neocarta.connectors.utils.generate_id import (
    _normalize,
    generate_business_term_id,
    generate_category_id,
    generate_column_id,
    generate_database_id,
    generate_glossary_id,
    generate_schema_id,
    generate_table_id,
    generate_value_id,
)
from neocarta.etl.metadata_normalizer.normalized_schema import (
    BusinessTermRecord,
    CategoryRecord,
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    GlossaryRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)
from neocarta.etl.transform import resolve_id

if TYPE_CHECKING:
    from pathlib import Path

# An id no generated shape can express: `_normalize` would rewrite it (asserted below),
# so it doubles as the verbatim control. Shaped like the Dataplex resource paths
# `generate_business_term_id`'s docstring tells users to align a CSV onto.
EXPLICIT = "projects/p/locations/us/entries/Custom-ID"

# --- The eight *entity-owning* id columns, from the audit of `connectors/csv/extract.py`.
# Each case: the CSV cells, the extractor method that resolves the id today, the record those
# cells validate as, and the generator the KeySpec builder replaces. The two reference
# endpoints and every *parent* column a child file repeats are covered by the endpoint class
# below, since under the contract they resolve through the parent's own record.
ENTITY_CASES: dict[str, dict] = {
    "database": {
        "filename": "database_info.csv",
        "extract": "extract_database_info",
        "id_column": "database_id",
        "model": DatabaseRecord,
        "cells": {"database_name": "My-DB"},
        "generate": lambda r: generate_database_id(r.database_name),
    },
    "schema": {
        "filename": "schema_info.csv",
        "extract": "extract_schema_info",
        "id_column": "schema_id",
        "model": SchemaRecord,
        "cells": {"database_name": "My-DB", "schema_name": "sales"},
        "generate": lambda r: generate_schema_id(r.database_name, r.schema_name),
    },
    "table": {
        "filename": "table_info.csv",
        "extract": "extract_table_info",
        "id_column": "table_id",
        "model": TableRecord,
        "cells": {"database_name": "My-DB", "schema_name": "sales", "table_name": "orders"},
        "generate": lambda r: generate_table_id(r.database_name, r.schema_name, r.table_name),
    },
    "column": {
        "filename": "column_info.csv",
        "extract": "extract_column_info",
        "id_column": "column_id",
        "model": ColumnRecord,
        "cells": {
            "database_name": "My-DB",
            "schema_name": "sales",
            "table_name": "orders",
            "column_name": "order_id",
        },
        "generate": lambda r: generate_column_id(
            r.database_name, r.schema_name, r.table_name, r.column_name
        ),
    },
    "value": {
        "filename": "value_info.csv",
        "extract": "extract_value_info",
        "id_column": "value_id",
        "model": ValueRecord,
        "cells": {
            "database_name": "My-DB",
            "schema_name": "sales",
            "table_name": "orders",
            "column_name": "status",
            "value": "Completed",
        },
        "generate": lambda r: generate_value_id(
            r.database_name, r.schema_name, r.table_name, r.column_name, r.value
        ),
    },
    "glossary": {
        "filename": "glossary_info.csv",
        "extract": "extract_glossary_info",
        "id_column": "glossary_id",
        "model": GlossaryRecord,
        "cells": {"glossary_name": "ecommerce_glossary"},
        "generate": lambda r: generate_glossary_id(r.glossary_name),
    },
    "category": {
        "filename": "category_info.csv",
        "extract": "extract_category_info",
        "id_column": "category_id",
        "model": CategoryRecord,
        "cells": {"glossary_name": "ecommerce_glossary", "category_name": "revenue_metrics"},
        "generate": lambda r: generate_category_id(r.glossary_name, r.category_name),
    },
    "business_term": {
        "filename": "business_term_info.csv",
        "extract": "extract_business_term_info",
        "id_column": "business_term_id",
        "model": BusinessTermRecord,
        "cells": {
            "glossary_name": "ecommerce_glossary",
            "category_name": "revenue_metrics",
            "term_name": "gmv",
        },
        "generate": lambda r: generate_business_term_id(
            r.glossary_name, r.category_name, r.term_name
        ),
    },
}

# `schema_info.csv` resolves *two* ids: its own `schema_id` (the entity case above) and
# the parent `database_id` that is the HAS_SCHEMA endpoint — the one containment endpoint
# today's connector materializes on the child row, and so the one the index rule can be
# exercised against without the S3 transform.
SCHEMA_CELLS = ENTITY_CASES["schema"]["cells"]
HAS_SCHEMA_ENDPOINT = {
    "filename": "schema_info.csv",
    "extract": "extract_schema_info",
    "id_column": "database_id",
}

# The reference (REFERENCES) frame: one CSV, two endpoints, and — under the contract —
# no override field of its own, because an edge has no identity to override.
REFERENCE_CELLS = {
    "source_database_name": "My-DB",
    "source_schema_name": "sales",
    "source_table_name": "orders",
    "source_column_name": "customer_id",
    "target_database_name": "My-DB",
    "target_schema_name": "sales",
    "target_table_name": "customers",
    "target_column_name": "id",
}


def _todays_id(tmp_path: Path, case: dict, cells: dict) -> str:
    """Resolve one id the way the shipped CSV connector resolves it today."""
    header = ",".join(cells)
    row = ",".join(str(v) for v in cells.values())
    (tmp_path / case["filename"]).write_text(f"{header}\n{row}\n")
    frame = getattr(CSVExtractor(str(tmp_path)), case["extract"])()
    return frame[case["id_column"]].iloc[0]


class TestExplicitIdColumnsReproduceTodaysValues:
    """AC: when set, the override wins — and matches what CSV passes through today."""

    @pytest.mark.parametrize("case_name", sorted(ENTITY_CASES))
    def test_explicit_value_matches_todays_extractor(self, case_name: str, tmp_path: Path) -> None:
        case = ENTITY_CASES[case_name]
        cells = {**case["cells"], case["id_column"]: EXPLICIT}
        today = _todays_id(tmp_path, case, cells)
        # The connector projects its `<x>_id` column onto the reserved field; every other
        # cell is already the contract's canonical vocabulary.
        record = case["model"].model_validate({**case["cells"], "explicit_id": EXPLICIT})
        assert resolve_id(record.explicit_id, case["generate"](record)) == today

    def test_the_oracle_passes_the_explicit_value_through_unchanged(self, tmp_path: Path) -> None:
        # Sensitivity control for every case above, so it runs once rather than per case:
        # the generated shape would have rewritten this string, which is what makes those
        # equalities unsatisfiable by a normalized id that merely looks similar. It also
        # states the property of today's connector that makes it a usable oracle at all.
        assert _normalize(EXPLICIT) != EXPLICIT
        case = ENTITY_CASES["column"]
        assert (
            _todays_id(tmp_path, case, {**case["cells"], case["id_column"]: EXPLICIT}) == EXPLICIT
        )

    def test_the_parity_assertion_has_teeth(self, tmp_path: Path) -> None:
        # Negative control per the #291 harness's reference pattern: degenerate the resolver to
        # ignore the override, and the explicit case must break — otherwise a resolver that
        # always generated would still look green on the auto-generated half. One case suffices,
        # since every case runs the same single-line resolver.
        case = ENTITY_CASES["column"]
        cells = {**case["cells"], case["id_column"]: EXPLICIT}
        today = _todays_id(tmp_path, case, cells)
        record = case["model"].model_validate({**case["cells"], "explicit_id": EXPLICIT})
        with pytest.raises(AssertionError):
            assert case["generate"](record) == today  # the resolver's job, skipped


class TestGeneratedIdsReproduceTodaysValues:
    """AC: when absent, downstream generation applies — at today's exact values."""

    @pytest.mark.parametrize("case_name", sorted(ENTITY_CASES))
    def test_auto_generated_value_matches_todays_extractor(
        self, case_name: str, tmp_path: Path
    ) -> None:
        case = ENTITY_CASES[case_name]
        today = _todays_id(tmp_path, case, case["cells"])
        record = case["model"].model_validate(case["cells"])
        # No `*_id` column in the CSV, so the contract row is identity-agnostic and the
        # id comes wholly from the natural key — which is the default D6 preserves.
        assert record.explicit_id is None
        assert resolve_id(record.explicit_id, case["generate"](record)) == today


class TestEndpointsResolveThroughTheEntityRow:
    """An edge carries no override; its endpoints resolve through the entity records."""

    def test_parent_endpoint_uses_the_parents_override(self, tmp_path: Path) -> None:
        # `schema_info.csv`'s `database_id` column *is* the HAS_SCHEMA endpoint, so this
        # is the index rule exercised against today's connector: the parent's override
        # decides the endpoint, and the child row never repeats it.
        today = _todays_id(tmp_path, HAS_SCHEMA_ENDPOINT, {**SCHEMA_CELLS, "database_id": EXPLICIT})
        parent = DatabaseRecord.model_validate(
            {"database_name": SCHEMA_CELLS["database_name"], "explicit_id": EXPLICIT}
        )
        assert resolve_id(parent.explicit_id, generate_database_id(parent.database_name)) == today

    def test_parent_endpoint_falls_back_to_generation(self, tmp_path: Path) -> None:
        # An index miss is "no override", never an error: today the endpoint id is
        # computed from the child row's own key segments, and the fallback computes the
        # same id from the same segments, so a missing parent row stays bit-identical.
        today = _todays_id(tmp_path, HAS_SCHEMA_ENDPOINT, SCHEMA_CELLS)
        child = SchemaRecord.model_validate(SCHEMA_CELLS)
        assert resolve_id(None, generate_database_id(child.database_name)) == today

    @pytest.mark.parametrize("side", ["source", "target"])
    def test_foreign_key_endpoints_reproduce_todays_values(self, side: str, tmp_path: Path) -> None:
        case = {
            "filename": "column_references_info.csv",
            "extract": "extract_column_references_info",
            "id_column": f"{side}_column_id",
        }
        today = _todays_id(tmp_path, case, REFERENCE_CELLS)
        record = ForeignKeyRecord.model_validate(REFERENCE_CELLS)
        endpoint = ColumnRecord.model_validate(
            {
                "database_name": getattr(record, f"{side}_database_name"),
                "schema_name": getattr(record, f"{side}_schema_name"),
                "table_name": getattr(record, f"{side}_table_name"),
                "column_name": getattr(record, f"{side}_column_name"),
            }
        )
        assert (
            resolve_id(
                endpoint.explicit_id,
                generate_column_id(
                    endpoint.database_name,
                    endpoint.schema_name,
                    endpoint.table_name,
                    endpoint.column_name,
                ),
            )
            == today
        )
