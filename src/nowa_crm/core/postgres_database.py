from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from nowa_crm.core.database import MIGRATIONS


def translate_sql(sql: str) -> str:
    result = sql
    result = re.sub(r"\s+COLLATE\s+NOCASE", "", result, flags=re.I)
    result = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", result, flags=re.I)
    if re.search(r"\bINSERT\s+OR\s+IGNORE\b", sql, re.I) and "ON CONFLICT" not in result.upper():
        result = result.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    result = re.sub(r"datetime\('now','localtime','([+-]\d+)\s+hours?'\)",
                    lambda m: f"(CURRENT_TIMESTAMP + INTERVAL '{m.group(1)} hours')", result, flags=re.I)
    result = re.sub(r"datetime\('now','([+-]\d+)\s+(minutes?|hours?|days?)'\)",
                    lambda m: f"(CURRENT_TIMESTAMP + INTERVAL '{m.group(1)} {m.group(2)}')", result, flags=re.I)
    result = re.sub(r"datetime\('now',\?\)", "(CURRENT_TIMESTAMP + CAST(? AS interval))", result, flags=re.I)
    result = re.sub(r"datetime\('now'(?:,'localtime')?\)", "CURRENT_TIMESTAMP", result, flags=re.I)
    result = re.sub(r"datetime\(([^(),]+)\)", r"CAST(\1 AS timestamp)", result, flags=re.I)
    result = re.sub(r"date\('now'\)", "CURRENT_DATE", result, flags=re.I)
    result = re.sub(r"date\(([^(),]+),'([+-]\d+)\s+days?'\)",
                    r"(CAST(\1 AS timestamp) + INTERVAL '\2 days')::date", result, flags=re.I)
    result = re.sub(r"date\(([^(),]+)\)", r"CAST(\1 AS date)", result, flags=re.I)
    result = re.sub(r"julianday\(([^()]+)\)", r"(EXTRACT(EPOCH FROM CAST(\1 AS timestamp))/86400.0)", result, flags=re.I)
    result = re.sub(r"\bMAX\(0,\s*CAST\(", "GREATEST(0,CAST(", result, flags=re.I)
    result = re.sub(r"\bLIKE\b", "ILIKE", result, flags=re.I)
    result = result.replace("?", "%s")
    return result


def translate_schema(script: str) -> str:
    result = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\b", "BIGSERIAL PRIMARY KEY", script, flags=re.I)
    result = re.sub(r"\bAUTOINCREMENT\b", "", result, flags=re.I)
    result = re.sub(r"\bBLOB\b", "BYTEA", result, flags=re.I)
    result = re.sub(r"\bREAL\b", "DOUBLE PRECISION", result, flags=re.I)
    return translate_sql(result)


def split_script(script: str) -> list[str]:
    statements, buffer = [], ""
    for line in script.splitlines(True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


class PostgresRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class PostgresCursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor, self.lastrowid = cursor, lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row=self.cursor.fetchone()
        return PostgresRow(row) if row is not None else None

    def fetchall(self):
        return [PostgresRow(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (PostgresRow(row) for row in self.cursor)


class PostgresConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, parameters=()):
        translated = translate_sql(sql)
        match = re.match(r"\s*INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+([A-Za-z_][\w]*)", sql, re.I)
        returning = bool(match and "RETURNING" not in translated.upper() and self._has_serial_id(match.group(1)))
        if returning:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        cursor = self.raw.cursor()
        cursor.execute(translated, tuple(parameters))
        lastrowid = None
        if returning:
            row = cursor.fetchone()
            lastrowid = row["id"] if isinstance(row, dict) else row[0]
        return PostgresCursor(cursor, lastrowid)

    def executemany(self, sql: str, parameters):
        cursor = self.raw.cursor()
        cursor.executemany(translate_sql(sql), parameters)
        return PostgresCursor(cursor)

    def executescript(self, script: str):
        cursor = self.raw.cursor()
        for statement in split_script(script):
            cursor.execute(translate_schema(statement))
        return PostgresCursor(cursor)

    def _has_serial_id(self, table: str) -> bool:
        cursor = self.raw.cursor()
        cursor.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name='id' AND column_default LIKE 'nextval%%'", (table,))
        return cursor.fetchone() is not None


class PostgresDatabase:
    is_postgres = True
    is_remote = True

    def __init__(self, host: str, port: int, database: str, user: str, password: str, sslmode: str = "prefer"):
        self.host, self.port, self.database, self.user = host, int(port), database, user
        self.password, self.sslmode = password, sslmode
        self.path = Path(f"postgresql-{host}-{database}")

    def connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL-ondersteuning ontbreekt in deze installatie.") from exc
        try:
            return psycopg.connect(host=self.host, port=self.port, dbname=self.database, user=self.user,
                                   password=self.password, sslmode=self.sslmode, row_factory=dict_row,
                                   connect_timeout=5)
        except psycopg.Error as exc:
            raise ConnectionError(f"Synology PostgreSQL niet bereikbaar: {exc}") from exc

    @contextmanager
    def transaction(self):
        raw = self.connect()
        try:
            with raw.transaction():
                yield PostgresConnection(raw)
        finally:
            raw.close()

    def migrate(self):
        with self.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("""CREATE TABLE IF NOT EXISTS nowa_system_secrets (
                name TEXT PRIMARY KEY, value BYTEA NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            current = {int(row["version"]) for row in conn.execute("SELECT version FROM schema_versions")}
        # Herstel een database waarop v3.37.0 tijdens migratie 15 is gestopt.
        # PostgreSQL vereist dat de doeltabel al bestaat voordat een FK wordt toegevoegd.
        if 15 not in current:
            with self.transaction() as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS product_catalog (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'Dienst',
                    unit TEXT NOT NULL DEFAULT 'stuk',
                    unit_price_cents INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
        for version, script in MIGRATIONS:
            if version in current:
                continue
            with self.transaction() as conn:
                conn.executescript(script)
                conn.execute("INSERT INTO schema_versions(version) VALUES(?)", (version,))
        with self.transaction() as conn:
            missing=[name for name in ("customers","proposals","proposal_lines","product_catalog","vault_entries")
                     if not conn.execute("""SELECT 1 FROM information_schema.tables
                         WHERE table_schema='public' AND table_name=?""",(name,)).fetchone()]
        if missing:raise RuntimeError("PostgreSQL-schema onvolledig; ontbrekend: "+", ".join(missing))

    def health(self) -> dict:
        with self.transaction() as conn:
            row = conn.execute("SELECT current_database() database,version() version").fetchone()
        return dict(row)

    def vault_key(self) -> bytes:
        with self.transaction() as conn:
            row=conn.execute("SELECT value FROM nowa_system_secrets WHERE name='vault_key'").fetchone()
        if not row:raise ConnectionError("De gedeelde kluissleutel ontbreekt in PostgreSQL.")
        return bytes(row["value"])

    def backup(self, label: str = "handmatig"):
        raise RuntimeError("Maak een herstelset via Multi-user; PostgreSQL wordt logisch geëxporteerd.")
