"""
SQLite (used for local dev/demo - see app/config.py) silently drops
tzinfo on read even for columns declared DateTime(timezone=True), so a
timestamp read back from the DB is naive while datetime.now(timezone.utc)
is aware, and comparing the two raises TypeError. Simplest fix that works
identically on SQLite and Postgres: never create an aware datetime in the
first place. Everything in this service is UTC implicitly; this is the
one function that should ever call datetime.now().
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
