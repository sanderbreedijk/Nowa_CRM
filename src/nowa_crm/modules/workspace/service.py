from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir
from nowa_crm.modules.proposals.service import ProposalService


class WorkspaceService:
    def __init__(self, db: Database, proposals: ProposalService, actor: str, output_dir: Path | None = None):
        self.db, self.proposals, self.actor = db, proposals, actor
        self.output_dir = output_dir or data_dir()

    def global_search(self, query: str) -> list[dict]:
        value = query.strip()
        if len(value) < 2:
            return []
        term = f"%{value}%"
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT 'Klant' kind,c.id entity_id,c.id customer_id,c.name title,c.customer_number||' · '||c.city detail FROM customers c
                   WHERE c.name LIKE :term OR c.customer_number LIKE :term OR c.email LIKE :term OR c.phone LIKE :term OR c.city LIKE :term
                   UNION ALL
                   SELECT 'Contact',ct.id,ct.customer_id,ct.name,COALESCE(ct.role,'')||' · '||COALESCE(ct.email,'')||' · '||COALESCE(ct.phone,'') FROM contacts ct
                   WHERE ct.name LIKE :term OR ct.email LIKE :term OR ct.phone LIKE :term
                   UNION ALL
                   SELECT 'Offerte',p.id,p.customer_id,p.number||' · '||p.title,p.status FROM proposals p WHERE p.number LIKE :term OR p.title LIKE :term
                   UNION ALL
                   SELECT 'Kluis',v.id,v.customer_id,v.label,v.category||' · '||v.username||' · '||v.host FROM vault_entries v
                   WHERE v.label LIKE :term OR v.username LIKE :term OR v.host LIKE :term OR v.url LIKE :term
                   UNION ALL
                   SELECT 'Gebruiker',u.id,u.customer_id,u.display_name,u.user_principal_name||' · '||u.license_name FROM customer_users u
                   WHERE u.display_name LIKE :term OR u.user_principal_name LIKE :term
                   UNION ALL
                   SELECT 'Projecttaak',t.id,t.customer_id,t.task_name,t.phase||' · '||t.status FROM project_tasks t
                   WHERE t.task_name LIKE :term OR t.phase LIKE :term OR t.owner LIKE :term
                   UNION ALL
                   SELECT 'Ticket',s.id,s.customer_id,s.number||' · '||s.subject,s.priority||' · '||s.status FROM service_tickets s
                   WHERE s.number LIKE :term OR s.subject LIKE :term OR s.description LIKE :term OR s.owner LIKE :term
                   UNION ALL
                   SELECT 'Actie',a.id,a.customer_id,a.title,a.priority||' · '||a.status||' · '||a.due_date FROM action_items a
                   WHERE a.title LIKE :term OR a.notes LIKE :term OR a.owner LIKE :term
                   UNION ALL
                   SELECT 'Document',d.id,d.customer_id,d.title,d.document_type||' · '||d.original_name FROM customer_documents d
                   WHERE d.title LIKE :term OR d.original_name LIKE :term OR d.notes LIKE :term
                   UNION ALL
                   SELECT 'E-mail',m.id,m.customer_id,m.subject,m.direction||' · '||m.status||' · '||COALESCE(NULLIF(m.sender,''),m.recipients) FROM mail_messages m
                   WHERE m.subject LIKE :term OR m.sender LIKE :term OR m.recipients LIKE :term OR m.body LIKE :term
                   UNION ALL
                   SELECT 'Gesprek',ce.id,ce.customer_id,COALESCE(NULLIF(ce.subject,''),ce.phone_number),ce.direction||' · '||ce.status||' · '||ce.outcome FROM call_events ce
                   WHERE ce.phone_number LIKE :term OR ce.subject LIKE :term OR ce.notes LIKE :term OR ce.outcome LIKE :term
                   UNION ALL
                   SELECT 'Software',sw.id,sw.customer_id,sw.name,sw.vendor||' · '||sw.version||' · '||sw.support_scope FROM customer_software sw
                   WHERE sw.name LIKE :term OR sw.vendor LIKE :term OR sw.support_scope LIKE :term
                   LIMIT 250""",
                {"term":term},
            ).fetchall()
        return [dict(row) for row in rows]

    def notes(self, customer_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("SELECT id,subject,body,created_by,created_at FROM customer_notes WHERE customer_id=? ORDER BY id DESC", (customer_id,))]

    def add_note(self, customer_id: int, subject: str, body: str) -> int:
        if not body.strip():
            raise ValueError("Notitietekst is verplicht")
        with self.db.transaction() as conn:
            cur = conn.execute("INSERT INTO customer_notes(customer_id,subject,body,created_by) VALUES(?,?,?,?)",
                               (customer_id,subject.strip(),body.strip(),self.actor))
            return int(cur.lastrowid)

    def actions(self, customer_id: int | None = None, include_done: bool = False, owner: str = "", period: str = "Alles") -> list[dict]:
        clauses, values = [], []
        if customer_id is not None:
            clauses.append("a.customer_id=?"); values.append(customer_id)
        if not include_done:
            clauses.append("a.status NOT IN ('Gereed','Geannuleerd')")
        if owner.strip():
            clauses.append("a.owner LIKE ?"); values.append(f"%{owner.strip()}%")
        today=date.today().isoformat(); week=(date.today()+timedelta(days=7)).isoformat()
        if period == "Te laat": clauses.append("a.due_date<>'' AND a.due_date<?"); values.append(today)
        elif period == "Vandaag": clauses.append("a.due_date=?"); values.append(today)
        elif period == "Komende 7 dagen": clauses.append("a.due_date>=? AND a.due_date<=?"); values.extend((today,week))
        elif period == "Zonder deadline": clauses.append("a.due_date='' ")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT a.id,a.customer_id,COALESCE(c.name,'Algemeen') customer_name,a.title,a.owner,a.due_date,a.priority,a.status,a.notes,"
                "a.action_type,a.source_type,a.source_id,a.reminder_at,"
                "CASE WHEN a.status NOT IN ('Gereed','Geannuleerd') AND a.due_date<>'' AND a.due_date<? THEN 1 ELSE 0 END overdue "
                "FROM action_items a LEFT JOIN customers c ON c.id=a.customer_id" + where +
                " ORDER BY overdue DESC,CASE a.priority WHEN 'Hoog' THEN 0 WHEN 'Normaal' THEN 1 ELSE 2 END,CASE WHEN a.due_date='' THEN 1 ELSE 0 END,a.due_date,a.id", [today,*values])]

    def add_action(self, customer_id: int | None, title: str, owner: str = "NOWA", due_date: str = "",
                   priority: str = "Normaal", notes: str = "", action_type: str = "Taak",
                   reminder_at: str = "", source_type: str = "", source_id: int | None = None) -> int:
        if not title.strip():
            raise ValueError("Titel van het actiepunt is verplicht")
        for label,value in (("Deadline",due_date),("Herinnering",reminder_at)):
            if value.strip():
                try: datetime.fromisoformat(value.strip())
                except ValueError: raise ValueError(f"{label} moet jjjj-mm-dd of jjjj-mm-dd uu:mm zijn")
        with self.db.transaction() as conn:
            cur = conn.execute("INSERT INTO action_items(customer_id,title,owner,due_date,priority,notes,action_type,reminder_at,source_type,source_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                               (customer_id,title.strip(),owner.strip() or "NOWA",due_date.strip(),priority,notes.strip(),action_type,reminder_at.strip(),source_type,source_id))
            return int(cur.lastrowid)

    def complete_action(self, action_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE action_items SET status='Gereed',completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?", (action_id,))

    def set_action_status(self, action_id: int, status: str) -> None:
        if status not in ("Open","Bezig","Wacht op klant","Gereed","Geannuleerd"):
            raise ValueError("Onbekende actiestatus")
        with self.db.transaction() as conn:
            conn.execute("UPDATE action_items SET status=?,completed_at=CASE WHEN ?='Gereed' THEN CURRENT_TIMESTAMP ELSE NULL END,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,status,action_id))

    def reschedule_action(self, action_id: int, due_date: str) -> None:
        if due_date:
            try: date.fromisoformat(due_date)
            except ValueError: raise ValueError("Deadline moet jjjj-mm-dd zijn")
        with self.db.transaction() as conn:
            conn.execute("UPDATE action_items SET due_date=?,status=CASE WHEN status='Gereed' THEN 'Open' ELSE status END,updated_at=CURRENT_TIMESTAMP WHERE id=?",(due_date,action_id))

    def action_summary(self, owner: str = "") -> dict:
        today=date.today().isoformat(); week=(date.today()+timedelta(days=7)).isoformat()
        owner_sql=" AND owner LIKE ?" if owner.strip() else ""; values=[f"%{owner.strip()}%"] if owner.strip() else []
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT COUNT(*) open,
                SUM(CASE WHEN due_date<>'' AND due_date<? THEN 1 ELSE 0 END) overdue,
                SUM(CASE WHEN due_date=? THEN 1 ELSE 0 END) today,
                SUM(CASE WHEN due_date>? AND due_date<=? THEN 1 ELSE 0 END) upcoming
                FROM action_items WHERE status NOT IN ('Gereed','Geannuleerd')"""+owner_sql,[today,today,today,week,*values]).fetchone()
        return {key:int(row[key] or 0) for key in ("open","overdue","today","upcoming")}

    def commercial_settings(self, customer_id: int) -> dict:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM customer_commercial_settings WHERE customer_id=?", (customer_id,)).fetchone()
        return dict(row) if row else {"customer_id":customer_id,"hourly_rate_cents":9400,"discount_percent":0,
                                     "payment_term_days":14,"validity_days":30}

    def save_commercial_settings(self, customer_id: int, hourly_rate_cents: int, discount_percent: float,
                                 payment_term_days: int, validity_days: int) -> None:
        if hourly_rate_cents <= 0 or not 0 <= discount_percent <= 100:
            raise ValueError("Controleer uurtarief en kortingspercentage")
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO customer_commercial_settings(customer_id,hourly_rate_cents,discount_percent,payment_term_days,validity_days)
                VALUES(?,?,?,?,?) ON CONFLICT(customer_id) DO UPDATE SET hourly_rate_cents=excluded.hourly_rate_cents,
                discount_percent=excluded.discount_percent,payment_term_days=excluded.payment_term_days,validity_days=excluded.validity_days,
                updated_at=CURRENT_TIMESTAMP""",(customer_id,hourly_rate_cents,discount_percent,payment_term_days,validity_days))

    def build_intake_proposal(self, customer_id: int, title: str = "IT-modernisering") -> int:
        with self.db.transaction() as conn:
            intake = conn.execute("SELECT * FROM project_intakes WHERE customer_id=?", (customer_id,)).fetchone()
            licenses = conn.execute("SELECT product,quantity,unit_price_cents FROM customer_licenses WHERE customer_id=? AND included_in_proposal=1", (customer_id,)).fetchall()
            hardware = conn.execute("SELECT kind,brand,model,quantity,sales_price_cents FROM customer_hardware WHERE customer_id=?", (customer_id,)).fetchall()
        if not intake:
            raise ValueError("Vul eerst de projectintake voor deze klant in")
        settings = self.commercial_settings(customer_id); rate = settings["hourly_rate_cents"]
        proposal_id = self.proposals.create(customer_id,title)
        users, devices = int(intake["users_count"]), int(intake["devices_count"])
        base_hours = 6 + users * 1.25 + devices * .75 + int(intake["shared_mailboxes"]) * .5 + int(intake["teams_count"]) * .5 + int(intake["sharepoint_sites"])
        self.proposals.add_line(proposal_id,"uren","Inventarisatie, ontwerp en projectvoorbereiding",6,rate)
        if base_hours > 6:
            self.proposals.add_line(proposal_id,"uren","Migratie, inrichting, testen en overdracht",round(base_hours-6,2),rate)
        for row in licenses:
            self.proposals.add_line(proposal_id,"licentie",row["product"],row["quantity"],row["unit_price_cents"])
        for row in hardware:
            label=" ".join(x for x in (row["kind"],row["brand"],row["model"]) if x)
            self.proposals.add_line(proposal_id,"hardware",label,row["quantity"],row["sales_price_cents"])
        discount = float(settings["discount_percent"])
        if discount:
            subtotal = self.proposals.get(proposal_id).total_cents
            self.proposals.add_line(proposal_id,"korting",f"Klantkorting {discount:g}%",1,0)
            with self.db.transaction() as conn:
                line = conn.execute("SELECT id FROM proposal_lines WHERE proposal_id=? ORDER BY id DESC LIMIT 1",(proposal_id,)).fetchone()
                conn.execute("UPDATE proposal_lines SET unit_price_cents=? WHERE id=?",(-round(subtotal*discount/100),line["id"]))
                self.proposals._recalculate(conn,proposal_id)
        return proposal_id

    def progress_mail(self, customer_id: int) -> str:
        with self.db.transaction() as conn:
            customer = conn.execute("SELECT name FROM customers WHERE id=?", (customer_id,)).fetchone()
            tasks = conn.execute("SELECT status,COUNT(*) amount FROM project_tasks WHERE customer_id=? GROUP BY status",(customer_id,)).fetchall()
            users = conn.execute("SELECT COUNT(*) total,SUM(mfa_enabled) mfa FROM customer_users WHERE customer_id=? AND active=1",(customer_id,)).fetchone()
        task_summary=", ".join(f"{row['status']}: {row['amount']}" for row in tasks) or "nog geen projecttaken geregistreerd"
        text=(f"Onderwerp: Voortgang IT-project {customer['name'] if customer else ''}\n\n"
              f"Beste relatie,\n\nHierbij ontvangt u de actuele voortgang van het IT-project.\n\n"
              f"Projecttaken: {task_summary}.\nActieve gebruikers: {users['total'] or 0}; MFA geregistreerd: {users['mfa'] or 0}.\n\n"
              "Eventuele openstaande acties stemmen we rechtstreeks met u af.\n\nMet vriendelijke groet,\nNOWA Solutions")
        folder=self.output_dir/"exports"; folder.mkdir(parents=True,exist_ok=True)
        (folder/f"voortgang-{customer_id}-{datetime.now():%Y%m%d-%H%M}.txt").write_text(text,encoding="utf-8")
        return text

    def export_customer_csv(self, customer_id: int) -> list[Path]:
        folder=self.output_dir/"exports"/f"klant-{customer_id}"; folder.mkdir(parents=True,exist_ok=True)
        outputs=[]
        for name, table in (("gebruikers","customer_users"),("licenties","customer_licenses"),("hardware","customer_hardware"),("planning","project_tasks")):
            with self.db.transaction() as conn:
                rows=[dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE customer_id=?",(customer_id,))]
            target=folder/f"{name}.csv"
            if rows:
                with target.open("w",encoding="utf-8-sig",newline="") as handle:
                    writer=csv.DictWriter(handle,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            else:
                target.write_text("",encoding="utf-8-sig")
            outputs.append(target)
        return outputs

    def backup(self) -> Path:
        return self.db.backup("handmatig")
