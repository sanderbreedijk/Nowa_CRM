from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir


class PlanningService:
    PHASES = ("Inventarisatie","Voorbereiding","Inrichting","Migratie","Werkplekken","Training","Oplevering","Nazorg")
    STATUSES = ("Gepland","In behandeling","Wacht op klant","Wacht op derde","Gereed","Geannuleerd")
    DEFAULTS = (
        ("Inventarisatie","Klant",1,"Gebruikerslijst, licenties, beheeraccounts en planning bevestigen."),
        ("Voorbereiding","NOWA",2,"Tenant, domein, DNS, communicatie en migratievoorbereiding."),
        ("Inrichting","NOWA",3,"Microsoft 365, security, Intune, MFA en basisstructuur inrichten."),
        ("Migratie","NOWA",2,"Mailboxen, OneDrive, SharePoint en Teams migreren volgens scope."),
        ("Werkplekken","NOWA",3,"Werkplekken configureren, randapparatuur en eindcontrole."),
        ("Training","NOWA/Klant",1,"Instructie en key-user overdracht."),
        ("Oplevering","NOWA",1,"Opleverdocument, controles, akkoord en nazorgafspraken."),
        ("Nazorg","NOWA",5,"Ondersteuning en nacontrole na livegang."),
    )

    def __init__(self, db: Database, output_dir: Path | None = None):
        self.db = db
        self.output_dir = output_dir or data_dir() / "exports" / "planning"

    def list(self, customer_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM project_tasks WHERE customer_id=? ORDER BY COALESCE(start_date,''),id",(customer_id,))]

    def save(self, customer_id: int, phase: str, task_name: str, owner: str = "NOWA",
             start_date: str = "", end_date: str = "", dependency: str = "",
             status: str = "Gepland", notes: str = "", task_id: int | None = None) -> int:
        if not task_name.strip(): raise ValueError("Taaknaam is verplicht")
        self._validate_dates(start_date,end_date)
        with self.db.transaction() as conn:
            if task_id:
                found=conn.execute("SELECT id FROM project_tasks WHERE id=? AND customer_id=?",(task_id,customer_id)).fetchone()
                if not found: raise ValueError("Projecttaak bestaat niet")
                conn.execute("""UPDATE project_tasks SET phase=?,task_name=?,owner=?,start_date=?,end_date=?,
                    dependency=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (phase.strip(),task_name.strip(),owner.strip(),start_date.strip(),end_date.strip(),
                     dependency.strip(),status.strip(),notes.strip(),task_id))
                return task_id
            return int(conn.execute("""INSERT INTO project_tasks
                (customer_id,phase,task_name,owner,start_date,end_date,dependency,status,notes)
                VALUES(?,?,?,?,?,?,?,?,?)""",(customer_id,phase.strip(),task_name.strip(),owner.strip(),
                start_date.strip(),end_date.strip(),dependency.strip(),status.strip(),notes.strip())).lastrowid)

    def delete(self, task_id: int) -> None:
        with self.db.transaction() as conn: conn.execute("DELETE FROM project_tasks WHERE id=?",(task_id,))

    def seed(self, customer_id: int, start: date | None = None) -> int:
        if self.list(customer_id): return 0
        cursor=start or date.today(); dependency=""; count=0
        for phase,owner,days,notes in self.DEFAULTS:
            end=cursor+timedelta(days=max(0,days-1))
            self.save(customer_id,phase,phase,owner,cursor.isoformat(),end.isoformat(),dependency,"Gepland",notes)
            dependency=phase; cursor=end+timedelta(days=1); count+=1
        return count

    def stats(self, customer_id: int) -> dict:
        rows=self.list(customer_id); today=date.today().isoformat()
        done=sum(1 for row in rows if row["status"]=="Gereed")
        overdue=sum(1 for row in rows if row["end_date"] and row["end_date"]<today and row["status"] not in ("Gereed","Geannuleerd"))
        waiting=sum(1 for row in rows if row["status"].startswith("Wacht"))
        return {"total":len(rows),"done":done,"open":len(rows)-done-sum(1 for r in rows if r["status"]=="Geannuleerd"),
                "overdue":overdue,"waiting":waiting,"progress":round(done*100/len(rows)) if rows else 0}

    def export_csv(self, customer_id: int) -> Path:
        folder=self._folder(customer_id); target=folder/"projectplanning.csv"
        with target.open("w",encoding="utf-8-sig",newline="") as handle:
            writer=csv.writer(handle,delimiter=";")
            writer.writerow(["Fase","Taak","Eigenaar","Start","Einde","Afhankelijkheid","Status","Notities"])
            for row in self.list(customer_id):
                writer.writerow([row[key] for key in ("phase","task_name","owner","start_date","end_date","dependency","status","notes")])
        return target

    def export_pdf(self, customer_id: int) -> Path:
        with self.db.transaction() as conn:
            customer=conn.execute("SELECT name,customer_number FROM customers WHERE id=?",(customer_id,)).fetchone()
        if not customer: raise ValueError("Klant bestaat niet")
        target=self._folder(customer_id)/"projectplanning.pdf"; rows=self.list(customer_id); stats=self.stats(customer_id)
        story=[Paragraph("NOWA Projectplanning",self._style(20,"#123458",True)),
               Paragraph(f"{customer['customer_number']} — {customer['name']}",self._style(13,"#24649c",True)),
               Paragraph(f"Voortgang {stats['progress']}% · {stats['open']} open · {stats['overdue']} te laat · {stats['waiting']} wachtend",
                         self._style(9,"#334155")),Spacer(1,5*mm)]
        data=[["Fase","Taak","Eigenaar","Start","Einde","Afhankelijkheid","Status"]]
        data.extend([[r["phase"],r["task_name"],r["owner"],r["start_date"],r["end_date"],r["dependency"],r["status"]] for r in rows])
        table=Table(data,colWidths=[31*mm,52*mm,27*mm,24*mm,24*mm,45*mm,31*mm],repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#123458")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f4f7fb")]),
            ("VALIGN",(0,0),(-1,-1),"TOP")]))
        story.append(table)
        doc=SimpleDocTemplate(str(target),pagesize=landscape(A4),leftMargin=14*mm,rightMargin=14*mm,topMargin=12*mm,bottomMargin=12*mm)
        doc.build(story); return target

    def _folder(self, customer_id: int) -> Path:
        folder=self.output_dir/f"klant-{customer_id}"; folder.mkdir(parents=True,exist_ok=True); return folder

    @staticmethod
    def _validate_dates(start: str,end: str) -> None:
        for value in (start,end):
            if value:
                try: datetime.strptime(value,"%Y-%m-%d")
                except ValueError as exc: raise ValueError("Gebruik voor datums JJJJ-MM-DD") from exc
        if start and end and end<start: raise ValueError("Einddatum ligt vóór de startdatum")

    @staticmethod
    def _style(size: int,color: str,bold: bool=False):
        from reportlab.lib.styles import ParagraphStyle
        return ParagraphStyle(name=f"p{size}{color}{bold}",fontName="Helvetica-Bold" if bold else "Helvetica",
                              fontSize=size,leading=size+4,textColor=colors.HexColor(color),spaceAfter=5)
