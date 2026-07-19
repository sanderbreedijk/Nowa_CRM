from __future__ import annotations

from uuid import uuid4

from nowa_crm.core.database import Database
from nowa_crm.modules.workspace.service import WorkspaceService


def normalize_phone(value: str) -> str:
    digits="".join(ch for ch in value if ch.isdigit())
    if digits.startswith("0031"):digits="0"+digits[4:]
    elif digits.startswith("31") and len(digits)>9:digits="0"+digits[2:]
    return digits.lstrip("0") if len(digits)>10 else digits


class TelephonyService:
    def __init__(self, db: Database, workspace: WorkspaceService, actor: str):
        self.db, self.workspace, self.actor = db, workspace, actor

    def recognize(self, phone_number: str) -> dict:
        normalized=normalize_phone(phone_number)
        if len(normalized)<6:
            return {"phone_number":phone_number,"normalized_number":normalized,"customer":None,"contact":None}
        with self.db.transaction() as conn:
            contacts=conn.execute("SELECT id,customer_id,name,role,email,phone FROM contacts WHERE phone<>''").fetchall()
            customers=conn.execute("SELECT id,customer_number,name,email,phone,city FROM customers WHERE phone<>''").fetchall()
        contact=next((dict(row) for row in contacts if _same_number(normalized,normalize_phone(row["phone"]))),None)
        customer_row=None
        if contact:
            with self.db.transaction() as conn:
                row=conn.execute("SELECT id,customer_number,name,email,phone,city FROM customers WHERE id=?",(contact["customer_id"],)).fetchone()
            customer_row=dict(row) if row else None
        if not customer_row:
            customer_row=next((dict(row) for row in customers if _same_number(normalized,normalize_phone(row["phone"]))),None)
        return {"phone_number":phone_number,"normalized_number":normalized,"customer":customer_row,"contact":contact}

    def register_call(self, phone_number: str, direction: str = "inkomend", external_id: str = "") -> int:
        if direction not in ("inkomend","uitgaand"):raise ValueError("Ongeldige gespreksrichting")
        match=self.recognize(phone_number); customer=match["customer"]; contact=match["contact"]
        with self.db.transaction() as conn:
            cur=conn.execute("""INSERT INTO call_events(external_id,phone_number,normalized_number,direction,customer_id,contact_id,handled_by)
                VALUES(?,?,?,?,?,?,?)""",(external_id or uuid4().hex,phone_number.strip(),match["normalized_number"],direction,
                customer["id"] if customer else None,contact["id"] if contact else None,self.actor))
            return int(cur.lastrowid)

    def get(self, call_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT ce.*,COALESCE(c.name,'Onbekend') customer_name,COALESCE(ct.name,'') contact_name
                FROM call_events ce LEFT JOIN customers c ON c.id=ce.customer_id LEFT JOIN contacts ct ON ct.id=ce.contact_id WHERE ce.id=?""",(call_id,)).fetchone()
        return dict(row) if row else None

    def history(self, customer_id: int | None = None, query: str = "") -> list[dict]:
        term=f"%{query.strip()}%"; values=[query.strip(),term,term,term,term]; customer_clause=""
        if customer_id is not None:customer_clause=" AND ce.customer_id=?"; values.append(customer_id)
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("""SELECT ce.id,ce.customer_id,ce.contact_id,ce.started_at,ce.direction,ce.phone_number,ce.status,ce.subject,ce.outcome,
                COALESCE(c.name,'Onbekend') customer_name,COALESCE(ct.name,'') contact_name FROM call_events ce
                LEFT JOIN customers c ON c.id=ce.customer_id LEFT JOIN contacts ct ON ct.id=ce.contact_id
                WHERE (?='' OR ce.phone_number LIKE ? OR c.name LIKE ? OR ct.name LIKE ? OR ce.subject LIKE ?)"""+customer_clause+
                " ORDER BY ce.started_at DESC,ce.id DESC LIMIT 500",values)]

    def finish_call(self, call_id: int, subject: str, notes: str, outcome: str, callback: bool = False, callback_due: str = "") -> None:
        call=self.get(call_id)
        if not call:raise ValueError("Gesprek niet gevonden")
        if callback and not call["customer_id"]:raise ValueError("Koppel het gesprek eerst aan een klant om een terugbelactie te maken.")
        with self.db.transaction() as conn:
            conn.execute("""UPDATE call_events SET subject=?,notes=?,outcome=?,status='afgerond',ended_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",(subject.strip(),notes.strip(),outcome.strip(),call_id))
        if call["customer_id"] and notes.strip():
            self.workspace.add_note(call["customer_id"],subject or "Telefoongesprek",notes)
        if callback:
            self.workspace.add_action(call["customer_id"],f"Terugbellen: {call['contact_name'] or call['phone_number']}",self.actor,callback_due,"Hoog",notes)

    def link_customer(self, call_id: int, customer_id: int, contact_id: int | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE call_events SET customer_id=?,contact_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(customer_id,contact_id,call_id))


def _same_number(left: str, right: str) -> bool:
    if not left or not right:return False
    return left==right or (len(left)>=8 and len(right)>=8 and left[-8:]==right[-8:])
