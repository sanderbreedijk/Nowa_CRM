from __future__ import annotations

from datetime import datetime, timedelta

from nowa_crm.core.database import Database


class ServiceDeskService:
    STATUSES=("Open","In behandeling","Wacht op klant","Gepland","Opgelost","Gesloten")
    PRIORITIES=("Laag","Normaal","Hoog","Kritiek")
    DEFAULT_SLA_HOURS={"Laag":72,"Normaal":24,"Hoog":8,"Kritiek":4}

    def __init__(self,db: Database,actor: str):
        self.db,self.actor=db,actor

    def create(self,customer_id: int,subject: str,description: str="",category: str="Support",
               priority: str="Normaal",owner: str="NOWA",sla_due_at: str="",contact_id: int | None=None,
               source_type: str="",source_id: int | None=None) -> int:
        if not subject.strip():raise ValueError("Onderwerp is verplicht")
        if priority not in self.PRIORITIES:raise ValueError("Ongeldige prioriteit")
        if not sla_due_at.strip():
            sla_due_at=(datetime.now()+timedelta(hours=self.sla_hours(priority))).strftime("%Y-%m-%d %H:%M")
        with self.db.transaction() as conn:
            year=datetime.now().year
            seq=int(conn.execute("SELECT COUNT(*) FROM service_tickets WHERE number LIKE ?",(f"TK-{year}-%",)).fetchone()[0])+1
            number=f"TK-{year}-{seq:05d}"
            cur=conn.execute("""INSERT INTO service_tickets(number,customer_id,contact_id,subject,description,category,priority,owner,sla_due_at,source_type,source_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(number,customer_id,contact_id,subject.strip(),description.strip(),category.strip(),priority,owner.strip(),sla_due_at.strip(),source_type.strip(),source_id))
            ticket_id=int(cur.lastrowid)
            conn.execute("INSERT INTO ticket_updates(ticket_id,body,status,created_by) VALUES(?,?,?,?)",(ticket_id,"Ticket aangemaakt","Open",self.actor))
            return ticket_id

    def list(self,customer_id: int | None=None,status: str="",query: str="",priority: str="",owner: str="",sla: str="") -> list[dict]:
        clauses=["(?='' OR t.subject LIKE ? OR t.number LIKE ? OR c.name LIKE ?)"]; term=f"%{query.strip()}%"; values=[query.strip(),term,term,term]
        if customer_id is not None:clauses.append("t.customer_id=?"); values.append(customer_id)
        if status:clauses.append("t.status=?"); values.append(status)
        if priority:clauses.append("t.priority=?"); values.append(priority)
        if owner:clauses.append("t.owner=?"); values.append(owner)
        with self.db.transaction() as conn:
            rows=[dict(x) for x in conn.execute("""SELECT t.*,c.name customer_name,
                COALESCE((SELECT SUM(minutes) FROM ticket_time_entries e WHERE e.ticket_id=t.id),0) minutes
                FROM service_tickets t JOIN customers c ON c.id=t.customer_id WHERE """+" AND ".join(clauses)+
                """ ORDER BY CASE t.priority WHEN 'Kritiek' THEN 0 WHEN 'Hoog' THEN 1 WHEN 'Normaal' THEN 2 ELSE 3 END,
                CASE WHEN t.status IN ('Opgelost','Gesloten') THEN 1 ELSE 0 END,t.sla_due_at,t.id DESC""",values)]
        for row in rows:row["sla_state"]=self.sla_state(row)
        return [row for row in rows if not sla or row["sla_state"]==sla]

    def get(self,ticket_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT t.*,c.name customer_name,COALESCE(ct.name,'') contact_name,
                COALESCE((SELECT SUM(minutes) FROM ticket_time_entries e WHERE e.ticket_id=t.id),0) minutes
                FROM service_tickets t JOIN customers c ON c.id=t.customer_id LEFT JOIN contacts ct ON ct.id=t.contact_id WHERE t.id=?""",(ticket_id,)).fetchone()
        result=dict(row) if row else None
        if result:result["sla_state"]=self.sla_state(result)
        return result

    def sla_hours(self,priority: str) -> int:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT resolution_hours FROM sla_policies WHERE priority=?",(priority,)).fetchone()
        return int(row[0]) if row else self.DEFAULT_SLA_HOURS[priority]

    @staticmethod
    def sla_state(ticket: dict,now: datetime | None=None) -> str:
        if ticket["status"] in ("Opgelost","Gesloten"):return "Afgerond"
        if not ticket.get("sla_due_at"):return "Geen SLA"
        try:due=datetime.fromisoformat(ticket["sla_due_at"])
        except ValueError:return "Onbekend"
        remaining=due-(now or datetime.now())
        if remaining.total_seconds()<0:return "Overschreden"
        if remaining.total_seconds()<=7200:return "Dreigt"
        return "Binnen SLA"

    def owners(self) -> list[str]:
        with self.db.transaction() as conn:return [str(x[0]) for x in conn.execute("SELECT DISTINCT owner FROM service_tickets WHERE owner<>'' ORDER BY owner")]

    def create_from_source(self,customer_id: int,subject: str,description: str,source_type: str,source_id: int,priority: str="Normaal") -> int:
        return self.create(customer_id,subject,description,priority=priority,source_type=source_type,source_id=source_id)

    def updates(self,ticket_id: int) -> list[dict]:
        with self.db.transaction() as conn:return [dict(x) for x in conn.execute("SELECT * FROM ticket_updates WHERE ticket_id=? ORDER BY id DESC",(ticket_id,))]

    def add_update(self,ticket_id: int,body: str,status: str="") -> None:
        if not body.strip():raise ValueError("Voortgangstekst is verplicht")
        if status and status not in self.STATUSES:raise ValueError("Ongeldige ticketstatus")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO ticket_updates(ticket_id,body,status,created_by) VALUES(?,?,?,?)",(ticket_id,body.strip(),status,self.actor))
            if status:
                closed="CURRENT_TIMESTAMP" if status in ("Opgelost","Gesloten") else "NULL"
                conn.execute(f"UPDATE service_tickets SET status=?,updated_at=CURRENT_TIMESTAMP,closed_at={closed} WHERE id=?",(status,ticket_id))

    def add_time(self,ticket_id: int,minutes: int,description: str="") -> None:
        if minutes<=0:raise ValueError("Tijd moet groter zijn dan nul")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO ticket_time_entries(ticket_id,minutes,description,created_by) VALUES(?,?,?,?)",(ticket_id,minutes,description.strip(),self.actor))
            conn.execute("UPDATE service_tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(ticket_id,))

    def close(self,ticket_id: int,resolution: str) -> None:
        if not resolution.strip():raise ValueError("Oplossing is verplicht")
        with self.db.transaction() as conn:
            conn.execute("UPDATE service_tickets SET status='Gesloten',resolution=?,closed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(resolution.strip(),ticket_id))
            conn.execute("INSERT INTO ticket_updates(ticket_id,body,status,created_by) VALUES(?,?,?,?)",(ticket_id,resolution.strip(),"Gesloten",self.actor))

    def stats(self,customer_id: int | None=None) -> dict:
        where=" WHERE customer_id=?" if customer_id is not None else ""; values=(customer_id,) if customer_id is not None else ()
        with self.db.transaction() as conn:
            open_count=conn.execute("SELECT COUNT(*) FROM service_tickets"+where+(" AND" if where else " WHERE")+" status NOT IN ('Opgelost','Gesloten')",values).fetchone()[0]
            critical=conn.execute("SELECT COUNT(*) FROM service_tickets"+where+(" AND" if where else " WHERE")+" priority='Kritiek' AND status NOT IN ('Opgelost','Gesloten')",values).fetchone()[0]
            minutes=conn.execute("""SELECT COALESCE(SUM(e.minutes),0) FROM ticket_time_entries e JOIN service_tickets t ON t.id=e.ticket_id"""+(" WHERE t.customer_id=?" if customer_id is not None else ""),values).fetchone()[0]
            overdue=conn.execute("SELECT COUNT(*) FROM service_tickets"+where+(" AND" if where else " WHERE")+" status NOT IN ('Opgelost','Gesloten') AND sla_due_at<>'' AND datetime(sla_due_at)<datetime('now','localtime')",values).fetchone()[0]
            due_soon=conn.execute("SELECT COUNT(*) FROM service_tickets"+where+(" AND" if where else " WHERE")+" status NOT IN ('Opgelost','Gesloten') AND datetime(sla_due_at) BETWEEN datetime('now','localtime') AND datetime('now','localtime','+2 hours')",values).fetchone()[0]
            closed=conn.execute("SELECT COUNT(*) FROM service_tickets"+where+(" AND" if where else " WHERE")+" status IN ('Opgelost','Gesloten')",values).fetchone()[0]
        return {"open":int(open_count),"critical":int(critical),"minutes":int(minutes),"overdue":int(overdue),"due_soon":int(due_soon),"closed":int(closed)}

    def add_maintenance(self,customer_id: int,title: str,frequency: str,next_due_date: str,owner: str="NOWA",notes: str="") -> int:
        if not title.strip():raise ValueError("Onderhoudstaak is verplicht")
        with self.db.transaction() as conn:return int(conn.execute("INSERT INTO maintenance_tasks(customer_id,title,frequency,next_due_date,owner,notes) VALUES(?,?,?,?,?,?)",(customer_id,title.strip(),frequency,next_due_date.strip(),owner.strip(),notes.strip())).lastrowid)

    def maintenance(self,customer_id: int | None=None) -> list[dict]:
        values=() if customer_id is None else (customer_id,); where="" if customer_id is None else " AND m.customer_id=?"
        with self.db.transaction() as conn:return [dict(x) for x in conn.execute("SELECT m.*,c.name customer_name FROM maintenance_tasks m JOIN customers c ON c.id=m.customer_id WHERE m.active=1"+where+" ORDER BY m.next_due_date,m.id",values)]
