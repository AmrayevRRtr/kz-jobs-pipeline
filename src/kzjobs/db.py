"""Thin database helper around psycopg 3."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


@contextmanager
def connect(database_url: str) -> Iterator[psycopg.Connection]:
    """Open a connection; commit on success, roll back on any error."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        yield conn
