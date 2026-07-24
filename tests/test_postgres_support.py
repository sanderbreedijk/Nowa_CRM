from nowa_crm.core.postgres_database import split_script, translate_schema, translate_sql


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
