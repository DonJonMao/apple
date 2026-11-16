"""Nested SQLite changes that preserve the caller's commit/rollback boundary."""
from contextlib import contextmanager
from uuid import uuid4


@contextmanager
def atomic(connection):
    name = "knowledge_" + uuid4().hex
    connection.execute("SAVEPOINT " + name)
    try:
        yield connection
        connection.execute("RELEASE " + name)
    except BaseException:
        connection.execute("ROLLBACK TO " + name)
        connection.execute("RELEASE " + name)
        raise
