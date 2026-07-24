from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class PostgresMigrator:
    def __init__(self, source, target, root: Path):
        self.source, self.target, self.root = source, target, root

    def run(self) -> dict:
        if getattr(self.source, "is_remote", False):
            raise ValueError("Migreren kan alleen vanuit de lokale SQLite-database.")
        backup = self.source.backup("voor-postgresql-migratie")
        self.target.migrate()
        vault_key=self.root/"vault.key"
        if not vault_key.is_file():
            raise RuntimeError("De lokale kluissleutel ontbreekt; migratie is niet veilig mogelijk.")
        with self.target.transaction() as target:
            target.execute("""INSERT INTO nowa_system_secrets(name,value) VALUES('vault_key',?)
                ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                (vault_key.read_bytes(),))
        source_counts = self._counts_sqlite()
        tables = [name for name in source_counts if name != "schema_versions"]
        with self.target.transaction() as target:
            target.raw.execute("SET session_replication_role = replica")
            try:
                for table in reversed(tables):
                    target.raw.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
                with self.source.transaction() as source:
                    for table in tables:
                        rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
                        if not rows:
                            continue
                        columns = list(rows[0].keys())
                        marks = ",".join(["%s"] * len(columns))
                        names = ",".join(f'"{name}"' for name in columns)
                        target.raw.executemany(
                            f'INSERT INTO "{table}" ({names}) VALUES ({marks})',
                            [tuple(row[name] for name in columns) for row in rows])
            finally:
                target.raw.execute("SET session_replication_role = DEFAULT")
            serial_tables = {row["table_name"] for row in target.raw.execute(
                """SELECT table_name FROM information_schema.columns
                   WHERE table_schema='public' AND column_name='id' AND column_default LIKE 'nextval%'""")}
            for table in tables:
                if table in serial_tables:
                    target.raw.execute(
                        f"""SELECT setval(pg_get_serial_sequence(%s,'id'),
                            COALESCE((SELECT MAX(id) FROM "{table}"),1),
                            COALESCE((SELECT MAX(id) FROM "{table}"),0)>0)""", (table,))
        target_counts = self._counts_postgres(tables)
        differences = {table: (source_counts[table], target_counts.get(table, -1))
                       for table in tables if source_counts[table] != target_counts.get(table)}
        if differences:
            raise RuntimeError(f"Controle na migratie mislukt: {differences}. Lokale database blijft actief.")
        manifest = backup.with_suffix(".postgres-migratie.json")
        manifest.write_text(json.dumps({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "backup": str(backup), "tables": source_counts, "verified": True,
            "contains_customer_data": True,
            "warning": "Niet uploaden naar GitHub of andere openbare opslag."
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"backup": backup, "manifest": manifest, "tables": len(tables),
                "rows": sum(source_counts[name] for name in tables), "verified": True}

    def _counts_sqlite(self):
        with self.source.transaction() as conn:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in tables}

    def _counts_postgres(self, tables):
        with self.target.transaction() as conn:
            return {name: int(conn.raw.execute(f'SELECT COUNT(*) count FROM "{name}"').fetchone()["count"])
                    for name in tables}
