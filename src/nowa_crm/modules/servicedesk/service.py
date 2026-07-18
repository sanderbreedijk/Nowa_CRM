from __future__ import annotations

from datetime import datetime

from nowa_crm.core.database import Database


class ServiceDeskService:
    STATUSES=("Open","In behandeling","Wacht op klant","Gepland","Opgelost","Gesloten")
    PRIORITIES=("Laag","Normaal","Hoog","Kritiek")

    def __init__(self,db: Database,actor: str):
        self.db,self.actor=db,actor

    def create(self,customer_id: int,subject: str,description: str="",category: str="Support",
               priority: str="Normaal",owner: str="NOWA",sla_due_at: str="",contact_id: int | None=None) -> int:
        if not subject.strip():raise ValueError("Onderwerp is verplicht")
        if priority not in self.PRIORITIES:raise ValueError("Ongeldige prioriteit")
        with self.db.transaction() as conn:
            year=datetime.now().year
            seq=int(conn.execute("SELECT COUNT(*) FROM service_tickets WHERE number LIKE ?",(f"TK-{year}-%",)).fetchone()[0])+1
            number=f"TK-{year}-{seq:05d}"
            cur=conn.execute("""INSERT INTO service_tickets(number,customer_id,contact_id,subject,description,category,priority,owner,sla_due_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",(number,customer_id,contact_id,subject.strip(),description.strip(),category.strip(),priority,owner.strip(),sla_due_at.strip()))
            ticket_id=int(cur.lastrowid)
            conn.execute("INSERT INTO ticket_updates(ticket_id,body,status,created_by) VALUES(?,?,?,?)",(ticket_id,"Ticket aangemaakt","Open",self.actor))
            return ticket_id

    def list(self,customer_id: int | None=None,status: str="",query: str="") -> list[dict]:
        clauses=["(?='' OR t.subject LIKE ? OR t.number LIKE ? OR c.name LIKE ?)"]; term=f"%{query.strip()}%"; values=[query.strip(),term,term,term]
        if customer_id is not None:clauses.append("t.customer_id=?"); values.append(customer_id)
        if status:clauses.append("t.status=?"); values.append(status)
        with self.db.transaction() as conn:
            return [dict(x) for x in conn.execute("""SELECT t.*,c.name customer_name,
                COALESCE((SELECT SUM(minutes) FROM ticket_time_entries e WHERE e.ticket_id=t.id),0) minutes
                FROM service_tickets t JOIN customers c ON c.id=t.customer_id WHERE """+" AND ".join(clauses)+
                """ ORDER BY CASE t.priority WHEN 'Kritiek' THEN 0 WHEN 'Hoog' THEN 1 WHEN 'Normaal' THEN 2 ELSE 3 END,
                CASE WHEN t.status IN ('Opgelost','Gesloten') THEN 1 ELSE 0 END,t.sla_due_at,t.id DESC""",values)]

    def get(self,ticket_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row=conn.execute("""SELECT t.*,c.name customer_name,COALESCE(ct.name,'') contact_name,
                COALESCE((SELECT SUM(minutes) FROM ticket_time_entries e WHERE e.ticket_id=t.id),0) minutes
                FROM service_tickets t JOIN customers c ON c.id=t.customer_id LEFT JOIN contacts ct ON ct.id=t.contact_id WHERE t.id=?""",(ticket_id,)).fetchone()
        return dict(row) if row else None

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
        return {"open":int(open_count),"critical":int(critical),"minutes":int(minutes)}
