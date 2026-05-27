"""Extract an OSI semantic model subgraph from Neo4j."""

from typing import Any

from neo4j import Driver


class OsiGraphExtractor:
    """
    Read an OSI semantic model from Neo4j by name, returning a structured snapshot
    that the export transformer can serialize back to OSI YAML.

    Parameters
    ----------
    driver : neo4j.Driver
        Connected Neo4j driver.
    database_name : str, default "neo4j"
        Target Neo4j database.
    """

    def __init__(self, driver: Driver, database_name: str = "neo4j") -> None:
        self.driver = driver
        self.database_name = database_name
        self.snapshot: dict[str, Any] | None = None

    def extract(self, semantic_model_name: str) -> dict[str, Any]:
        """
        Read the OSI semantic model with the given ``name`` from Neo4j.

        Parameters
        ----------
        semantic_model_name : str
            Matches against :OsiSemanticModel.name (unique within the OSI subgraph).

        Returns:
        -------
        dict[str, Any]
            A structured snapshot keyed by entity type (schemas, tables, columns, metrics,
            joins, dimensions, expressions, aspects, business_terms) plus relationship
            lists. Cached on the instance as ``self.snapshot``.
        """
        raise NotImplementedError("OsiGraphExtractor.extract is not yet implemented")
