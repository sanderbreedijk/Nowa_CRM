from __future__ import annotations

from dataclasses import dataclass
import json

from nowa_crm.core.database import Database
from nowa_crm.core.events import Event, EventBus
from nowa_crm.core.phone import format_phone, normalize_phone


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
    country: str
    mobile_phone: str
    status: str
    tags: str


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

    def create(self, customer_number: str, name: str, email: str = "", phone: str = "", street: str = "", postal_code: str = "", city: str = "", notes: str = "", mobile_phone: str = "", country: str = "", status: str = "actief", tags: str = "") -> int:
        if not customer_number.strip() or not name.strip():
            raise ValueError("Klantnummer en naam zijn verplicht")
        duplicates=self.find_duplicates(customer_number,name,email,phone,mobile_phone)
        if duplicates:raise ValueError("Mogelijk dubbele klant: "+", ".join(f"{x.customer_number} — {x.name}" for x in duplicates[:3]))
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO customers(customer_number,name,email,phone,street,postal_code,city,notes,mobile_phone,country,status,tags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (customer_number.strip(),name.strip(),email.strip(),format_phone(phone),street.strip(),postal_code.strip(),
                 city.strip(),notes.strip(),format_phone(mobile_phone),country.strip(),status.strip(),tags.strip()),
            )
            customer_id = int(cur.lastrowid)
            conn.execute("INSERT INTO customer_change_log(customer_id,action,changed_fields,detail) VALUES(?,?,?,?)",(customer_id,"Aangemaakt","alle velden",name.strip()))
        self.events.publish(Event("customer.created", {"customer_id": customer_id}))
        return customer_id

    def search(self, query: str = "") -> list[Customer]:
        term = f"%{query.strip()}%"
        phone_term=f"%{normalize_phone(query)}%" if normalize_phone(query) else term
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT id,customer_number,name,email,phone,street,postal_code,city,notes,country,mobile_phone,status,tags FROM customers
                   WHERE active=1 AND (?='' OR customer_number LIKE ? OR name LIKE ? OR email LIKE ? OR phone LIKE ? OR mobile_phone LIKE ? OR street LIKE ? OR postal_code LIKE ? OR city LIKE ? OR country LIKE ?
                   OR EXISTS(SELECT 1 FROM contacts ct WHERE ct.customer_id=customers.id AND (ct.name LIKE ? OR ct.email LIKE ? OR ct.phone LIKE ?))
                   OR replace(replace(phone,'-',''),' ','') LIKE ? OR replace(replace(mobile_phone,'-',''),' ','') LIKE ?
                   OR EXISTS(SELECT 1 FROM contacts ct WHERE ct.customer_id=customers.id AND replace(replace(ct.phone,'-',''),' ','') LIKE ?)
                   ) ORDER BY name COLLATE NOCASE LIMIT 5000""",
                (query.strip(), term, term, term, term, term, term, term, term, term, term, term, term,
                 phone_term,phone_term,phone_term),
            ).fetchall()
        return [Customer(**dict(row)) for row in rows]

    def get(self, customer_id: int) -> Customer | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id,customer_number,name,email,phone,street,postal_code,city,notes,country,mobile_phone,status,tags FROM customers WHERE id=?", (customer_id,)
            ).fetchone()
        return Customer(**dict(row)) if row else None

    def update(self, customer_id: int, customer_number: str, name: str, email: str = "", phone: str = "", street: str = "", postal_code: str = "", city: str = "", notes: str = "", mobile_phone: str = "", country: str = "", status: str | None = None, tags: str | None = None) -> None:
        if not customer_number.strip() or not name.strip():
            raise ValueError("Klantnummer en naam zijn verplicht")
        duplicates=self.find_duplicates(customer_number,name,email,phone,mobile_phone,customer_id)
        if duplicates:raise ValueError("Mogelijk dubbele klant: "+", ".join(f"{x.customer_number} — {x.name}" for x in duplicates[:3]))
        before=self.get(customer_id);status=before.status if status is None and before else status or "actief";tags=before.tags if tags is None and before else tags or ""
        names=("customer_number","name","email","phone","street","postal_code","city","notes","mobile_phone","country","status","tags")
        values=(customer_number.strip(),name.strip(),email.strip(),format_phone(phone),street.strip(),postal_code.strip(),
                city.strip(),notes.strip(),format_phone(mobile_phone),country.strip(),status.strip(),tags.strip())
        with self.db.transaction() as conn:
            cur = conn.execute(
                """UPDATE customers SET customer_number=?,name=?,email=?,phone=?,street=?,postal_code=?,city=?,notes=?,mobile_phone=?,country=?,status=?,tags=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (*values, customer_id),
            )
            if not cur.rowcount:
                raise KeyError(customer_id)
            changed=[key for key,value in zip(names,values) if before and getattr(before,key)!=value]
            if changed:conn.execute("INSERT INTO customer_change_log(customer_id,action,changed_fields,detail) VALUES(?,?,?,?)",(customer_id,"Bijgewerkt",", ".join(changed),json.dumps({key:value for key,value in zip(names,values) if key in changed},ensure_ascii=False)))
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
            return int(conn.execute("SELECT COUNT(*) FROM customers WHERE active=1").fetchone()[0])

    def find_duplicates(self,number,name,email="",phone="",mobile="",exclude_id=None) -> list[Customer]:
        values=[number.strip(),name.strip(),email.strip(),phone.strip(),mobile.strip()];clauses=["customer_number=?","lower(name)=lower(?)"]
        params=[values[0],values[1]]
        # A central/reception number may legitimately belong to multiple customer records.
        for column,value in (("email",values[2]),):
            if value:clauses.append(f"{column}=?");params.append(value)
        where=" OR ".join(clauses);extra=" AND id<>?" if exclude_id else ""
        if exclude_id:params.append(exclude_id)
        with self.db.transaction() as conn:rows=conn.execute(f"SELECT id,customer_number,name,email,phone,street,postal_code,city,notes,country,mobile_phone,status,tags FROM customers WHERE active=1 AND ({where}){extra} LIMIT 5",params).fetchall()
        return [Customer(**dict(row)) for row in rows]

    def history(self,customer_id:int) -> list[dict]:
        with self.db.transaction() as conn:return [dict(x) for x in conn.execute("SELECT action,changed_fields,detail,created_at FROM customer_change_log WHERE customer_id=? ORDER BY created_at DESC,id DESC",(customer_id,))]

    def contacts(self, customer_id: int) -> list[Contact]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id,customer_id,name,role,email,phone FROM contacts WHERE customer_id=? ORDER BY name COLLATE NOCASE", (customer_id,)).fetchall()
        return [Contact(**dict(row)) for row in rows]

    def save_contact(self, customer_id: int, name: str, role: str = "", email: str = "", phone: str = "", contact_id: int | None = None) -> int:
        if not name.strip():
            raise ValueError("Naam van de contactpersoon is verplicht")
        values = (name.strip(),role.strip(),email.strip(),format_phone(phone))
        with self.db.transaction() as conn:
            if contact_id:
                conn.execute("UPDATE contacts SET name=?,role=?,email=?,phone=? WHERE id=? AND customer_id=?", (*values, contact_id, customer_id))
                return contact_id
            cur = conn.execute("INSERT INTO contacts(customer_id,name,role,email,phone) VALUES(?,?,?,?,?)", (customer_id, *values))
            return int(cur.lastrowid)

    def delete_contact(self, contact_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
