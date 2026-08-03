"""The one reserved identity field on an otherwise identity-agnostic contract.

GUIDE **D6** makes connector mappings identity-agnostic and hands identity to an
ontology-declared KeySpec, *"a rare explicit-ID override exists for cross-source
alignment"*. This module is that clause: the single owner of the reserved
``explicit_id`` field (GUIDE §4, "one owner per piece of state"), so the
structural core (``models.py``) and the optional facets (``facets.py``) declare
the same escape hatch and cannot drift apart — exactly the role ``_vocabulary.py``
plays for the field vocabulary.

Four rules the field keeps, each of which a test pins:

- **Opt-in.** It defaults to ``None``, so identity-agnostic stays the *default*
  and every row a connector emits today is unaffected.
- **Never aliased.** ``validation_alias`` is ``None``, so the input name is the
  field name and a connector must project deliberately. A source ``*_id`` column
  is not reliably a graph id: ``_vocabulary.py`` already spends ``table_id``,
  ``dataset_id`` and ``project_id`` on *name* concepts, and Dataplex's
  ``glossary_id`` / ``category_id`` / ``term_id`` are slugs. Absorbing any of
  them here would let a raw row silently override with the wrong value — and an
  override *wins*, so the damage is a corrupted id rather than a rejected row.
- **Verbatim.** The value is never normalized, stripped or case-folded. The
  generated ids it displaces are dot-joined ``_normalize``d segments; the whole
  point of an override is to reach an id that shape cannot express, such as the
  Dataplex resource path ``generate_business_term_id``'s docstring already tells
  users to align onto.
- **Blank means absent.** ``""``, whitespace and NaN fold to ``None``. An empty
  string is falsy but is not ``None``, so leaving it intact would make
  :func:`~neocarta.etl.transform.resolve_id` return ``""`` and collapse every row
  of that type onto one empty-id node — the same "never fabricate a key segment"
  rule ``ValueRecord.value`` keeps.

Only **entity** records carry it. A relationship is merged on its endpoint pair
and has no id of its own, so the field would be permanently unconsumed on
``ForeignKeyRecord``, ``BusinessTermAssignmentRecord`` and ``LineageRecord``;
their endpoints resolve through the entity rows' overrides instead. The
precedence rule itself lives with the ID builder that applies it
(``etl/transform``), not here — see ``docs/refactor/explicit-id-override.md``.
"""

from typing import Any

from pydantic import Field, field_validator

from ....data_model._validators import coerce_key_segment_or_none

_DESCRIPTION = (
    "A pre-computed graph id supplied by the connector, which wins over the id the "
    "downstream KeySpec builder would generate from this row's natural key (GUIDE D6). "
    "Opt-in and rare: leave it unset unless the source is a passthrough source or the "
    "row must align onto an id another source already minted. Used verbatim."
)


def explicit_id_field() -> Any:
    """Declare the reserved ``explicit_id`` field on an entity record.

    A factory rather than a module-level constant so each record gets its own
    ``FieldInfo``, and so the D6 carve-out is a visible, greppable opt-in at every
    declaration site rather than something a future record can inherit silently.

    Returns:
    -------
    Any
        The Pydantic field declaration: optional, defaulting to ``None``, with no
        validation alias.
    """
    return Field(
        default=None,
        description=_DESCRIPTION,
        examples=["projects/p/locations/us/glossaries/ecommerce-glossary"],
    )


def explicit_id_validator() -> Any:
    """Declare the blank-to-``None`` fold for ``explicit_id`` on an entity record.

    Pairs with :func:`explicit_id_field`; assign it to a private class attribute
    (``_fold_explicit_id = explicit_id_validator()``). Also a factory, because a
    validator proxy binds to the class it is assigned on.

    Returns:
    -------
    Any
        The Pydantic validator descriptor folding blank / NaN values to ``None``.
    """
    return field_validator("explicit_id", mode="before")(coerce_key_segment_or_none)
