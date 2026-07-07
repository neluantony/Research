"""Database connection helper.

Connection is taken from ``DATABASE_URL`` (e.g.
``postgresql://user:pass@localhost:5432/urban_imageability``) if set, otherwise
assembled from standard ``PG*`` environment variables with sensible defaults.
"""
from __future__ import annotations

import os

import psycopg


DEFAULT_DBNAME = "urban_imageability"


def connection_string() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "postgres")
    dbname = os.environ.get("PGDATABASE", DEFAULT_DBNAME)
    password = os.environ.get("PGPASSWORD", "")
    conninfo = f"host={host} port={port} user={user} dbname={dbname}"
    if password:
        conninfo += f" password={password}"
    return conninfo


def connect() -> psycopg.Connection:
    """Open a connection. Caller is responsible for commit/close (use `with`)."""
    return psycopg.connect(connection_string())
