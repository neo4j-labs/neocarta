"""Fixtures for the JDBC schema connector integration test.

Spins up a Dockerized PostgreSQL instance and seeds a small schema. The
``testcontainers.postgres`` import is deferred into the fixture body so test
collection does not require the optional ``testcontainers[postgres]`` extra
when the suite is skipped (e.g. in CI without Java/JARs).
"""

import pytest

_SEED_DDL = (
    "CREATE TABLE customers (id integer PRIMARY KEY, email varchar); "
    "CREATE TABLE orders ("
    "id integer PRIMARY KEY, "
    "customer_id integer REFERENCES customers(id));"
)


@pytest.fixture
def postgres_jdbc():
    """Start a seeded PostgreSQL container and yield JDBC connection details."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as postgres:
        seed_cmd = (
            f"PGPASSWORD={postgres.password} "
            f'psql -U {postgres.username} -d {postgres.dbname} -c "{_SEED_DDL}"'
        )
        exit_code, output = postgres.get_wrapped_container().exec_run(["sh", "-c", seed_cmd])
        assert exit_code == 0, output

        host = postgres.get_container_host_ip()
        port = postgres.get_exposed_port(5432)
        yield {
            "url": f"jdbc:postgresql://{host}:{port}/{postgres.dbname}",
            "user": postgres.username,
            "password": postgres.password,
            "database": postgres.dbname,
        }
