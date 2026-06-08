"""Shared Pydantic models for the neocarta and dbxcarta graph data model.

``carta-schema`` is the single source of truth for the core RDBMS graph schema.
Both ``neocarta`` and the ``dbxcarta`` packages depend on it so there is one
definition of the node and relationship models, with no mirror copy to drift.

The package is deliberately tiny: it pulls in only ``pydantic`` and ``pandas``,
never the source connectors or Spark, so it is cheap to ship to a Databricks
cluster.

Submodules are imported directly, for example
``from carta_schema.rdbms.core import Column``; this package root re-exports
nothing.
"""
