"""OSI domain-context cypher query (full context of one semantic model)."""


def get_domain_context_cypher() -> str:
    """
    Get the cypher query to retrieve the full context of one OSI domain.

    Returns the domain's description and OSI version, every dataset (table) with its
    columns (each column carrying its dialect-specific expressions and aspects), every
    metric with its expressions / synonyms / aspects, the joins between datasets, and the
    domain-level aspects. Bounded to a single semantic model so the payload stays sane.

    Notes:
    -----
    Expected Cypher parameters:

    domainId : str
        The ``:Domain`` node id (resolve from the domain name via
        ``generate_osi_semantic_model_id``).

    Returns:
    -------
    str
        A single ``result`` map matching the ``DomainContext`` model.
    """
    return """
MATCH (d:Domain {id: $domainId})
RETURN {
    domain_name: d.name,
    domain_description: d.description,
    osi_version: d.osi_version,
    tables: COLLECT {
        // Datasets are OsiTable (HAS_TABLE) or query-backed Query (HAS_QUERY) nodes.
        MATCH (d)-[:HAS_TABLE|HAS_QUERY]->(t:Table|Query)
        RETURN {
            table_name: t.name,
            table_description: t.description,
            database_name: head([(t)<-[:HAS_TABLE]-(s:Schema)<-[:HAS_SCHEMA]-(db:Database) | db.name]),
            schema_name: head([(t)<-[:HAS_TABLE]-(s:Schema) | s.name]),
            primary_key: coalesce(t.primary_key, []),
            num_columns: COUNT { (t)-[:HAS_COLUMN|USES_COLUMN]->(:Column) },
            columns: COLLECT {
                MATCH (t)-[:HAS_COLUMN|USES_COLUMN]->(col:Column)
                RETURN {
                    column_name: col.name,
                    column_description: col.description,
                    data_type: col.type,
                    label: col.label,
                    is_time_dimension: col.is_time_dimension,
                    nullable: col.nullable,
                    key_type: CASE
                        WHEN col.is_primary_key THEN "primary"
                        WHEN col.is_foreign_key THEN "foreign"
                        ELSE null
                    END,
                    references: COLLECT {
                        MATCH (col)-[:REFERENCES]->(refCol:Column)<-[:HAS_COLUMN]-(refTable:Table)
                        RETURN refTable.name + "." + refCol.name
                    },
                    expressions: COLLECT {
                        MATCH (col)-[:HAS_EXPRESSION]->(e:Expression)
                        RETURN {dialect: e.dialect, expression: e.expression}
                    },
                    aspects: COLLECT {
                        MATCH (col)-[:HAS_ASPECT]->(a:Aspect)
                        RETURN {
                            aspect_type: CASE
                                WHEN a:OsiAiContext THEN "ai_context"
                                WHEN a:OsiCustomExtensions THEN "custom_extensions"
                                ELSE "unknown"
                            END,
                            data: a.data,
                            vendor_name: a.vendor_name
                        }
                    }
                }
            },
            aspects: COLLECT {
                MATCH (t)-[:HAS_ASPECT]->(a:Aspect)
                RETURN {
                    aspect_type: CASE
                        WHEN a:OsiAiContext THEN "ai_context"
                        WHEN a:OsiCustomExtensions THEN "custom_extensions"
                        ELSE "unknown"
                    END,
                    data: a.data,
                    vendor_name: a.vendor_name
                }
            }
        }
    },
    metrics: COLLECT {
        MATCH (d)-[:HAS_METRIC]->(m:Metric)
        RETURN {
            metric_name: m.name,
            metric_description: m.description,
            domain_name: d.name,
            expressions: COLLECT {
                MATCH (m)-[:HAS_EXPRESSION]->(e:Expression)
                RETURN {dialect: e.dialect, expression: e.expression}
            },
            synonyms: COLLECT {
                MATCH (m)-[:TAGGED_WITH]->(bt:BusinessTerm)
                RETURN bt.name
            },
            aspects: COLLECT {
                MATCH (m)-[:HAS_ASPECT]->(a:Aspect)
                RETURN {
                    aspect_type: CASE
                        WHEN a:OsiAiContext THEN "ai_context"
                        WHEN a:OsiCustomExtensions THEN "custom_extensions"
                        ELSE "unknown"
                    END,
                    data: a.data,
                    vendor_name: a.vendor_name
                }
            },
            backing_tables: COLLECT {
                MATCH (m)-[:USES_TABLE]->(mt)
                RETURN mt.name
            },
            backing_columns: COLLECT {
                MATCH (m)-[:USES_COLUMN]->(mc:Column)
                // Indexed owner lookup by id (see osi_metric_search), with a fallback to the
                // ownership edge for column names containing a "." that break the id split.
                WITH mc, left(mc.id, size(mc.id) - size(last(split(mc.id, "."))) - 1) AS ownerId
                OPTIONAL MATCH (byId:Table|Query {id: ownerId})
                WITH mc, CASE
                    WHEN byId IS NOT NULL THEN byId
                    ELSE head([(o:Table|Query)-[:HAS_COLUMN|USES_COLUMN]->(mc) | o])
                END AS colOwner
                RETURN CASE WHEN colOwner IS NULL THEN mc.name ELSE colOwner.name + "." + mc.name END
            }
        }
    },
    joins: COLLECT {
        MATCH (j:Join)-[:HAS_SOURCE_TABLE]->(src)
        WHERE EXISTS { (d)-[:HAS_TABLE|HAS_QUERY]->(src) }
        OPTIONAL MATCH (j)-[:HAS_TARGET_TABLE]->(tgt)
        RETURN {
            join_name: j.name,
            from_table: src.name,
            to_table: tgt.name,
            from_columns: coalesce(j.from_columns, []),
            to_columns: coalesce(j.to_columns, []),
            aspects: COLLECT {
                MATCH (j)-[:HAS_ASPECT]->(a:Aspect)
                RETURN {
                    aspect_type: CASE
                        WHEN a:OsiAiContext THEN "ai_context"
                        WHEN a:OsiCustomExtensions THEN "custom_extensions"
                        ELSE "unknown"
                    END,
                    data: a.data,
                    vendor_name: a.vendor_name
                }
            }
        }
    },
    aspects: COLLECT {
        MATCH (d)-[:HAS_ASPECT]->(a:Aspect)
        RETURN {
            aspect_type: CASE
                WHEN a:OsiAiContext THEN "ai_context"
                WHEN a:OsiCustomExtensions THEN "custom_extensions"
                ELSE "unknown"
            END,
            data: a.data,
            vendor_name: a.vendor_name
        }
    }
} AS result
    """
