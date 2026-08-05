"""Every tabular transformer is visible to the #291 Layer A harness.

Found while building the S1.6 (#297) parity proof: ``serialize_transform`` discovered families
only through ``@property`` accessors, but four of the nine tabular transformers assign theirs
as plain instance attributes in ``__init__``. For those it returned ``{}`` — and an empty dict
compares equal to an empty golden, so anyone capturing one would have committed a
characterization test that passed while guarding nothing.

That matters well beyond this ticket: every S4 connector cutover is supposed to be guarded by a
Layer A golden captured first (GUIDE §4), and four connectors could not have one. So this
suite pins discovery for **all** of them rather than only the ones S1.6 happened to need.
"""

from __future__ import annotations

import importlib

import pytest

from tests.support.characterization import serialize_transform

#: Every tabular transformer, with the family count it must expose. The four marked below
#: returned zero before this fix; the counts are pinned so a regression is a failure rather
#: than a silently thinner golden.
TABULAR_TRANSFORMERS = [
    ("bigquery.schema", "BigQuerySchemaTransformer", 10),
    ("csv", "CSVTransformer", 20),
    ("jdbc.schema", "JdbcSchemaTransformer", 8),
    ("query_log", "QueryLogTransformer", 13),
    ("databricks.schema", "DatabricksSchemaTransformer", 10),
    ("snowflake.schema", "SnowflakeSchemaTransformer", 10),
    ("unity_catalog.schema", "UnityCatalogSchemaTransformer", 7),  # was 0
    ("dataplex.schema", "DataplexSchemaTransformer", 7),  # was 0
    ("dataplex.glossary", "DataplexGlossaryTransformer", 7),  # was 0
    ("databricks.tags", "DatabricksTagsTransformer", 3),  # was 0
]

#: The four that used to be invisible — called out separately so the regression this fixes
#: cannot be reintroduced by loosening the counts above.
PREVIOUSLY_INVISIBLE = frozenset(
    {
        "UnityCatalogSchemaTransformer",
        "DataplexSchemaTransformer",
        "DataplexGlossaryTransformer",
        "DatabricksTagsTransformer",
    }
)


def _transformer(module: str, name: str) -> object:
    """Instantiate a connector transformer by module path and class name."""
    return getattr(importlib.import_module(f"neocarta.connectors.{module}.transform"), name)()


@pytest.mark.parametrize(("module", "name", "expected"), TABULAR_TRANSFORMERS)
def test_every_family_is_discovered(module: str, name: str, expected: int) -> None:
    """A fresh transformer exposes exactly its documented family count."""
    assert len(serialize_transform(_transformer(module, name))) == expected


@pytest.mark.parametrize(("module", "name", "expected"), TABULAR_TRANSFORMERS)
def test_no_transformer_serializes_to_nothing(module: str, name: str, expected: int) -> None:
    """The failure mode itself: an empty dict would compare equal to an empty golden."""
    assert serialize_transform(_transformer(module, name)) != {}
    assert expected > 0


def test_instance_attribute_families_are_found() -> None:
    """The mechanism of the fix, on a minimal transformer with no properties at all."""

    class AttributeOnly:
        def __init__(self) -> None:
            self.thing_nodes: list[str] = []
            self.other_relationships: list[str] = []
            self._private_nodes: list[str] = []
            self.not_a_family = []

    assert sorted(serialize_transform(AttributeOnly())) == [
        "other_relationships",
        "thing_nodes",
    ]


def test_the_four_previously_invisible_transformers_are_covered() -> None:
    """Guard the guard: keep the regression cases in the parametrized set above."""
    covered = {name for _, name, _ in TABULAR_TRANSFORMERS}
    assert covered >= PREVIOUSLY_INVISIBLE
