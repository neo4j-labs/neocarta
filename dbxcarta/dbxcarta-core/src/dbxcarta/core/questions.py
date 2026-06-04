"""Shared data shapes for example question *generation*.

These are the containers both the dense-schema and schemapile question
generators produce. They are deliberately separate from
:mod:`dbxcarta.client.questions`, which holds the *consumption* model that
Client loads and validates from the serialized questions fixture. The two
share a leaf module name by coincidence of concern, not by design, and must
not be collapsed: ``GeneratedPair`` carries generation metadata, while the
client's ``Question`` is the consumption shape with its own validators. The
serialized fixture is the seam between them, matching the "primary output of
generation, side input of Client" relationship in the stage contracts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedPair:
    """One generated (question, SQL) record tied to its source schema."""

    uc_schema: str
    source_id: str
    shape: str
    question: str
    sql: str


@dataclass
class ValidationOutcome:
    """Tally of a validation pass: the accepted pairs plus rejection counts."""

    accepted: list[GeneratedPair]
    errored: int = 0
    empty: int = 0
    trivial: int = 0
