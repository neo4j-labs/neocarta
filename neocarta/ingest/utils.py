"""Utility functions for ingesting data into Neo4j."""

from neo4j import Driver, RoutingControl
from pydantic import BaseModel

from ..enums import NodeLabel, RelationshipType
from ..errors import ConfigError


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
        print(f"Error checking enterprise edition: {e}")
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


def _build_node_ingest_query(
    node_label: NodeLabel,
    overwrite_existing: bool,
    properties_list: list[str],
    secondary_labels: list[NodeLabel] | None = None,
) -> str:
    """
    Build a node ingest query for a given node label, overwrite existing flag, and properties list.
    Will return a MERGE query that sets properties according to the configuration.

    Parameters
    ----------
    node_label: str
        The label of the node to ingest.
    overwrite_existing: bool
        Whether to overwrite existing nodes on MATCH.
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
    query = f"""
UNWIND $rows as row
MERGE (n:{node_label} {{id: row.id}})
"""

    secondary_labels = secondary_labels or []
    # Only add ON CREATE and SET if there are secondary labels or properties to set
    if len(properties_list) == 0 and not secondary_labels:
        return query.rstrip()

    # Determine indentation based on overwrite setting
    if not overwrite_existing:
        query += "ON CREATE\n    SET "
        indent = " " * 8  # 8 spaces for continuation lines
    else:
        query += "SET "
        indent = " " * 4  # 4 spaces for continuation lines

    set_items = [f"n:{label}" for label in secondary_labels] + [
        f"n.{prop} = row.{prop}" for prop in properties_list
    ]
    query += (",\n" + indent).join(set_items)

    return query


def _build_relationship_ingest_query(
    relationship_type: RelationshipType,
    source_node_label: NodeLabel,
    target_node_label: NodeLabel,
    source_id_column_name: str,
    target_id_column_name: str,
    overwrite_existing: bool,
    properties_list: list[str],
) -> str:
    """Build a relationship ingest query for a given relationship type, source node label, target node label, source id column name, target id column name, overwrite existing flag, and properties list."""
    query = f"""
UNWIND $rows as row
MATCH (n1:{source_node_label} {{id: row.{source_id_column_name}}})
MATCH (n2:{target_node_label} {{id: row.{target_id_column_name}}})
MERGE (n1)-[r:{relationship_type}]->(n2)
"""
    # Only add ON CREATE and SET if there are properties to set
    if len(properties_list) == 0:
        return query.rstrip()

    # Determine indentation based on overwrite setting
    if not overwrite_existing:
        query += "ON CREATE\n    SET "
        indent = " " * 8  # 8 spaces for continuation lines
    else:
        query += "SET "
        indent = " " * 4  # 4 spaces for continuation lines

    for idx, prop in enumerate(properties_list):
        query += f"r.{prop} = row.{prop}"
        if idx < len(properties_list) - 1:
            query += ",\n" + indent

    return query
