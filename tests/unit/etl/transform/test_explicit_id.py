"""Contract-level tests for the D6 explicit-ID precedence rule (S1.4, #295).

Proves the fixed decision — *explicit ID > generated ID* — holds, that an explicit
id survives **verbatim** where a generated one would have been normalized, and that
the model half (blank folds to ``None``) and the transform half (``None`` means
generate) compose into one rule rather than two half-rules that disagree.

The generic ID builder is #305; here the "generated" side is today's
``generate_*_id``, which is also what the parity suites pin.
"""

from __future__ import annotations

import pytest

from neocarta.connectors.utils.generate_id import _normalize, generate_column_id
from neocarta.etl.metadata_normalizer.normalized_schema import ColumnRecord
from neocarta.etl.transform import resolve_id

# --- Ids a connector would supply to reach a value the generated shape cannot express.
# Each is chosen so `_normalize` would rewrite it, which is what makes the verbatim
# assertions below non-vacuous (asserted, not assumed — see TestVerbatim).
SUPPLIED_IDS = [
    "projects/p/locations/us/glossaries/ecommerce-glossary",  # the Dataplex alignment case
    "Custom-ID With Spaces",
    "MixedCase.Id",
    "  padded  ",
]

COLUMN_KEY = ("my_db", "sales", "orders", "order_id")


class TestPrecedence:
    """The fixed decision: an explicit id wins; absent means generate."""

    def test_explicit_wins_over_generated(self) -> None:
        # One representative id: precedence is a single claim, and the value matrix that
        # matters (values a normalizer would rewrite) belongs to TestVerbatim, whose
        # assertion is this one plus a sensitivity control.
        assert resolve_id(SUPPLIED_IDS[0], generate_column_id(*COLUMN_KEY)) == SUPPLIED_IDS[0]

    def test_generated_applies_when_absent(self) -> None:
        generated = generate_column_id(*COLUMN_KEY)
        assert resolve_id(None, generated) == generated

    def test_absence_is_none_not_falsiness(self) -> None:
        # A falsy check here would silently reinterpret an id the caller genuinely
        # supplied. Blank folding is the model's job (and has already happened by the
        # time a row reaches the builder), so doing it again here would be two owners.
        assert resolve_id("", "generated") == ""
        assert resolve_id("0", "generated") == "0"


class TestVerbatim:
    """An explicit id is never normalized, stripped or case-folded."""

    @pytest.mark.parametrize("supplied", SUPPLIED_IDS)
    def test_supplied_id_is_not_normalized(self, supplied: str) -> None:
        # The sensitivity control: assert the normalizer *would* have changed this value,
        # so the equality below cannot pass by the value simply being normalization-proof.
        assert _normalize(supplied) != supplied
        assert resolve_id(supplied, "generated") == supplied


class TestModelAndResolverCompose:
    """The model half and the transform half are one rule, not two.

    Only the blank case is worth composing: a supplied id passes through both halves
    untouched, so it would just re-assert what TestPrecedence and the model's own
    verbatim tests already cover separately.
    """

    @pytest.mark.parametrize("blank", ["", "   ", "\t", None, float("nan")])
    def test_a_blank_cell_falls_back_to_generation(self, blank: object) -> None:
        # End to end over the seam: the model folds the blank to None, and only because
        # it is None does the resolver generate. If either half changed — the model
        # keeping "", or the resolver adding a falsy check — this row would land on an
        # empty-id node and every row of its type would merge onto it.
        record = ColumnRecord.model_validate(
            {
                "database_name": COLUMN_KEY[0],
                "schema_name": COLUMN_KEY[1],
                "table_name": COLUMN_KEY[2],
                "column_name": COLUMN_KEY[3],
                "explicit_id": blank,
            }
        )
        assert record.explicit_id is None
        assert resolve_id(record.explicit_id, generate_column_id(*COLUMN_KEY)) == (
            "my_db.sales.orders.order_id"
        )
