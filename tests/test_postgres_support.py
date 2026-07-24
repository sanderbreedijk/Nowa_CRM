from nowa_crm.core.database import PROPOSALS_230_SCHEMA
from nowa_crm.core.postgres_database import PostgresDatabase,split_script, translate_schema, translate_sql


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
    assert "if 15 not in current" in source
    assert "CREATE TABLE IF NOT EXISTS product_catalog" in source
