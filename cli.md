# Splitting the Databricks Connector from the Operator Tooling

## Overview

Today the `dbxcarta` branch carries a full copy of the Databricks project inside Neocarta: the pipeline code, the operator CLI, wheel building, publishing, and job submission. Most of that does not belong in Neocarta.

The plan is to draw a clean line between the connector and the operator tooling.

Neocarta keeps only the Databricks connector. That means the pipeline-facing core and the Spark ingest pipeline, the code that reads source tables and writes the semantic layer into Neo4j. Neocarta builds this as a versioned wheel and publishes it to a package index, the same way any Python package is released. This is based on the `add-databricks-connector-from-dbxcarta` branch.

The external `dbxcarta` project becomes operator tooling only. It drops the core connector and the Spark pipeline, since those now live in Neocarta. It keeps a thin operator core for reading environment files, parsing Volume paths, building the workspace client, and administering Unity Catalog. It pulls the connector wheel that Neocarta published, by version, and does three jobs: publish the wheel to the Unity Catalog Volume, set up the catalogs and volumes, and run the job.

The two projects stay decoupled. Neocarta does not depend on `dbxcarta`. The `dbxcarta` tooling depends on the Neocarta connector only as a published artifact it pulls and stages, not as code it imports. The connector wheel is the single handoff between them.

The pipeline-facing core is just part of the connector. It is the small set of support modules the ingest job needs at runtime: settings and environment loading, identifier and Volume-path validation, the workspace client, Volume reads and writes, and the built-in presets. These live as ordinary modules inside the connector, packaged and resolved like any other dependency. There is no separate core package and no build-time bundling step.

The cost of the split is a little duplication. A few of those support modules are needed by both the pipeline and the operator tooling: environment loading, config derivation, identifier and Volume-path parsing, and the workspace client. Because the two projects stay decoupled with no shared import, `dbxcarta` keeps its own thin copies of the operator-facing helpers and the Neocarta connector keeps its own copies for the pipeline. That duplication is the price of full decoupling. The alternative, a shared core package both projects depend on, was set aside.

## How the Spark job gets run

The job runs on Databricks without the pipeline source being present in `dbxcarta`. The connector wheel, published by Neocarta and staged on the Volume, carries everything the cluster needs. Two ways to launch it, and a team can ship both.

### Option 1: Command line

An operator runs the `dbxcarta` submit tooling from a terminal. It reads the target catalog, the Volume path, and the Neo4j connection details from configuration, then submits a Databricks job that installs the staged connector wheel and runs the ingest entry point. It waits for the run and reports the result. Good for automation, scheduling, and repeatable runs from outside the workspace.

### Option 2: Notebook

A Databricks notebook does the launch from inside the workspace. The operator opens the notebook, fills in a few values at the top, and runs it. The notebook installs the published connector wheel and its pinned dependencies, attaches the Neo4j Spark Connector, then calls the ingest entry point directly. The notebook is the compute, so there is no separate submit step and no local setup beyond workspace access. Good for demos, exploration, and users who already live in Databricks.

A notebook can download the libraries and run the pipeline. A cell can install the connector wheel from the package index or from the Volume, the same wheel the command-line option submits. The Neo4j Spark Connector is a JVM library, so it attaches to the cluster rather than installing through pip; this is a one-time cluster setting or a notebook-scoped library step. After the libraries are present, the notebook imports the ingest code and runs it against the cluster's Spark session. Ingest needs a classic cluster rather than serverless, because the Neo4j Spark Connector is not supported on serverless compute.

## What needs to be done

### In Neocarta

* Bring in the pipeline-facing core and the Spark ingest pipeline from the `add-databricks-connector-from-dbxcarta` branch, and nothing else from `dbxcarta`.
* Keep the pipeline-facing core as ordinary modules inside the connector, packaged into the single connector wheel, with no separate core package or build-time bundling step.
* Add a versioning and build step that produces a versioned connector wheel.
* Publish the versioned wheel to a package index, public or private, as the release artifact of record.
* Keep the connector's runtime dependencies pinned to the versions the pipeline was tested against.
* Document the Neo4j Spark Connector requirement, since it is a JVM library the connector expects on the cluster rather than a pip dependency.

### In the external dbxcarta project

* Remove the pipeline core and the Spark ingest pipeline, now owned by Neocarta.
* Keep the thin operator core: environment loading, Volume-path parsing, workspace client, and Unity Catalog administration.
* Change the publish step so it pulls the Neocarta connector wheel by version from the package index and uploads it to the Unity Catalog Volume, instead of building the wheel from local source.
* Keep the setup step that creates the data catalog and the operations catalog, schema, and volume.
* Keep the run step that submits the ingest job pointing at the staged connector wheel, on classic compute with the Neo4j Spark Connector preflight.
* Update operator configuration and docs to reference a connector wheel version rather than a local build.

### Shared

* Agree on the connector wheel name and version scheme, since it is the one contract between the two projects.
* Decide which package index is used for publishing and pulling.
