# Schema Data Model

Structural metadata describing how data is organised at the source. This is the
only layer that is partitioned by source database type, because the structure
itself differs fundamentally between models.

* [`rdbms/`](./rdbms/README.md) — relational structure: `Database`, `Schema`,
  `Table`, `Column`
* [`lpg/`](./lpg/README.md) — Labeled Property Graph structure: `Database`,
  `Schema`, `Node`, `Relationship`, `Property` **(in-progress)**

