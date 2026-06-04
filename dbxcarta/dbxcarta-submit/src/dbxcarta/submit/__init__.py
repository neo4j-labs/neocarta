"""Operator CLI for submitting and uploading dbxcarta Databricks jobs.

This package owns everything that talks to ``databricks-job-runner``: the
named-entrypoint table, the runner wiring, and the submit and upload
commands. The core ``dbxcarta-spark`` package depends on neither this
package nor the job runner.
"""
