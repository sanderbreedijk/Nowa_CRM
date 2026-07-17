from __future__ import annotations

from dataclasses import dataclass

from nowa_crm.core.database import Database
from nowa_crm.core.events import Event, EventBus


@dataclass(frozen=True)
class Customer:
    id: int
    customer_number: str
    name: str
    email: str
    phone: str
    street: str
    postal_code: str
    city: str
    notes: str


@dataclass(frozen=True)
class Contact:
    id: int
    customer_id: int
    name: str
    role: str
    email: str
    phone: str


class CustomerService:
    def __init__(self, db: Database, events: EventBus):
        self.db, self.events = db, events

    def create(self, customer_number: str, name: str, email: str = "", phone: str = "", street: str = "", postal_code: str = "", city: str = "", notes: str = "") -> int:
        if not customer_number.strip() or not name.strip():
            raise ValueError("Klantnummer en naam zijn verplicht")
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO customers(customer_number,name,email,phone,street,postal_code,city,notes) VALUES(?,?,?,?,?,?,?,?)",
                tuple(value.strip() for value in (customer_number, name, email, phone, street, postal_code, city, notes)),
            )
            customer_id = int(cur.lastrowid)
        self.events.publish(Event("customer.created", {"customer_id": customer_id}))
        return customer_id

    def search(self, query: str = "") -> list[Customer]:
        term = f"%{query.strip()}%"
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT id,customer_number,name,email,phone,street,postal_code,city,notes FROM customers
                   WHERE ?='' OR customer_number LIKE ? OR name LIKE ? OR email LIKE ? OR phone LIKE ? OR street LIKE ? OR postal_code LIKE ? OR city LIKE ?
                   OR EXISTS(SELECT 1 FROM contacts ct WHERE ct.customer_id=customers.id AND (ct.name LIKE ? OR ct.email LIKE ? OR ct.phone LIKE ?))
                   ORDER BY name COLLATE NOCASE LIMIT 200""",
                (query.strip(), term, term, term, term, term, term, term, term, term, term),
            ).fetchall()
        return [Customer(**dict(row)) for row in rows]

    def get(self, customer_id: int) -> Customer | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id,customer_number,name,email,phone,street,postal_code,city,notes FROM customers WHERE id=?", (customer_id,)
            ).fetchone()
        return Customer(**dict(row)) if row else None

    def update(self, customer_id: int, customer_number: str, name: str, email: str = "", phone: str = "", street: str = "", postal_code: str = "", city: str = "", notes: str = "") -> None:
        if not customer_number.strip() or not name.strip():
            raise ValueError("Klantnummer en naam zijn verplicht")
        with self.db.transaction() as conn:
            cur = conn.execute(
                """UPDATE customers SET customer_number=?,name=?,email=?,phone=?,street=?,postal_code=?,city=?,notes=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (*tuple(value.strip() for value in (customer_number, name, email, phone, street, postal_code, city, notes)), customer_id),
            )
            if not cur.rowcount:
                raise KeyError(customer_id)
        self.events.publish(Event("customer.updated", {"customer_id": customer_id}))

    def delete(self, customer_id: int) -> None:
        with self.db.transaction() as conn:
            vault_count = conn.execute("SELECT COUNT(*) FROM vault_entries WHERE customer_id=?", (customer_id,)).fetchone()[0]
            if vault_count:
                raise ValueError("Verwijder eerst de kluisgegevens van deze klant")
            cur = conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
            if not cur.rowcount:
                raise KeyError(customer_id)
        self.events.publish(Event("customer.deleted", {"customer_id": customer_id}))

    def count(self) -> int:
        with self.db.transaction() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0])

    def contacts(self, customer_id: int) -> list[Contact]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id,customer_id,name,role,email,phone FROM contacts WHERE customer_id=? ORDER BY name COLLATE NOCASE", (customer_id,)).fetchall()
        return [Contact(**dict(row)) for row in rows]

    def save_contact(self, customer_id: int, name: str, role: str = "", email: str = "", phone: str = "", contact_id: int | None = None) -> int:
        if not name.strip():
            raise ValueError("Naam van de contactpersoon is verplicht")
        values = tuple(value.strip() for value in (name, role, email, phone))
        with self.db.transaction() as conn:
            if contact_id:
                conn.execute("UPDATE contacts SET name=?,role=?,email=?,phone=? WHERE id=? AND customer_id=?", (*values, contact_id, customer_id))
                return contact_id
            cur = conn.execute("INSERT INTO contacts(customer_id,name,role,email,phone) VALUES(?,?,?,?,?)", (customer_id, *values))
            return int(cur.lastrowid)

    def delete_contact(self, contact_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
