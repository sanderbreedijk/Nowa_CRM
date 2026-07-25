from nowa_crm.core.database import PROPOSALS_230_SCHEMA
from nowa_crm.core.database import Database
from nowa_crm.core.postgres_database import PostgresDatabase,split_script, translate_schema, translate_sql
from nowa_crm.modules.multiuser.service import MultiUserService


def test_sqlite_queries_are_translated_for_postgres():
    assert "COLLATE NOCASE" not in translate_sql("SELECT * FROM customers ORDER BY name COLLATE NOCASE")
    assert "ON CONFLICT DO NOTHING" in translate_sql("INSERT OR IGNORE INTO x(name) VALUES(?)")
    assert "%s" in translate_sql("SELECT * FROM x WHERE id=?")
    assert "ILIKE" in translate_sql("SELECT * FROM x WHERE name LIKE ?")
    assert "CURRENT_DATE" in translate_sql("UPDATE x SET due=date('now')")
    assert "INTERVAL '-30 days'" in translate_sql("SELECT datetime('now','-30 days')")


def test_schema_types_are_postgres_compatible():
    translated=translate_schema("CREATE TABLE x(id INTEGER PRIMARY KEY,payload BLOB,amount REAL);")
    assert "BIGSERIAL PRIMARY KEY" in translated
    assert "BYTEA" in translated
    assert "DOUBLE PRECISION" in translated
    assert "ADD COLUMN IF NOT EXISTS introduction" in translate_schema(
        "ALTER TABLE proposals ADD COLUMN introduction TEXT NOT NULL DEFAULT '';")


def test_migration_script_splitter_keeps_statements():
    result=split_script("CREATE TABLE x(id INTEGER);\nINSERT INTO x VALUES(1);")
    assert len(result)==2


def test_catalog_is_created_before_foreign_key_is_added():
    statements=split_script(PROPOSALS_230_SCHEMA)
    create_index=next(i for i,value in enumerate(statements) if "CREATE TABLE IF NOT EXISTS product_catalog" in value)
    foreign_key_index=next(i for i,value in enumerate(statements) if "ADD COLUMN catalog_item_id" in value)
    assert create_index < foreign_key_index


def test_postgres_migration_contains_catalog_recovery():
    import inspect
    source=inspect.getsource(PostgresDatabase.migrate)
    assert "CREATE TABLE IF NOT EXISTS product_catalog" in source
    assert "if base_ready and 15 in current" in source


def test_manual_import_rejects_unrelated_sqlite(tmp_path):
    import sqlite3
    source=tmp_path/"verkeerd.sqlite3"
    with sqlite3.connect(source) as conn:conn.execute("CREATE TABLE anders(id INTEGER)")
    service=MultiUserService(Database(tmp_path/"local.sqlite3"),tmp_path)
    try:service.import_sqlite_to_postgres(source)
    except ValueError as exc:assert "geen volledige NOWA CRM-database" in str(exc)
    else:raise AssertionError("Ongeldige database werd geaccepteerd")


def test_postgres_bulk_import_uses_cursor():
    import inspect
    from nowa_crm.modules.multiuser.postgres_migration import PostgresMigrator
    source=inspect.getsource(PostgresMigrator.run)
    assert ".raw.executemany" not in source
    assert ".raw.cursor().executemany" in source
