"""The D6 explicit-ID precedence rule: a supplied id wins over a generated one.

GUIDE **D6** hands identity to an ontology-declared KeySpec and one generic ID
builder, with *"a rare explicit-ID override … for cross-source alignment"*. The
normalized contract declares the supplied id (``explicit_id``, one field on each
entity record); this module decides what to do with it, and lives here rather
than on the model for the same reasons S1.3 put the merge policy in the writer:

- **Precedence is not a property of a row.** It needs the supplied id *and* the
  generated one, and the contract deliberately does not replicate the
  ``generate_id`` logic — so a row structurally cannot resolve itself.
- **The contract is graph-agnostic.** The *field* is a single, guarded D6 breach
  the escape hatch cannot avoid; resolving it against a KeySpec's output would be
  a second, avoidable one.
- **One owner, and it moves as a unit.** GUIDE §5 maps
  ``connectors/utils/generate_id.py`` onto this package, so the rule is born where
  the generic ID builder (#305) lands and never has to move.

The builder is not here yet, so the resolution rule ships as one function against
which S1.4's parity tests pin today's connector id values. The wider contract —
including how an *edge* resolves endpoints it has no override field for — is
specified in ``docs/refactor/explicit-id-override.md``.
"""


def resolve_id(explicit_id: str | None, generated_id: str) -> str:
    """Apply the D6 precedence: an explicit id wins, the generated one is the default.

    The explicit id is returned **verbatim** — never normalized, stripped or
    case-folded, unlike the dot-joined ``_normalize``d segments a generated id is
    built from. That is the point of the override: it reaches ids that shape
    cannot express, such as the Dataplex resource path a CSV must align onto.

    ``None`` — not ``""`` — is the absence signal. The normalized model already
    folds a blank cell to ``None`` (``normalized_schema/_identity.py``), so
    repeating that fold here would put two owners on one rule; a falsy check would
    also silently reinterpret an id the caller genuinely supplied.

    Parameters
    ----------
    explicit_id : str | None
        The id the connector supplied on the normalized row, or ``None`` when the
        row is identity-agnostic (the default).
    generated_id : str
        The id the KeySpec-driven ID builder derived from the row's natural key.

    Returns:
    -------
    str
        ``explicit_id`` when one was supplied, otherwise ``generated_id``.

    Examples:
    --------
    >>> resolve_id(None, "my_db.sales.orders")
    'my_db.sales.orders'
    >>> resolve_id("projects/p/locations/us/glossaries/ecommerce-glossary", "ignored")
    'projects/p/locations/us/glossaries/ecommerce-glossary'
    """
    return generated_id if explicit_id is None else explicit_id
