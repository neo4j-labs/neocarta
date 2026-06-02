"""Neo4j constraint definitions for the RDBMS data model."""

from neocarta.ingest.constraints import (
    database_id_key_constraint,
    database_id_unique_constraint,
    schema_id_key_constraint,
    schema_id_unique_constraint,
    value_id_key_constraint,
    value_id_unique_constraint,
)

from ...enums import NodeLabel

table_id_unique_constraint = """
CREATE CONSTRAINT table_id_constraint IF NOT EXISTS
FOR (t:Table) REQUIRE t.id IS UNIQUE;
"""

table_id_key_constraint = table_id_unique_constraint.replace("UNIQUE", "NODE KEY")

column_id_unique_constraint = """
CREATE CONSTRAINT column_id_constraint IF NOT EXISTS
FOR (c:Column) REQUIRE c.id IS UNIQUE;
"""

column_id_key_constraint = column_id_unique_constraint.replace("UNIQUE", "NODE KEY")

glossary_id_unique_constraint = """
CREATE CONSTRAINT glossary_id_constraint IF NOT EXISTS
FOR (g:Glossary) REQUIRE g.id IS UNIQUE;
"""

glossary_id_key_constraint = glossary_id_unique_constraint.replace("UNIQUE", "NODE KEY")

business_term_id_unique_constraint = """
CREATE CONSTRAINT business_term_id_constraint IF NOT EXISTS
FOR (b:BusinessTerm) REQUIRE b.id IS UNIQUE;
"""

business_term_id_key_constraint = business_term_id_unique_constraint.replace("UNIQUE", "NODE KEY")


category_id_unique_constraint = """
CREATE CONSTRAINT category_id_constraint IF NOT EXISTS
FOR (c:Category) REQUIRE c.id IS UNIQUE;
"""

category_id_key_constraint = category_id_unique_constraint.replace("UNIQUE", "NODE KEY")

query_id_unique_constraint = """
CREATE CONSTRAINT query_id_constraint IF NOT EXISTS
FOR (q:Query) REQUIRE q.id IS UNIQUE;
"""

query_id_key_constraint = query_id_unique_constraint.replace("UNIQUE", "NODE KEY")

cte_id_unique_constraint = """
CREATE CONSTRAINT cte_id_constraint IF NOT EXISTS
FOR (c:CTE) REQUIRE c.id IS UNIQUE;
"""

cte_id_key_constraint = cte_id_unique_constraint.replace("UNIQUE", "NODE KEY")

domain_id_unique_constraint = """
CREATE CONSTRAINT domain_id_constraint IF NOT EXISTS
FOR (d:Domain) REQUIRE d.id IS UNIQUE;
"""
domain_id_key_constraint = domain_id_unique_constraint.replace("UNIQUE", "NODE KEY")

metric_id_unique_constraint = """
CREATE CONSTRAINT metric_id_constraint IF NOT EXISTS
FOR (m:Metric) REQUIRE m.id IS UNIQUE;
"""
metric_id_key_constraint = metric_id_unique_constraint.replace("UNIQUE", "NODE KEY")

join_id_unique_constraint = """
CREATE CONSTRAINT join_id_constraint IF NOT EXISTS
FOR (j:Join) REQUIRE j.id IS UNIQUE;
"""
join_id_key_constraint = join_id_unique_constraint.replace("UNIQUE", "NODE KEY")

expression_id_unique_constraint = """
CREATE CONSTRAINT expression_id_constraint IF NOT EXISTS
FOR (e:Expression) REQUIRE e.id IS UNIQUE;
"""
expression_id_key_constraint = expression_id_unique_constraint.replace("UNIQUE", "NODE KEY")

aspect_id_unique_constraint = """
CREATE CONSTRAINT aspect_id_constraint IF NOT EXISTS
FOR (a:Aspect) REQUIRE a.id IS UNIQUE;
"""
aspect_id_key_constraint = aspect_id_unique_constraint.replace("UNIQUE", "NODE KEY")

UNIQUE_CONSTRAINTS_LOOKUP = {
    NodeLabel.DATABASE: database_id_unique_constraint,
    NodeLabel.SCHEMA: schema_id_unique_constraint,
    NodeLabel.TABLE: table_id_unique_constraint,
    NodeLabel.COLUMN: column_id_unique_constraint,
    NodeLabel.VALUE: value_id_unique_constraint,
    NodeLabel.GLOSSARY: glossary_id_unique_constraint,
    NodeLabel.CATEGORY: category_id_unique_constraint,
    NodeLabel.BUSINESS_TERM: business_term_id_unique_constraint,
    NodeLabel.QUERY: query_id_unique_constraint,
    NodeLabel.CTE: cte_id_unique_constraint,
    NodeLabel.DOMAIN: domain_id_unique_constraint,
    NodeLabel.METRIC: metric_id_unique_constraint,
    NodeLabel.JOIN: join_id_unique_constraint,
    NodeLabel.EXPRESSION: expression_id_unique_constraint,
    NodeLabel.ASPECT: aspect_id_unique_constraint,
}

KEY_CONSTRAINTS_LOOKUP = {
    NodeLabel.DATABASE: database_id_key_constraint,
    NodeLabel.SCHEMA: schema_id_key_constraint,
    NodeLabel.TABLE: table_id_key_constraint,
    NodeLabel.COLUMN: column_id_key_constraint,
    NodeLabel.VALUE: value_id_key_constraint,
    NodeLabel.GLOSSARY: glossary_id_key_constraint,
    NodeLabel.CATEGORY: category_id_key_constraint,
    NodeLabel.BUSINESS_TERM: business_term_id_key_constraint,
    NodeLabel.QUERY: query_id_key_constraint,
    NodeLabel.CTE: cte_id_key_constraint,
    NodeLabel.DOMAIN: domain_id_key_constraint,
    NodeLabel.METRIC: metric_id_key_constraint,
    NodeLabel.JOIN: join_id_key_constraint,
    NodeLabel.EXPRESSION: expression_id_key_constraint,
    NodeLabel.ASPECT: aspect_id_key_constraint,
}
