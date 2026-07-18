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

MAIL_080_SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    subject_template TEXT NOT NULL DEFAULT '',
    body_template TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Algemeen',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mail_messages (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    direction TEXT NOT NULL DEFAULT 'uitgaand' CHECK(direction IN ('inkomend','uitgaand')),
    status TEXT NOT NULL DEFAULT 'concept',
    sender TEXT NOT NULL DEFAULT '',
    recipients TEXT NOT NULL DEFAULT '',
    cc TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mail_messages_customer ON mail_messages(customer_id, occurred_at DESC);
CREATE TABLE IF NOT EXISTS mail_attachments (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES mail_messages(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO mail_templates(name,subject_template,body_template,category) VALUES
('Algemene klantmail','Betreft: {klantnaam}','Beste {contactnaam},\n\n\n\nMet vriendelijke groet,\nNOWA Solutions','Algemeen'),
('Offerte verzenden','Offerte {offertenummer} – {offertetitel}','Beste {contactnaam},\n\nIn de bijlage ontvangt u onze offerte {offertenummer} voor {offertetitel}.\n\nHeeft u vragen, dan lichten wij de offerte graag toe.\n\nMet vriendelijke groet,\nNOWA Solutions','Offerte'),
('Voortgang project','Voortgang IT-project {klantnaam}','Beste {contactnaam},\n\nHierbij ontvangt u de actuele voortgang van het IT-project.\n\n{voortgang}\n\nMet vriendelijke groet,\nNOWA Solutions','Project');
"""

TELEPHONY_090_SCHEMA = """
CREATE TABLE IF NOT EXISTS call_events (
    id INTEGER PRIMARY KEY,
    external_id TEXT NOT NULL DEFAULT '',
    phone_number TEXT NOT NULL,
    normalized_number TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'inkomend' CHECK(direction IN ('inkomend','uitgaand')),
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'nieuw',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    subject TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    handled_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_call_events_phone ON call_events(normalized_number, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_call_events_customer ON call_events(customer_id, started_at DESC);
"""

ASSETS_120_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_locations (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customer_locations_customer ON customer_locations(customer_id,name);
CREATE TABLE IF NOT EXISTS customer_software (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    vendor TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    support_scope TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customer_software_customer ON customer_software(customer_id,name);
CREATE TABLE IF NOT EXISTS customer_documents (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL DEFAULT 'Algemeen',
    original_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customer_documents_customer ON customer_documents(customer_id,created_at DESC);
"""

SERVICEDESK_130_SCHEMA = """
CREATE TABLE IF NOT EXISTS service_tickets (
    id INTEGER PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    subject TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'Support',
    priority TEXT NOT NULL DEFAULT 'Normaal',
    status TEXT NOT NULL DEFAULT 'Open',
    owner TEXT NOT NULL DEFAULT 'NOWA',
    sla_due_at TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_service_tickets_customer ON service_tickets(customer_id,status,priority);
CREATE TABLE IF NOT EXISTS ticket_updates (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES service_tickets(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ticket_time_entries (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES service_tickets(id) ON DELETE CASCADE,
    minutes INTEGER NOT NULL CHECK(minutes>0),
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

REPORTING_140_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_reports (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL DEFAULT 'Voortgang',
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    progress_percent INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_project_reports_customer ON project_reports(customer_id,created_at DESC);
"""

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, SCHEMA), (2, AUTH_SCHEMA), (3, CRM_050_SCHEMA), (4, OPERATIONS_060_SCHEMA),
    (5, WORKSPACE_070_SCHEMA), (6, MAIL_080_SCHEMA), (7, TELEPHONY_090_SCHEMA),
    (8, ASSETS_120_SCHEMA), (9, SERVICEDESK_130_SCHEMA), (10, REPORTING_140_SCHEMA)
)
