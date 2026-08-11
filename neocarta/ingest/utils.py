"""Utility functions for ingesting data into Neo4j."""

import logging
from enum import Enum

from neo4j import Driver, RoutingControl
from pydantic import BaseModel

from ..enums import NodeLabel, RelationshipType
from ..errors import ConfigError

logger = logging.getLogger(__name__)


class MergePolicy(str, Enum):
    """How a write reconciles an incoming row with an entity that already exists.

    These three policies partition the whole space of "what happens to a property
    when the ``MERGE`` matches an entity that an earlier write — a previous run, or
    another connector — already created":

    - ``CREATE_ONLY`` — properties are written only when the entity is created, so a
      later, fuller row can never enrich it (first writer wins).
    - ``OVERWRITE`` — properties are written on every merge, ``NULL`` included, so an
      incoming ``NULL`` erases a stored value.
    - ``COALESCE`` — properties are written on every merge, but an incoming ``NULL``
      never replaces a stored value. This is the GUIDE D10 **non-clobber** merge: a
      sparse row and a full row for the same entity accumulate, in either order.

    ``COALESCE`` is the value-level half of the contract only. Which properties are in
    scope for a write at all remains the caller's ``properties_list``, and that
    property-scope layer is what a source with no tri-state for a field (e.g.
    ``Column.nullable``, whose ``True`` default is indistinguishable from an asserted
    ``True``) needs in order to stay non-clobbering.

    See ``docs/refactor/merge-contract.md`` for the full contract.
    """

    CREATE_ONLY = "create_only"
    OVERWRITE = "overwrite"
    COALESCE = "coalesce"


def _resolve_merge_policy(merge_policy: bool | str | MergePolicy) -> MergePolicy:
    """Normalize a merge policy, accepting the legacy ``overwrite_existing`` flag.

    Args:
        merge_policy: A :class:`MergePolicy` (or its string value), or the legacy
            ``overwrite_existing`` flag, where a truthy value means ``OVERWRITE`` and a
            falsy one ``CREATE_ONLY``.

    Returns:
        The resolved :class:`MergePolicy`.

    Raises:
        ConfigError: If ``merge_policy`` is a string that is not a known policy value.
    """
    if isinstance(merge_policy, MergePolicy):
        return merge_policy
    if isinstance(merge_policy, str):
        # Checked before the legacy branch, and strictly: a string is unambiguously
        # meant as a policy name, so a misspelling must fail loudly rather than fall
        # through to the truthy branch and silently select destructive OVERWRITE.
        try:
            return MergePolicy(merge_policy)
        except ValueError as e:
            raise ConfigError(
                f"Unknown merge policy {merge_policy!r}; expected one of "
                f"{[policy.value for policy in MergePolicy]}."
            ) from e
    # The legacy ``overwrite_existing`` flag, resolved by truthiness rather than a strict
    # bool check: the parameter was annotated ``bool`` but accepted anything truthy, and
    # connectors read pandas frames, so a numpy bool must keep behaving as it did.
    return MergePolicy.OVERWRITE if merge_policy else MergePolicy.CREATE_ONLY


def is_enterprise_edition(neo4j_driver: Driver, database_name: str = "neo4j") -> bool:
    """
    Check if using enterprise edition of Neo4j.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    database_name: str
        The name of the database to check the edition of.

    Returns:
    -------
    bool
        True if the Neo4j database is running in enterprise edition, False otherwise.
    """
    try:
        results = neo4j_driver.execute_query(
            query_="""
call dbms.components()
yield name, versions, edition
where name = "Neo4j Kernel"
return name, versions, edition
""",
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
            database_=database_name,
        )
        return results[0]["edition"] == "enterprise"
    except Exception as e:
        logger.warning("Error checking enterprise edition: %s", e)
        return False


def write_neo4j_constraints(
    neo4j_driver: Driver,
    node_labels: list[NodeLabel],
    key_constraints: dict[NodeLabel, str],
    unique_constraints: dict[NodeLabel, str],
    database_name: str = "neo4j",
) -> dict:
    """
    Write constraints to the database according to which edition is being used.
    Iterate over a list of node labels and write the appropriate constraints.
    Searches for appropriate constraint in the provided key and unique constraints lookupdictionaries.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to write constraints to.
    node_labels: list[str]
        The labels of the nodes to write constraints for.
    key_constraints: dict[str, str]
        A dictionary of key constraints to write.
    unique_constraints: dict[str, str]
        A dictionary of unique constraints to write.
    database_name: str
        The name of the database to write constraints to.

    Returns:
    -------
    dict
        The summary of the constraints written.
    """
    is_enterprise = is_enterprise_edition(neo4j_driver, database_name)
    summaries = [{"enterprise_edition": is_enterprise}]

    if is_enterprise:
        # use key constraints for enterprise edition
        for node_label in node_labels:
            try:
                c = key_constraints[node_label]
            except KeyError as e:
                raise ConfigError(
                    f"Node key constraint not found for node label {node_label}."
                ) from e
            _, summary, _ = neo4j_driver.execute_query(
                query_=c, routing_=RoutingControl.WRITE, database_=database_name
            )
            summaries.append(summary.counters.__dict__)
    else:
        # use unique constraints for community edition, node keys are not supported
        for node_label in node_labels:
            try:
                c = unique_constraints[node_label]
            except KeyError as e:
                raise ConfigError(
                    f"Node unique constraint not found for node label {node_label}."
                ) from e
            _, summary, _ = neo4j_driver.execute_query(
                query_=c, routing_=RoutingControl.WRITE, database_=database_name
            )
            summaries.append(summary.counters.__dict__)
    return summaries


def _validate_properties_list(model: BaseModel, properties_list: list[str]) -> None:
    """
    Validate the properties list for a given Pydantic model.
    Will raise an error if any properties are not found in the model fields.

    Parameters
    ----------
    model: BaseModel
        The Pydantic model to validate the properties list for.
    properties_list: list[str]
        The list of properties to validate.

    Raises:
    ------
    ConfigError
        If any properties are not found in the model fields.
    """
    invalid_props = set(properties_list) - set(model.model_fields)
    if invalid_props:
        raise ConfigError(
            f"Properties list contains invalid properties for model {model.__class__.__name__}: {invalid_props}"
        )


def _node_pattern(node_label: NodeLabel) -> str:
    """
    Return a human-readable Cypher-style node pattern for logging.

    Examples:
    --------
    >>> _node_pattern(NodeLabel.COLUMN)
    '(:Column)'
    """
    return f"(:{node_label})"


def _relationship_pattern(
    relationship_type: RelationshipType,
    source_node_label: NodeLabel,
    target_node_label: NodeLabel,
) -> str:
    """
    Return a human-readable Cypher-style relationship pattern for logging.

    Examples:
    --------
    >>> _relationship_pattern(
    ...     RelationshipType.TAGGED_WITH, NodeLabel.COLUMN, NodeLabel.BUSINESS_TERM
    ... )
    '(:Column)-[:TAGGED_WITH]->(:BusinessTerm)'
    """
    return f"(:{source_node_label})-[:{relationship_type}]->(:{target_node_label})"


def _build_node_ingest_query(
    node_label: NodeLabel,
    merge_policy: bool | str | MergePolicy,
    properties_list: list[str],
    secondary_labels: list[NodeLabel] | None = None,
) -> str:
    """
    Build a node ingest query for a given node label, merge policy, and properties list.
    Will return a MERGE query that sets properties according to the configuration.

    Parameters
    ----------
    node_label: str
        The label of the node to ingest.
    merge_policy: bool | str | MergePolicy
        How to reconcile a row against a node that already exists — see
        :class:`MergePolicy`. The legacy boolean spelling is accepted, where
        ``True`` means ``OVERWRITE`` and ``False`` means ``CREATE_ONLY``.
    properties_list: list[str]
        The list of properties to set on the node.
    secondary_labels: list[NodeLabel] | None
        Optional additional labels to tag onto the node alongside ``node_label``.
        Used for subtype labels such as ``:Table:OsiTable``. Each label is added
        in the same SET clause as the property assignments.

    Returns:
    -------
    str
        The MERGE query to ingest the nodes.
    """
    policy = _resolve_merge_policy(merge_policy)
    query = f"""
UNWIND $rows as row
MERGE (n:{node_label} {{id: row.id}})
"""

    secondary_labels = secondary_labels or []
    if len(properties_list) == 0 and not secondary_labels:
        return query.rstrip()

    label_items = [f"n:{label}" for label in secondary_labels]
    if policy is MergePolicy.COALESCE:
        # Non-clobber (D10): an incoming NULL keeps whatever is already stored, so a
        # sparse row can never erase a fuller one and both feed orders converge on the
        # same node. Re-emitting a row rewrites identical values, so it is a no-op on stored
        # state (the SET still executes, so Neo4j still counts a property write).
        prop_items = [f"n.{prop} = coalesce(row.{prop}, n.{prop})" for prop in properties_list]
    else:
        prop_items = [f"n.{prop} = row.{prop}" for prop in properties_list]

    if policy is not MergePolicy.CREATE_ONLY:
        # Apply labels AND properties on every MERGE.
        all_items = label_items + prop_items
        query += "SET " + (",\n    ").join(all_items)
        return query

    # CREATE_ONLY: properties only fire on first create, but secondary labels must apply
    # regardless so the OSI subtype label sticks even when the node was created by a
    # prior call or another connector. This requires both ON CREATE SET and ON MATCH SET.
    create_items = label_items + prop_items
    query += "ON CREATE\n    SET " + (",\n        ").join(create_items)
    if label_items:
        query += "\nON MATCH\n    SET " + (",\n        ").join(label_items)
    return query


def _build_relationship_ingest_query(
    relationship_type: RelationshipType,
    source_node_label: NodeLabel,
    target_node_label: NodeLabel,
    source_id_column_name: str,
    target_id_column_name: str,
    merge_policy: bool | str | MergePolicy,
    properties_list: list[str],
) -> str:
    """
    Build a relationship ingest query, mirroring :func:`_build_node_ingest_query`.

    Parameters
    ----------
    relationship_type: RelationshipType
        The type of the relationship to ingest.
    source_node_label: NodeLabel
        The label of the relationship's start node.
    target_node_label: NodeLabel
        The label of the relationship's end node.
    source_id_column_name: str
        The row key holding the start node's ``id``.
    target_id_column_name: str
        The row key holding the end node's ``id``.
    merge_policy: bool | str | MergePolicy
        How to reconcile a row against a relationship that already exists — see
        :class:`MergePolicy`. The legacy boolean spelling is accepted, where
        ``True`` means ``OVERWRITE`` and ``False`` means ``CREATE_ONLY``.
    properties_list: list[str]
        The list of properties to set on the relationship.

    Returns:
    -------
    str
        The MERGE query to ingest the relationships.
    """
    policy = _resolve_merge_policy(merge_policy)
    query = f"""
UNWIND $rows as row
MATCH (n1:{source_node_label} {{id: row.{source_id_column_name}}})
MATCH (n2:{target_node_label} {{id: row.{target_id_column_name}}})
MERGE (n1)-[r:{relationship_type}]->(n2)
"""
    # Only add ON CREATE and SET if there are properties to set
    if len(properties_list) == 0:
        return query.rstrip()

    # Determine indentation based on when the properties fire
    if policy is MergePolicy.CREATE_ONLY:
        query += "ON CREATE\n    SET "
        indent = " " * 8  # 8 spaces for continuation lines
    else:
        query += "SET "
        indent = " " * 4  # 4 spaces for continuation lines

    for idx, prop in enumerate(properties_list):
        if policy is MergePolicy.COALESCE:
            # Non-clobber (D10) — see the note in _build_node_ingest_query.
            query += f"r.{prop} = coalesce(row.{prop}, r.{prop})"
        else:
            query += f"r.{prop} = row.{prop}"
        if idx < len(properties_list) - 1:
            query += ",\n" + indent

    return query
