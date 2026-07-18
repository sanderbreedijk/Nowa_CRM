from __future__ import annotations

import sqlite3
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            current = {int(row[0]) for row in conn.execute("SELECT version FROM schema_versions")}
        pending = [(version, script) for version, script in MIGRATIONS if version not in current]
        if not pending:
            return
        if self.path.exists() and self.path.stat().st_size:
            self.backup("voor_migratie")
        for version, script in pending:
            with self.transaction() as conn:
                conn.executescript(script)
                conn.execute("INSERT INTO schema_versions(version) VALUES(?)", (version,))

    def backup(self, label: str = "handmatig") -> Path:
        folder = self.path.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"nowa-{label}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
        source = self.connect()
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return target


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    customer_number TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    street TEXT NOT NULL DEFAULT '',
    postal_code TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'concept',
    revision INTEGER NOT NULL DEFAULT 1,
    total_cents INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS proposal_lines (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'service',
    description TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_price_cents INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS vault_entries (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT 'Account',
    label TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    secret BLOB NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_vault_lookup ON vault_entries(customer_id, label COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    customer_id INTEGER,
    reason TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS integration_settings (
    provider TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash BLOB NOT NULL,
    password_salt BLOB NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('administrator','sales','service','viewer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS login_events (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    username TEXT NOT NULL,
    successful INTEGER NOT NULL,
    workstation TEXT NOT NULL DEFAULT ''
);
"""

CRM_050_SCHEMA = """
ALTER TABLE vault_entries ADD COLUMN group_path TEXT NOT NULL DEFAULT '';
ALTER TABLE vault_entries ADD COLUMN host TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_contacts_customer ON contacts(customer_id, name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS proposal_templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS proposal_template_lines (
    id INTEGER PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES proposal_templates(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'dienst',
    description TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_price_cents INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO proposal_templates(name, description) VALUES
 ('Microsoft 365 migratie', 'Basisopzet voor een Microsoft 365 migratie'),
 ('Nieuwe werkplek', 'Werkplek, installatie en oplevering'),
 ('Netwerkproject', 'Netwerkonderzoek, inrichting en documentatie');
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Inventarisatie en technisch ontwerp',4,9400,10 FROM proposal_templates WHERE name='Microsoft 365 migratie'
AND NOT EXISTS(SELECT 1 FROM proposal_template_lines);
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Migratie en inrichting per gebruiker',1,9400,20 FROM proposal_templates WHERE name='Microsoft 365 migratie';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'hardware','Zakelijke werkplek',1,0,10 FROM proposal_templates WHERE name='Nieuwe werkplek';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Installatie, configuratie en overdracht',2,9400,20 FROM proposal_templates WHERE name='Nieuwe werkplek';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Netwerkinventarisatie en ontwerp',4,9400,10 FROM proposal_templates WHERE name='Netwerkproject';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Inrichting, testen en documentatie',8,9400,20 FROM proposal_templates WHERE name='Netwerkproject';
"""

OPERATIONS_060_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_users (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    user_principal_name TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    license_name TEXT NOT NULL DEFAULT '',
    mfa_enabled INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customer_users_customer ON customer_users(customer_id, display_name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS customer_licenses (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    supplier TEXT NOT NULL DEFAULT 'Microsoft',
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price_cents INTEGER NOT NULL DEFAULT 0,
    included_in_proposal INTEGER NOT NULL DEFAULT 1,
    renewal_date TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS customer_hardware (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    serial_number TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1,
    purchase_price_cents INTEGER NOT NULL DEFAULT 0,
    sales_price_cents INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'In gebruik',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS project_intakes (
    customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
    users_count INTEGER NOT NULL DEFAULT 0,
    devices_count INTEGER NOT NULL DEFAULT 0,
    shared_mailboxes INTEGER NOT NULL DEFAULT 0,
    teams_count INTEGER NOT NULL DEFAULT 0,
    sharepoint_sites INTEGER NOT NULL DEFAULT 0,
    migration_source TEXT NOT NULL DEFAULT '',
    desired_date TEXT NOT NULL DEFAULT '',
    scope_notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS project_tasks (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    phase TEXT NOT NULL DEFAULT 'Voorbereiding',
    task_name TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT 'NOWA',
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    dependency TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Gepland',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_project_tasks_customer ON project_tasks(customer_id, status, start_date);
"""

WORKSPACE_070_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_notes (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT 'NOWA',
    due_date TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'Normaal',
    status TEXT NOT NULL DEFAULT 'Open',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_action_items_status ON action_items(status, due_date, priority);
CREATE TABLE IF NOT EXISTS customer_commercial_settings (
    customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
    hourly_rate_cents INTEGER NOT NULL DEFAULT 9400,
    discount_percent REAL NOT NULL DEFAULT 0,
    payment_term_days INTEGER NOT NULL DEFAULT 14,
    validity_days INTEGER NOT NULL DEFAULT 30,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, SCHEMA), (2, AUTH_SCHEMA), (3, CRM_050_SCHEMA), (4, OPERATIONS_060_SCHEMA),
    (5, WORKSPACE_070_SCHEMA)
)
