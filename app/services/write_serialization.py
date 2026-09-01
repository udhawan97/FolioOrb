"""Serialize read-modify-write financial mutations in FolioOrb's SQLite store.

SQLite's default deferred transactions let two request sessions read the same
old row before either becomes the writer.  Both can then derive financial
changes from that stale snapshot.  ``BEGIN IMMEDIATE`` chooses the single
writer before the first read, so a competing request waits and then evaluates
the state committed by the winner.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def begin_financial_write(db: Session) -> None:
    """Acquire SQLite's write reservation before reading financial state.

    A session may already have performed a legacy-mode SQLite ``SELECT``.  In
    that case SQLAlchemy has an internal transaction object while the DB-API
    connection has not actually begun a database transaction, so issuing
    ``BEGIN IMMEDIATE`` is both valid and necessary.  If the driver is already
    in a transaction, an earlier write owns the reservation and no upgrade is
    needed.

    FolioOrb's persisted application database is SQLite.  Other dialects keep
    their existing transaction behavior rather than receiving SQLite syntax.
    """
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = connection.connection.driver_connection
    if driver_connection.in_transaction:
        return
    connection.exec_driver_sql("BEGIN IMMEDIATE")
