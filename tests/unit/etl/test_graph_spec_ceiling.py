"""Pins the Graph Spec expressiveness ceiling the S1.6 (#297) verdict rests on.

S1.6 decided that the Neo4j Graph Spec (``neo4j/import-spec``) is **not** the
connector→normalized mapping mechanism. That verdict is a claim about the *format*, so it is
asserted here against the vendored, tag-pinned schema (``tests/support/graph_spec/``) rather than
left as prose that nothing re-checks — GUIDE §9, *"acceptance criteria should be objectively
checkable."*

Upstream is an RC with no GA (rc01 … rc21 at the time of writing). These tests are therefore
**designed to fail** if a newer release candidate widens the format: that failure is the GUIDE
**D13** signal that the verdict's premise moved and deserves a fresh look. It is not a flake —
see ``docs/refactor/mapping-mechanism.md`` and the re-pinning steps in
``tests/support/graph_spec/README.md``.

Nothing here imports Graph Spec at runtime. There is no JVM and no new production dependency
(GUIDE §6 — *"adapt behind our boundary, don't block on it"*).
"""

from __future__ import annotations

import pytest

from tests.support.graph_spec import SPEC_VERSION, definition, load_spec_schema, spec_schema_text

# The transformation vocabulary a declarative mapping mechanism would need, and which the format
# does not have anywhere. Absence is the finding: everything a connector's transform.py does
# beyond rename + cast has to leave the spec entirely — a Java SPI plugin or a raw-Cypher
# `target.query` — which is what makes Graph Spec *more* complex than the Python it replaces.
ABSENT_TRANSFORMATION_KEYWORDS = frozenset(
    {
        "transformation",  # the older Dataflow job-spec had `source_transformations`; v1 does not
        "aggregat",  # aggregate / aggregation — no groupby
        "order_by",
        "limit",
        "where",  # no row filter — the self-FK drop is inexpressible
        "filter",
        "default",  # no default value — cannot inject `platform="GCP"`
        "expression",  # no computed value — cannot construct an id
        "literal",
        "constant",
        "unwind",
        "explode",
        "dedup",
        "distinct",
    }
)


class TestPropertyMappingIsRenameAndCastOnly:
    """The mapping surface is capped at rename + optional cast, and the cap is enforced."""

    def test_property_mapping_has_exactly_three_keys(self) -> None:
        """A property mapping is a source field, a target property, and an optional type."""
        assert set(definition("target.entity.propertyMapping")["properties"]) == {
            "source_field",
            "target_property",
            "target_property_type",
        }

    def test_property_mapping_forbids_extra_keys(self) -> None:
        """``additionalProperties: false`` makes the ceiling enforced, not conventional.

        The load-bearing assertion: without it the ceiling would merely be undocumented, and a
        mechanism could smuggle an expression or a default into an unknown key. The schema
        rejects that outright.
        """
        assert definition("target.entity.propertyMapping")["additionalProperties"] is False

    def test_no_transformation_vocabulary_exists_in_the_format(self) -> None:
        """None of the transformation keywords appears anywhere in the schema.

        Asserted document-wide rather than per-definition, because the claim is that the
        capability is absent from the *format* — a connector cannot reach it from any block.
        """
        schema = spec_schema_text().lower()
        present = sorted(word for word in ABSENT_TRANSFORMATION_KEYWORDS if word in schema)
        assert not present, f"the format gained transformation vocabulary: {present}"

    def test_the_absence_search_is_not_vacuous(self) -> None:
        """Sensitivity control: the same search finds vocabulary that *is* present.

        Without this, the assertion above would pass just as happily against an empty file.
        """
        schema = spec_schema_text().lower()
        assert all(
            word in schema for word in ("properties", "labels", "write_mode", "source_field")
        )


class TestStaticPropertyListConflictsWithD10:
    """The primary refutation: a static property list cannot honour the merge contract.

    ``docs/refactor/merge-contract.md`` (S1.3, #294) ratified **D10** non-clobber merge — partial
    data must never erase fuller data — and ``MergePolicy.COALESCE`` implements the value-level
    half as ``n.p = coalesce(row.p, n.p)``. Graph Spec offers a static ``properties`` array plus
    ``write_mode: merge`` and nothing else, so every declared property is written on every row.
    In Cypher ``SET n.description = null`` *removes* the property, so a target declaring
    ``description`` erases a description another connector wrote on every row where this source
    has none. With no ``default``, ``expression`` or ``filter`` in the format (asserted above), it
    cannot be patched spec-side.
    """

    def test_write_mode_offers_only_create_or_merge(self) -> None:
        """There is no coalescing write mode — these two options are the whole choice."""
        assert set(definition("target.entity.base")["properties"]["write_mode"]["enum"]) == {
            "create",
            "CREATE",
            "merge",
            "MERGE",
        }

    def test_an_entity_target_has_no_other_knob(self) -> None:
        """Write mode and a property list are the only configuration, so nothing carries scope."""
        assert set(definition("target.entity.base")["properties"]) == {"write_mode", "properties"}

    def test_the_property_list_is_static(self) -> None:
        """``properties`` is a fixed array of mappings, so membership cannot vary per row."""
        properties = definition("target.entity.base")["properties"]["properties"]
        assert properties["type"] == "array"
        assert properties["items"]["$ref"] == "#/$defs/target.entity.propertyMapping"


class TestRelationshipEndpointsAreSingleTargetReferences:
    """A relationship target binds to exactly one node target, so no row-dependent label.

    ``BusinessTermAssignmentRecord`` addresses its tagged asset by key-path **depth** —
    ``column_name`` set means column grain, absent means table grain — deliberately with no
    ``source_label`` discriminator (``normalized_schema/facets.py``). Graph Spec cannot route
    that: ``start_node_reference`` names one declared node target, and there is no ``where``
    clause to split a mixed-grain source. The polymorphic ``TaggedWith``
    (``Literal["Column", "Table", "Schema", "Metric"]``) therefore needs N relationship targets,
    one per grain.
    """

    @pytest.mark.parametrize("side", ["start_node_reference", "end_node_reference"])
    def test_an_endpoint_is_a_named_target_or_a_key_mapping_object(self, side: str) -> None:
        """Both admitted forms name a single node target."""
        reference = definition("target.relationship")["properties"][side]
        assert reference["then"]["$ref"] == "#/$defs/target.relationship.node.reference"
        assert reference["else"]["type"] == "string"

    def test_a_key_mapping_object_names_exactly_one_target(self) -> None:
        """``name`` is singular and required — one reference cannot span two node targets."""
        reference = definition("target.relationship.node.reference")
        assert set(reference["required"]) == {"name", "key_mappings"}
        assert reference["properties"]["name"]["type"] == "string"

    def test_endpoint_keys_are_rename_only(self) -> None:
        """Endpoint keys are source-field → node-property renames, with no computation.

        Neocarta survives this downstream only because it pre-computes every node ``id`` in
        Python, so each mapping is the trivial ``<x>_id`` → ``id``.
        """
        mapping = definition("target.relationship.node.reference")["properties"]["key_mappings"]
        assert set(mapping["items"]["properties"]) == {"source_field", "node_property"}


class TestSourcesCarryNoFieldVocabulary:
    """Graph Spec is not the normalization intermediate standard either.

    A ``source`` is an open-ended connection/query descriptor whose real shape lives behind the
    Java ``SourceProvider`` SPI. It has no notion of a canonical field vocabulary, so it cannot
    carry the x6 container / x4 data-type / x3 nullability resolution
    ``normalized_schema/_vocabulary.py`` owns.
    """

    def test_a_source_declares_only_a_type_and_a_name(self) -> None:
        """Everything else about a source is provider-defined, not schema-defined."""
        assert set(definition("source")["properties"]) == {"type", "name"}
        assert set(definition("source")["required"]) == {"type", "name"}

    def test_a_source_is_open_ended(self) -> None:
        """``additionalProperties: true`` — the opposite of the property mapping's closed cap."""
        assert definition("source")["additionalProperties"] is True


def test_the_vendored_schema_is_the_version_the_verdict_names() -> None:
    """Keep the pinned artifact and the version the design doc cites together.

    Also guards the major version, so a ``v2`` document cannot slip in as a silently different
    format under the same filename.
    """
    assert SPEC_VERSION == "v1.0.0-rc21"
    assert load_spec_schema()["properties"]["version"]["const"] == "1"


def test_the_only_escape_hatch_is_raw_cypher() -> None:
    """Recorded because it is the fallback a reader will propose.

    A ``query`` target replaces typed Python with untyped Cypher strings and loses
    ``_validate_properties_list``, which today rejects a property absent from the graph model.
    """
    assert definition("target.query")["required"] == ["query"]
    assert definition("target.query")["properties"]["query"]["type"] == "string"
