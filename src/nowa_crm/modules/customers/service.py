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
    city: str


class CustomerService:
    def __init__(self, db: Database, events: EventBus):
        self.db, self.events = db, events

    def create(self, customer_number: str, name: str, email: str = "", phone: str = "", city: str = "") -> int:
        if not customer_number.strip() or not name.strip():
            raise ValueError("Klantnummer en naam zijn verplicht")
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO customers(customer_number,name,email,phone,city) VALUES(?,?,?,?,?)",
                (customer_number.strip(), name.strip(), email.strip(), phone.strip(), city.strip()),
            )
            customer_id = int(cur.lastrowid)
        self.events.publish(Event("customer.created", {"customer_id": customer_id}))
        return customer_id

    def search(self, query: str = "") -> list[Customer]:
        term = f"%{query.strip()}%"
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT id,customer_number,name,email,phone,city FROM customers
                   WHERE ?='' OR customer_number LIKE ? OR name LIKE ? OR email LIKE ? OR phone LIKE ? OR city LIKE ?
                   ORDER BY name COLLATE NOCASE LIMIT 200""",
                (query.strip(), term, term, term, term, term),
            ).fetchall()
        return [Customer(**dict(row)) for row in rows]

    def get(self, customer_id: int) -> Customer | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id,customer_number,name,email,phone,city FROM customers WHERE id=?", (customer_id,)
            ).fetchone()
        return Customer(**dict(row)) if row else None

    def update(self, customer_id: int, customer_number: str, name: str, email: str = "", phone: str = "", city: str = "") -> None:
        if not customer_number.strip() or not name.strip():
            raise ValueError("Klantnummer en naam zijn verplicht")
        with self.db.transaction() as conn:
            cur = conn.execute(
                """UPDATE customers SET customer_number=?,name=?,email=?,phone=?,city=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (customer_number.strip(), name.strip(), email.strip(), phone.strip(), city.strip(), customer_id),
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
