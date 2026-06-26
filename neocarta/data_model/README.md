# Graph Data Model

This package defines the Pydantic models for the Neocarta metadata graph. It is
organised into **layers of concern** rather than one model per source. Only the
structural layer is partitioned by source database type.

**The data model components defined here are subject to change throughout development.**

## Layout

| Module | Concern |
|---|---|
| [`metadata/`](./metadata/README.md) | Graph-level bookkeeping (the `NeocartaGraph` singleton) |
| [`schema/`](./schema/README.md) | Structural metadata — partitioned into [`rdbms/`](./schema/rdbms/README.md) and [`lpg/`](./schema/lpg/README.md) |
| [`glossary/`](./glossary/README.md) | Business terminology (glossaries, categories, business terms, tagging) |
| [`governance/`](./governance/README.md) | Vendor-neutral governance tags (tag keys, allowed values, assignments) |
| [`instance/`](./instance/README.md) | Instance-level data values (`Value` nodes) |
| [`query/`](./query/README.md) | Cached SQL queries, CTEs, and parsed table/column usage |
| [`osi/`](./osi/README.md) | Open Semantic Interchange (OSI) semantic-model components |

Each module exposes its models from a `models.py` and re-exports them from the
package `__init__`, so both of the following work:

```python
from neocarta.data_model.schema.rdbms import Table, Column
from neocarta.data_model.osi.models import OsiTable
```

## Conventions

- Shared field validators (NaN/`None` coercion, uppercasing) live in
  [`_validators.py`](./_validators.py) and are wired into models with
  `field_validator(...)(coerce_str_or_none)`.
- Relationships that may originate from several node labels use a
  `source_label` discriminator plus a `source_id` (e.g. `TaggedWith`,
  `HasAspect`, `HasExpression`).
- Node ids are generated via `connectors/utils/generate_id.py`; the models here
  only carry the resulting id strings.

## Dependencies

The modules form a clean dependency DAG. Only `osi/` imports another module —
its `OsiTable` / `OsiColumn` subclass the RDBMS structural `Table` / `Column`.
Every other cross-module reference is by id string, not by import.
