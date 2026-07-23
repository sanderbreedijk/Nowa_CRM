from __future__ import annotations

from uuid import uuid4

from nowa_crm.core.database import Database
from nowa_crm.core.phone import format_phone, normalize_phone
from nowa_crm.modules.workspace.service import WorkspaceService


class TelephonyService:
    def __init__(self, db: Database, workspace: WorkspaceService, actor: str):
        self.db, self.workspace, self.actor = db, workspace, actor

    def recognize(self, phone_number: str) -> dict:
        normalized=normalize_phone(phone_number)
        if len(normalized)<6:
            return {"phone_number":phone_number,"normalized_number":normalized,"customer":None,"contact":None,"matches":[]}
        with self.db.transaction() as conn:
            links=conn.execute("""SELECT l.customer_id,l.contact_id,l.label,l.description,c.customer_number,c.name customer_name,
                COALESCE(ct.name,l.label,'') contact_name,COALESCE(ct.role,l.description,'') contact_role
                FROM call_number_links l JOIN customers c ON c.id=l.customer_id
                LEFT JOIN contacts ct ON ct.id=l.contact_id
                WHERE l.normalized_number=? AND c.active=1 ORDER BY c.name,contact_name""",(normalized,)).fetchall()
            contacts=conn.execute("SELECT id,customer_id,name,role,email,phone FROM contacts WHERE phone<>''").fetchall()
            customers=conn.execute("SELECT id,customer_number,name,email,phone,mobile_phone,city FROM customers WHERE active=1 AND (phone<>'' OR mobile_phone<>'')").fetchall()
        matches=[dict(row) for row in links]
        if not matches:
            for row in contacts:
                if _same_number(normalized,normalize_phone(row["phone"])):
                    customer=next((x for x in customers if x["id"]==row["customer_id"]),None)
                    if customer:matches.append({"customer_id":row["customer_id"],"contact_id":row["id"],
                        "customer_number":customer["customer_number"],"customer_name":customer["name"],
                        "contact_name":row["name"],"contact_role":row["role"],"label":row["name"],"description":row["role"]})
            for row in customers:
                if (_same_number(normalized,normalize_phone(row["phone"])) or
                        _same_number(normalized,normalize_phone(row["mobile_phone"]))):
                    if not any(x["customer_id"]==row["id"] and x.get("contact_id") is None for x in matches):
                        matches.append({"customer_id":row["id"],"contact_id":None,"customer_number":row["customer_number"],
                            "customer_name":row["name"],"contact_name":"","contact_role":"","label":"","description":""})
        if len(matches)==1:
            selected=matches[0]
            with self.db.transaction() as conn:
                customer=conn.execute("SELECT id,customer_number,name,email,phone,mobile_phone,city FROM customers WHERE id=?",(selected["customer_id"],)).fetchone()
                contact_row=conn.execute("SELECT id,customer_id,name,role,email,phone FROM contacts WHERE id=?",(selected["contact_id"],)).fetchone() if selected.get("contact_id") else None
            return {"phone_number":phone_number,"normalized_number":normalized,"customer":dict(customer) if customer else None,
                    "contact":dict(contact_row) if contact_row else None,"matches":matches}
        return {"phone_number":phone_number,"normalized_number":normalized,"customer":None,"contact":None,"matches":matches}

    def register_call(self, phone_number: str, direction: str = "inkomend", external_id: str = "") -> int:
        if direction not in ("inkomend","uitgaand"):raise ValueError("Ongeldige gespreksrichting")
        match=self.recognize(phone_number); customer=match["customer"]; contact=match["contact"]
        with self.db.transaction() as conn:
            if external_id:
                existing=conn.execute("SELECT id FROM call_events WHERE external_id=?",(external_id,)).fetchone()
                if existing:return int(existing["id"])
            cur=conn.execute("""INSERT INTO call_events(external_id,phone_number,normalized_number,direction,customer_id,contact_id,handled_by)
                VALUES(?,?,?,?,?,?,?)""",(external_id or uuid4().hex,format_phone(phone_number),match["normalized_number"],direction,
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
        self.mark_existing_missed(call_id)
        return call_id

    def mark_existing_missed(self, call_id: int) -> None:
        call=self.get(call_id)
        if not call or call["status"]=="gemist":return
        with self.db.transaction() as conn:
            conn.execute("""UPDATE call_events SET status='gemist',subject='Gemiste oproep',outcome='Niet beantwoord',
                priority='Hoog',assigned_to=?,callback_due=date('now'),callback_status='open',ended_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",(self.actor,call_id))
        if call and call["customer_id"]:
            self.workspace.add_action(call["customer_id"],f"Gemiste oproep terugbellen: {call['contact_name'] or call['phone_number']}",
                                      self.actor,"","Hoog","Automatisch aangemaakt vanuit telefonie.","Terugbellen",
                                      source_type="Telefoon",source_id=call_id)

    def acknowledge_call(self, call_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("""UPDATE call_events SET status=CASE WHEN status='nieuw' THEN 'actief' ELSE status END,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",(call_id,))

    def complete_callback(self, call_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE call_events SET callback_status='afgerond',updated_at=CURRENT_TIMESTAMP WHERE id=?",(call_id,))

    def missed_calls(self, open_only: bool = False) -> list[dict]:
        clause=" AND ce.callback_status='open'" if open_only else ""
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("""SELECT ce.id,ce.customer_id,ce.started_at,ce.phone_number,ce.priority,
                ce.assigned_to,ce.callback_status,ce.subject,COALESCE(c.name,'Onbekend') customer_name,
                COALESCE(ct.name,'') contact_name FROM call_events ce
                LEFT JOIN customers c ON c.id=ce.customer_id LEFT JOIN contacts ct ON ct.id=ce.contact_id
                WHERE ce.status='gemist' AND datetime(ce.started_at)>=datetime('now','-30 days')"""+clause+
                " ORDER BY ce.started_at DESC,ce.id DESC")]

    def missed_stats(self) -> dict:
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT COUNT(*) total,SUM(callback_status='open') open FROM call_events
                WHERE status='gemist' AND datetime(started_at)>=datetime('now','-30 days')""").fetchone()
        return {"total":int(row["total"] or 0),"open":int(row["open"] or 0)}

    def cleanup_missed_calls(self, retention_days: int = 30) -> int:
        days=max(1,int(retention_days))
        with self.db.transaction() as conn:
            ids=[int(row["id"]) for row in conn.execute("""SELECT id FROM call_events
                WHERE status='gemist' AND datetime(started_at)<datetime('now',?)""",(f"-{days} days",))]
            if not ids:return 0
            placeholders=",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM action_items WHERE source_type='Telefoon' AND source_id IN ({placeholders})",ids)
            conn.execute(f"DELETE FROM call_events WHERE id IN ({placeholders})",ids)
            return len(ids)

    def queue_stats(self) -> dict:
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT COUNT(*) total,SUM(status='gemist') missed,SUM(callback_status='open') callbacks,
                SUM(customer_id IS NULL) unknown FROM call_events""").fetchone()
        return {key:int(row[key] or 0) for key in ("total","missed","callbacks","unknown")}

    def customer_briefing(self, customer_id: int | None) -> dict:
        if not customer_id:
            return {"open_tickets": 0, "open_actions": 0, "recent_calls": [], "summary": "Nummer nog niet gekoppeld"}
        with self.db.transaction() as conn:
            tickets = conn.execute("""SELECT COUNT(*) total FROM service_tickets
                WHERE customer_id=? AND status NOT IN ('Gesloten','Afgerond')""", (customer_id,)).fetchone()
            actions = conn.execute("""SELECT COUNT(*) total FROM action_items
                WHERE customer_id=? AND status NOT IN ('Gereed','Geannuleerd')""", (customer_id,)).fetchone()
            recent = [dict(row) for row in conn.execute("""SELECT started_at,subject,outcome,status
                FROM call_events WHERE customer_id=? ORDER BY started_at DESC,id DESC LIMIT 3""", (customer_id,))]
        open_tickets, open_actions = int(tickets["total"]), int(actions["total"])
        parts = [f"{open_tickets} open servicetickets", f"{open_actions} open acties"]
        if recent:
            parts.append(f"laatste contact {recent[0]['started_at'][:10]}")
        return {"open_tickets": open_tickets, "open_actions": open_actions, "recent_calls": recent,
                "summary": " · ".join(parts)}

    def select_match(self,call_id: int,customer_id: int,contact_id: int | None=None) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE call_events SET customer_id=?,contact_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (customer_id,contact_id,call_id))

    def link_customer(self, call_id: int, customer_id: int, contact_id: int | None = None,
                      contact_name: str = "", description: str = "") -> int | None:
        with self.db.transaction() as conn:
            call=conn.execute("SELECT phone_number,normalized_number FROM call_events WHERE id=?",(call_id,)).fetchone()
            if not call:raise ValueError("Gesprek niet gevonden")
            if contact_name.strip() and contact_id is None:
                existing=conn.execute("SELECT id FROM contacts WHERE customer_id=? AND name=? COLLATE NOCASE",
                                      (customer_id,contact_name.strip())).fetchone()
                if existing:
                    contact_id=int(existing["id"])
                    conn.execute("UPDATE contacts SET role=?,phone=? WHERE id=?",
                                 (description.strip(),call["phone_number"],contact_id))
                else:
                    contact_id=int(conn.execute("INSERT INTO contacts(customer_id,name,role,phone) VALUES(?,?,?,?)",
                        (customer_id,contact_name.strip(),description.strip(),call["phone_number"])).lastrowid)
            conn.execute("UPDATE call_events SET customer_id=?,contact_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(customer_id,contact_id,call_id))
            if call["normalized_number"]:
                conn.execute("""INSERT INTO call_number_links(normalized_number,customer_id,contact_id,label,description,created_by)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(normalized_number,customer_id,contact_id) DO UPDATE SET
                    label=excluded.label,description=excluded.description,created_by=excluded.created_by""",
                    (call["normalized_number"],customer_id,contact_id,contact_name.strip(),description.strip(),self.actor))
        if description.strip():
            self.workspace.add_note(customer_id,f"Telefoonnummer gekoppeld: {contact_name or call['phone_number']}",description)
        return contact_id


def _same_number(left: str, right: str) -> bool:
    if not left or not right:return False
    return left==right or (len(left)>=8 and len(right)>=8 and left[-8:]==right[-8:])

