from __future__ import annotations

import sqlite3
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from nowa_crm.core.phone import format_phone


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
            self._standardize_phone_numbers()
            return
        if self.path.exists() and self.path.stat().st_size:
            self.backup("voor_migratie")
        for version, script in pending:
            with self.transaction() as conn:
                conn.executescript(script)
                conn.execute("INSERT INTO schema_versions(version) VALUES(?)", (version,))
        self._standardize_phone_numbers()

    def _standardize_phone_numbers(self) -> None:
        with self.transaction() as conn:
            for table,column in (("customers","phone"),("customers","mobile_phone"),("contacts","phone"),("call_events","phone_number")):
                try:
                    rows=conn.execute(f"SELECT id,{column} FROM {table} WHERE {column}<>''").fetchall()
                except sqlite3.OperationalError:
                    continue
                for row in rows:
                    formatted=format_phone(row[column])
                    if formatted!=row[column]:
                        conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?",(formatted,row["id"]))

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

DOCUMENTS_180_SCHEMA = """
CREATE TABLE IF NOT EXISTS organization_profile (
    id INTEGER PRIMARY KEY CHECK(id=1),
    company_name TEXT NOT NULL DEFAULT 'NOWA Solutions',
    address TEXT NOT NULL DEFAULT '',
    postal_city TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    primary_color TEXT NOT NULL DEFAULT '#0B2342',
    footer_text TEXT NOT NULL DEFAULT 'NOWA Solutions',
    logo_path TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO organization_profile(id,company_name,primary_color,footer_text)
VALUES(1,'NOWA Solutions','#0B2342','NOWA Solutions');
"""

SERVICEDESK_190_SCHEMA = """
ALTER TABLE service_tickets ADD COLUMN source_type TEXT NOT NULL DEFAULT '';
ALTER TABLE service_tickets ADD COLUMN source_id INTEGER;
CREATE TABLE IF NOT EXISTS sla_policies (
    priority TEXT PRIMARY KEY,
    response_hours INTEGER NOT NULL,
    resolution_hours INTEGER NOT NULL
);
INSERT OR IGNORE INTO sla_policies(priority,response_hours,resolution_hours) VALUES
('Laag',8,72),('Normaal',4,24),('Hoog',2,8),('Kritiek',1,4);
CREATE TABLE IF NOT EXISTS maintenance_tasks (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    frequency TEXT NOT NULL DEFAULT 'Maandelijks',
    next_due_date TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT 'NOWA',
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_maintenance_due ON maintenance_tasks(active,next_due_date);
"""

INTEGRATIONS_200_SCHEMA = """
CREATE TABLE IF NOT EXISTS integration_events (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provider TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    successful INTEGER NOT NULL DEFAULT 1,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id INTEGER,
    actor TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_integration_events_provider ON integration_events(provider,occurred_at DESC);
INSERT OR IGNORE INTO integration_settings(provider,enabled,settings_json) VALUES
('outlook',0,'{"mode":"eml"}'),('coligo',0,'{"mode":"local_ingest"}');
"""

FOLLOWUP_220_SCHEMA = """
ALTER TABLE action_items ADD COLUMN action_type TEXT NOT NULL DEFAULT 'Taak';
ALTER TABLE action_items ADD COLUMN source_type TEXT NOT NULL DEFAULT '';
ALTER TABLE action_items ADD COLUMN source_id INTEGER;
ALTER TABLE action_items ADD COLUMN reminder_at TEXT NOT NULL DEFAULT '';
ALTER TABLE action_items ADD COLUMN completed_at TEXT;
CREATE INDEX IF NOT EXISTS idx_action_items_worklist ON action_items(status,due_date,owner,action_type);
"""

PROPOSALS_230_SCHEMA = """
ALTER TABLE proposals ADD COLUMN introduction TEXT NOT NULL DEFAULT '';
ALTER TABLE proposals ADD COLUMN terms TEXT NOT NULL DEFAULT '';
ALTER TABLE proposal_templates ADD COLUMN introduction TEXT NOT NULL DEFAULT '';
ALTER TABLE proposal_templates ADD COLUMN terms TEXT NOT NULL DEFAULT '';
ALTER TABLE proposal_lines ADD COLUMN catalog_item_id INTEGER REFERENCES product_catalog(id) ON DELETE SET NULL;
CREATE TABLE IF NOT EXISTS product_catalog (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Dienst',
    unit TEXT NOT NULL DEFAULT 'stuk',
    unit_price_cents INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_product_catalog_name ON product_catalog(active,category,name COLLATE NOCASE);
INSERT OR IGNORE INTO product_catalog(code,name,category,unit,unit_price_cents) VALUES
('UUR-IT','IT-werkzaamheden','Uren','uur',9400),
('UUR-PROJECT','Projectleiding','Uren','uur',10900),
('M365-BP','Microsoft 365 Business Premium','Licentie','gebruiker/maand',0),
('WP-INST','Installatie en oplevering werkplek','Dienst','stuk',18800),
('NET-SCAN','Netwerkinventarisatie en advies','Dienst','opdracht',37600);
"""

MAIL_DOSSIER_240_SCHEMA = """
ALTER TABLE mail_messages ADD COLUMN source_path TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_external_unique ON mail_messages(external_id) WHERE external_id<>'';
CREATE INDEX IF NOT EXISTS idx_mail_unlinked ON mail_messages(customer_id,direction,occurred_at DESC);
"""

CUSTOMER_IMPORT_250_SCHEMA = """
ALTER TABLE customers ADD COLUMN country TEXT NOT NULL DEFAULT '';
ALTER TABLE customers ADD COLUMN mobile_phone TEXT NOT NULL DEFAULT '';
ALTER TABLE customers ADD COLUMN active INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_customers_active_name ON customers(active,name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS customer_import_runs (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_rows INTEGER NOT NULL DEFAULT 0,
    created_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    archived_count INTEGER NOT NULL DEFAULT 0,
    performed_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CUSTOMER_IMPORT_260_SCHEMA = """
ALTER TABLE customer_import_runs ADD COLUMN unchanged_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE customer_import_runs ADD COLUMN backup_path TEXT NOT NULL DEFAULT '';
ALTER TABLE customer_import_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'uitgevoerd';
ALTER TABLE customer_import_runs ADD COLUMN reversed_at TEXT;
CREATE TABLE IF NOT EXISTS customer_import_changes (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES customer_import_runs(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    customer_number TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    action TEXT NOT NULL,
    changed_fields TEXT NOT NULL DEFAULT '',
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_customer_import_changes_run ON customer_import_changes(run_id,id);
"""

MAILBOX_270_SCHEMA = """
ALTER TABLE mail_messages ADD COLUMN triage_state TEXT NOT NULL DEFAULT 'open';
ALTER TABLE mail_messages ADD COLUMN priority TEXT NOT NULL DEFAULT 'Normaal';
ALTER TABLE mail_messages ADD COLUMN assigned_to TEXT NOT NULL DEFAULT '';
ALTER TABLE mail_messages ADD COLUMN follow_up_at TEXT NOT NULL DEFAULT '';
ALTER TABLE mail_messages ADD COLUMN handled_at TEXT;
CREATE INDEX IF NOT EXISTS idx_mail_triage ON mail_messages(triage_state,priority,occurred_at DESC);
CREATE TABLE IF NOT EXISTS mail_customer_aliases (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    email_address TEXT NOT NULL UNIQUE COLLATE NOCASE,
    source TEXT NOT NULL DEFAULT 'handmatig',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mail_alias_customer ON mail_customer_aliases(customer_id,email_address);
"""

TELEPHONY_280_SCHEMA = """
ALTER TABLE call_events ADD COLUMN priority TEXT NOT NULL DEFAULT 'Normaal';
ALTER TABLE call_events ADD COLUMN assigned_to TEXT NOT NULL DEFAULT '';
ALTER TABLE call_events ADD COLUMN callback_due TEXT NOT NULL DEFAULT '';
ALTER TABLE call_events ADD COLUMN callback_status TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_calls_callback ON call_events(callback_status,callback_due,started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_calls_external_unique ON call_events(external_id) WHERE external_id<>'';
CREATE TABLE IF NOT EXISTS call_customer_aliases (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    normalized_number TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'handmatig',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_call_alias_customer ON call_customer_aliases(customer_id,normalized_number);
"""

DAYSTART_290_SCHEMA = """
CREATE TABLE IF NOT EXISTS daystart_states (
    item_kind TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    assigned_to TEXT NOT NULL DEFAULT '',
    snoozed_until TEXT NOT NULL DEFAULT '',
    dismissed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(item_kind,entity_id)
);
CREATE INDEX IF NOT EXISTS idx_daystart_visible ON daystart_states(dismissed,snoozed_until,assigned_to);
"""

VAULT_VERIFICATION_300_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_verifications (
    id INTEGER PRIMARY KEY,
    vault_entry_id INTEGER NOT NULL REFERENCES vault_entries(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    call_id INTEGER NOT NULL REFERENCES call_events(id) ON DELETE CASCADE,
    requester_name TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    request_reason TEXT NOT NULL,
    identity_confirmed INTEGER NOT NULL DEFAULT 0,
    authority_confirmed INTEGER NOT NULL DEFAULT 0,
    successful INTEGER NOT NULL DEFAULT 0,
    used_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    verified_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_vault_verification_entry ON vault_verifications(vault_entry_id,successful,created_at DESC);
"""

PROPOSAL_TEMPLATE_310_SCHEMA = """
ALTER TABLE proposal_templates ADD COLUMN sections_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE proposal_templates ADD COLUMN calculation_json TEXT NOT NULL DEFAULT '{}';

INSERT OR IGNORE INTO proposal_templates(
    name,description,introduction,terms,sections_json,calculation_json
) VALUES(
    'NOWA Professional',
    'Modulair professioneel offertesjabloon uit de oorspronkelijke NOWA Workspace v6.3.0',
    'Hartelijk dank voor het prettige gesprek. Op basis van de besproken uitgangspunten hebben wij dit voorstel opgesteld.

NOWA Solutions adviseert een Microsoft 365-omgeving met duidelijke inrichting, beveiliging, documentatie, monitoring en nazorgafspraken.',
    'Werkzaamheden buiten de beschreven scope worden uitsluitend na akkoord uitgevoerd.
Software van derden valt buiten functionele ondersteuning, tenzij deze uitdrukkelijk is opgenomen.
Nazorg vindt plaats op nacalculatie, tenzij anders overeengekomen.

AVG: NOWA Solutions verwerkt persoonsgegevens uitsluitend voor zover noodzakelijk voor uitvoering, migratie, beheer, documentatie en ondersteuning.

Deze offerte is gebaseerd op de tijdens de intake beschikbare informatie. Wijzigingen in scope, aantallen of planning kunnen invloed hebben op kosten en doorlooptijd.',
    '[{"key":"cover","title":"Voorblad","enabled":true},{"key":"letter","title":"Begeleidend schrijven","enabled":true},{"key":"summary","title":"Managementsamenvatting","enabled":true},{"key":"current_situation","title":"Huidige situatie","enabled":true},{"key":"solution","title":"Voorgestelde oplossing","enabled":true},{"key":"planning","title":"Planning en oplevering","enabled":true},{"key":"activities","title":"Werkzaamheden","enabled":true},{"key":"licenses","title":"Licenties","enabled":true},{"key":"hardware","title":"Hardware","enabled":true},{"key":"pricing","title":"Investering","enabled":true},{"key":"scope","title":"Scope en uitsluitingen","enabled":true},{"key":"avg","title":"AVG-verklaring","enabled":true},{"key":"disclaimer","title":"Disclaimer","enabled":true},{"key":"approval","title":"Akkoord","enabled":true}]',
    '{"hourly_rate_eur":94.0,"fixed_hours":{"Projectvoorbereiding":3.0,"Kick-off / afstemming":1.0,"Technisch ontwerp":2.0,"Documentatie":4.0,"Oplevering":2.0,"Gebruikersinstructie":2.0},"percentages":{"Projectmanagement":0.10,"Risico-/wijzigingsbuffer":0.08},"minimum_total_hours":56.0,"rounding_step_hours":0.25,"enabled":true}'
);

INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Projectvoorbereiding',3,9400,10 FROM proposal_templates
WHERE name='NOWA Professional'
AND NOT EXISTS(SELECT 1 FROM proposal_template_lines l WHERE l.template_id=proposal_templates.id);
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Kick-off en afstemming',1,9400,20 FROM proposal_templates WHERE name='NOWA Professional';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Technisch ontwerp',2,9400,30 FROM proposal_templates WHERE name='NOWA Professional';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Uitvoering volgens intake en overeengekomen scope',42,9400,40 FROM proposal_templates WHERE name='NOWA Professional';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Documentatie',4,9400,50 FROM proposal_templates WHERE name='NOWA Professional';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Oplevering',2,9400,60 FROM proposal_templates WHERE name='NOWA Professional';
INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order)
SELECT id,'uren','Gebruikersinstructie',2,9400,70 FROM proposal_templates WHERE name='NOWA Professional';
"""

LEGACY_PROPOSAL_IMPORT_320_SCHEMA = """
CREATE TABLE IF NOT EXISTS legacy_proposal_imports (
    id INTEGER PRIMARY KEY,
    source_fingerprint TEXT NOT NULL UNIQUE,
    source_number TEXT NOT NULL,
    source_date TEXT NOT NULL DEFAULT '',
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES customer_documents(id) ON DELETE SET NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_legacy_proposal_import_customer ON legacy_proposal_imports(customer_id,imported_at DESC);
"""

PROPOSAL_EDITOR_330_SCHEMA = """
ALTER TABLE proposals ADD COLUMN sections_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE proposal_lines ADD COLUMN active INTEGER NOT NULL DEFAULT 1;
ALTER TABLE proposal_lines ADD COLUMN billing_period TEXT NOT NULL DEFAULT 'eenmalig';
ALTER TABLE proposal_lines ADD COLUMN group_name TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS proposal_revisions (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(proposal_id, revision_number)
);
CREATE INDEX IF NOT EXISTS idx_proposal_revisions ON proposal_revisions(proposal_id,revision_number DESC);
"""

CUSTOMER_QUALITY_313_SCHEMA = """
ALTER TABLE customers ADD COLUMN status TEXT NOT NULL DEFAULT 'actief';
ALTER TABLE customers ADD COLUMN tags TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS customer_change_log (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    changed_fields TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customer_change_log ON customer_change_log(customer_id,created_at DESC);
"""

PROPOSAL_OPTIONS_318_SCHEMA = """
ALTER TABLE proposal_lines ADD COLUMN optional INTEGER NOT NULL DEFAULT 0;
"""

PROPOSAL_APPROVAL_319_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposal_publications (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    token_hint TEXT NOT NULL,
    recipient_email TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'voorbereid',
    package_path TEXT NOT NULL DEFAULT '',
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    accepted_at TEXT,
    accepted_by TEXT NOT NULL DEFAULT '',
    accepted_function TEXT NOT NULL DEFAULT '',
    acceptance_comment TEXT NOT NULL DEFAULT '',
    license_changes_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_proposal_publications ON proposal_publications(proposal_id,created_at DESC);
"""

PROPOSAL_APPROVAL_320_SCHEMA = """
ALTER TABLE proposal_publications ADD COLUMN applied_at TEXT;
"""

PROPOSAL_APPROVAL_321_SCHEMA = """
ALTER TABLE proposal_publications ADD COLUMN applied_license_ids_json TEXT NOT NULL DEFAULT '[]';
"""

TELEPHONY_MULTI_LINK_326_SCHEMA = """
CREATE TABLE IF NOT EXISTS call_number_links (
    id INTEGER PRIMARY KEY,
    normalized_number TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    label TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(normalized_number,customer_id,contact_id)
);
CREATE INDEX IF NOT EXISTS idx_call_number_links_number ON call_number_links(normalized_number);
INSERT OR IGNORE INTO call_number_links(normalized_number,customer_id,contact_id,created_by)
SELECT normalized_number,customer_id,contact_id,created_by FROM call_customer_aliases;
"""

SHOMI_ANALYSIS_332_SCHEMA = """
CREATE TABLE IF NOT EXISTS call_analyses (
    id INTEGER PRIMARY KEY,
    call_id INTEGER NOT NULL REFERENCES call_events(id) ON DELETE CASCADE,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'shomi',
    source_event_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    transcript TEXT NOT NULL DEFAULT '',
    action_points_json TEXT NOT NULL DEFAULT '[]',
    raw_payload_json TEXT NOT NULL DEFAULT '{}',
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider,source_event_id)
);
CREATE INDEX IF NOT EXISTS idx_call_analyses_call ON call_analyses(call_id,received_at DESC);
"""

GOOGLE_CALENDAR_332_SCHEMA = """
CREATE TABLE IF NOT EXISTS calendar_event_links (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'google_calendar',
    action_id INTEGER NOT NULL REFERENCES action_items(id) ON DELETE CASCADE,
    external_event_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL DEFAULT 'primary',
    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider,action_id)
);
CREATE INDEX IF NOT EXISTS idx_calendar_event_links_external ON calendar_event_links(provider,external_event_id);
"""

SHOMI_PLANNING_333_SCHEMA = """
ALTER TABLE action_items ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 60;
ALTER TABLE call_analyses ADD COLUMN review_status TEXT NOT NULL DEFAULT 'Te beoordelen';
ALTER TABLE call_analyses ADD COLUMN reviewed_at TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_call_analyses_review ON call_analyses(provider,review_status,received_at);
"""

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, SCHEMA), (2, AUTH_SCHEMA), (3, CRM_050_SCHEMA), (4, OPERATIONS_060_SCHEMA),
    (5, WORKSPACE_070_SCHEMA), (6, MAIL_080_SCHEMA), (7, TELEPHONY_090_SCHEMA),
    (8, ASSETS_120_SCHEMA), (9, SERVICEDESK_130_SCHEMA), (10, REPORTING_140_SCHEMA),
    (11, DOCUMENTS_180_SCHEMA), (12, SERVICEDESK_190_SCHEMA), (13, INTEGRATIONS_200_SCHEMA),
    (14, FOLLOWUP_220_SCHEMA), (15, PROPOSALS_230_SCHEMA), (16, MAIL_DOSSIER_240_SCHEMA),
    (17, CUSTOMER_IMPORT_250_SCHEMA), (18, CUSTOMER_IMPORT_260_SCHEMA), (19, MAILBOX_270_SCHEMA),
    (20, TELEPHONY_280_SCHEMA), (21, DAYSTART_290_SCHEMA), (22, VAULT_VERIFICATION_300_SCHEMA),
    (23, PROPOSAL_TEMPLATE_310_SCHEMA), (24, LEGACY_PROPOSAL_IMPORT_320_SCHEMA),
    (25, PROPOSAL_EDITOR_330_SCHEMA), (26, CUSTOMER_QUALITY_313_SCHEMA),
    (27, PROPOSAL_OPTIONS_318_SCHEMA), (28, PROPOSAL_APPROVAL_319_SCHEMA),
    (29, PROPOSAL_APPROVAL_320_SCHEMA), (30, PROPOSAL_APPROVAL_321_SCHEMA),
    (31, TELEPHONY_MULTI_LINK_326_SCHEMA), (32, SHOMI_ANALYSIS_332_SCHEMA),
    (33, GOOGLE_CALENDAR_332_SCHEMA), (34, SHOMI_PLANNING_333_SCHEMA)
)
