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
            alias=conn.execute("SELECT customer_id,contact_id FROM call_customer_aliases WHERE normalized_number=?",(normalized,)).fetchone()
            contacts=conn.execute("SELECT id,customer_id,name,role,email,phone FROM contacts WHERE phone<>''").fetchall()
            customers=conn.execute("SELECT id,customer_number,name,email,phone,mobile_phone,city FROM customers WHERE active=1 AND (phone<>'' OR mobile_phone<>'')").fetchall()
        if alias:
            with self.db.transaction() as conn:
                customer=conn.execute("SELECT id,customer_number,name,email,phone,mobile_phone,city FROM customers WHERE id=?",(alias["customer_id"],)).fetchone()
                contact_row=conn.execute("SELECT id,customer_id,name,role,email,phone FROM contacts WHERE id=?",(alias["contact_id"],)).fetchone() if alias["contact_id"] else None
            return {"phone_number":phone_number,"normalized_number":normalized,"customer":dict(customer) if customer else None,
                    "contact":dict(contact_row) if contact_row else None}
        contact=next((dict(row) for row in contacts if _same_number(normalized,normalize_phone(row["phone"]))),None)
        customer_row=None
        if contact:
            with self.db.transaction() as conn:
                row=conn.execute("SELECT id,customer_number,name,email,phone,mobile_phone,city FROM customers WHERE id=?",(contact["customer_id"],)).fetchone()
            customer_row=dict(row) if row else None
        if not customer_row:
            customer_row=next((dict(row) for row in customers if _same_number(normalized,normalize_phone(row["phone"]))
                               or _same_number(normalized,normalize_phone(row["mobile_phone"]))),None)
        return {"phone_number":phone_number,"normalized_number":normalized,"customer":customer_row,"contact":contact}

    def register_call(self, phone_number: str, direction: str = "inkomend", external_id: str = "") -> int:
        if direction not in ("inkomend","uitgaand"):raise ValueError("Ongeldige gespreksrichting")
        match=self.recognize(phone_number); customer=match["customer"]; contact=match["contact"]
        with self.db.transaction() as conn:
            if external_id:
                existing=conn.execute("SELECT id FROM call_events WHERE external_id=?",(external_id,)).fetchone()
                if existing:return int(existing["id"])
            cur=conn.execute("""INSERT INTO call_events(external_id,phone_number,normalized_number,direction,customer_id,contact_id,handled_by)
                VALUES(?,?,?,?,?,?,?)""",(external_id or uuid4().hex,phone_number.strip(),match["normalized_number"],direction,
                customer["id"] if customer else None,contact["id"] if contact else None,self.actor))
            return int(cur.lastrowid)

    def get(self, call_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT ce.*,COALESCE(c.name,'Onbekend') customer_name,COALESCE(ct.name,'') contact_name
                FROM call_events ce LEFT JOIN customers c ON c.id=ce.customer_id LEFT JOIN contacts ct ON ct.id=ce.contact_id WHERE ce.id=?""",(call_id,)).fetchone()
        return dict(row) if row else None

    def history(self, customer_id: int | None = None, query: str = "", queue: str = "alle") -> list[dict]:
        term=f"%{query.strip()}%"; values=[query.strip(),term,term,term,term]; customer_clause=""
        if customer_id is not None:customer_clause=" AND ce.customer_id=?"; values.append(customer_id)
        queue_clause=""
        if queue=="terugbellen":queue_clause=" AND ce.callback_status='open'"
        elif queue=="gemist":queue_clause=" AND ce.status='gemist'"
        elif queue=="onbekend":queue_clause=" AND ce.customer_id IS NULL"
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("""SELECT ce.id,ce.customer_id,ce.contact_id,ce.started_at,ce.direction,ce.phone_number,ce.status,ce.subject,ce.outcome,
                ce.priority,ce.assigned_to,ce.callback_due,ce.callback_status,COALESCE(c.name,'Onbekend') customer_name,COALESCE(ct.name,'') contact_name FROM call_events ce
                LEFT JOIN customers c ON c.id=ce.customer_id LEFT JOIN contacts ct ON ct.id=ce.contact_id
                WHERE (?='' OR ce.phone_number LIKE ? OR c.name LIKE ? OR ct.name LIKE ? OR ce.subject LIKE ?)"""+customer_clause+queue_clause+
                " ORDER BY ce.started_at DESC,ce.id DESC LIMIT 500",values)]

    def finish_call(self, call_id: int, subject: str, notes: str, outcome: str, callback: bool = False,
                    callback_due: str = "", priority: str = "Normaal", assigned_to: str = "") -> None:
        call=self.get(call_id)
        if not call:raise ValueError("Gesprek niet gevonden")
        if callback and not call["customer_id"]:raise ValueError("Koppel het gesprek eerst aan een klant om een terugbelactie te maken.")
        with self.db.transaction() as conn:
            conn.execute("""UPDATE call_events SET subject=?,notes=?,outcome=?,status='afgerond',ended_at=CURRENT_TIMESTAMP,
                priority=?,assigned_to=?,callback_due=?,callback_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (subject.strip(),notes.strip(),outcome.strip(),priority,assigned_to.strip(),callback_due.strip() if callback else "",
                 "open" if callback else "",call_id))
        if call["customer_id"] and notes.strip():
            self.workspace.add_note(call["customer_id"],subject or "Telefoongesprek",notes)
        if callback:
            self.workspace.add_action(call["customer_id"],f"Terugbellen: {call['contact_name'] or call['phone_number']}",assigned_to or self.actor,callback_due,priority,notes,
                                      "Terugbellen",source_type="Telefoon",source_id=call_id)

    def mark_missed(self, phone_number: str, external_id: str = "") -> int:
        call_id=self.register_call(phone_number,"inkomend",external_id)
        call=self.get(call_id)
        with self.db.transaction() as conn:
            conn.execute("""UPDATE call_events SET status='gemist',subject='Gemiste oproep',outcome='Niet beantwoord',
                priority='Hoog',assigned_to=?,callback_due=date('now'),callback_status='open',ended_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",(self.actor,call_id))
        if call and call["customer_id"]:
            self.workspace.add_action(call["customer_id"],f"Gemiste oproep terugbellen: {call['contact_name'] or call['phone_number']}",
                                      self.actor,"","Hoog","Automatisch aangemaakt vanuit telefonie.","Terugbellen",
                                      source_type="Telefoon",source_id=call_id)
        return call_id

    def complete_callback(self, call_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE call_events SET callback_status='afgerond',updated_at=CURRENT_TIMESTAMP WHERE id=?",(call_id,))

    def queue_stats(self) -> dict:
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT COUNT(*) total,SUM(status='gemist') missed,SUM(callback_status='open') callbacks,
                SUM(customer_id IS NULL) unknown FROM call_events""").fetchone()
        return {key:int(row[key] or 0) for key in ("total","missed","callbacks","unknown")}

    def link_customer(self, call_id: int, customer_id: int, contact_id: int | None = None) -> None:
        with self.db.transaction() as conn:
            call=conn.execute("SELECT normalized_number FROM call_events WHERE id=?",(call_id,)).fetchone()
            conn.execute("UPDATE call_events SET customer_id=?,contact_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(customer_id,contact_id,call_id))
            if call and call["normalized_number"]:
                conn.execute("""INSERT INTO call_customer_aliases(customer_id,contact_id,normalized_number,source,created_by)
                    VALUES(?,?,?,'gesprekskoppeling',?) ON CONFLICT(normalized_number) DO UPDATE SET
                    customer_id=excluded.customer_id,contact_id=excluded.contact_id,source=excluded.source,created_by=excluded.created_by""",
                    (customer_id,contact_id,call["normalized_number"],self.actor))


def _same_number(left: str, right: str) -> bool:
    if not left or not right:return False
    return left==right or (len(left)>=8 and len(right)>=8 and left[-8:]==right[-8:])

