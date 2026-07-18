from __future__ import annotations

from datetime import datetime
from pathlib import Path

from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir
from nowa_crm.modules.mail.service import MailService


class ReportingService:
    DONE = {"Gereed", "Afgerond", "Gesloten", "Opgelost"}

    def __init__(self, db: Database, actor: str, mail: MailService | None = None, output_dir: Path | None = None):
        self.db, self.actor, self.mail = db, actor, mail
        self.output_dir = output_dir or data_dir() / "exports" / "rapportages"

    def snapshot(self, customer_id: int) -> dict:
        with self.db.transaction() as conn:
            customer = conn.execute("SELECT id,name,email FROM customers WHERE id=?", (customer_id,)).fetchone()
            if not customer:
                raise ValueError("Klant bestaat niet")
            intake = conn.execute("SELECT * FROM project_intakes WHERE customer_id=?", (customer_id,)).fetchone()
            tasks = [dict(row) for row in conn.execute(
                "SELECT id,phase,task_name,owner,start_date,end_date,dependency,status,notes FROM project_tasks "
                "WHERE customer_id=? ORDER BY start_date,phase,id", (customer_id,))]
            actions = [dict(row) for row in conn.execute(
                "SELECT id,title,owner,due_date,priority,status,notes FROM action_items "
                "WHERE customer_id=? AND status NOT IN ('Gereed','Geannuleerd') ORDER BY due_date,id", (customer_id,))]
            tickets = [dict(row) for row in conn.execute(
                "SELECT id,number,subject,priority,status,owner,sla_due_at FROM service_tickets "
                "WHERE customer_id=? AND status NOT IN ('Opgelost','Gesloten') ORDER BY "
                "CASE priority WHEN 'Kritiek' THEN 0 WHEN 'Hoog' THEN 1 ELSE 2 END,id", (customer_id,))]
            users = conn.execute(
                "SELECT COUNT(*) total,COALESCE(SUM(mfa_enabled),0) mfa FROM customer_users WHERE customer_id=? AND active=1",
                (customer_id,)).fetchone()
            licenses = conn.execute(
                "SELECT COALESCE(SUM(quantity),0) amount FROM customer_licenses WHERE customer_id=?", (customer_id,)).fetchone()
            hardware = conn.execute(
                "SELECT COALESCE(SUM(quantity),0) amount FROM customer_hardware WHERE customer_id=?", (customer_id,)).fetchone()
        done = sum(1 for task in tasks if task["status"] in self.DONE)
        progress = round(done * 100 / len(tasks)) if tasks else 0
        waiting = [task for task in tasks if "wacht" in task["status"].lower()]
        risks = []
        if any(ticket["priority"] == "Kritiek" for ticket in tickets):
            risks.append("Er staan kritieke servicedesktickets open.")
        if waiting:
            risks.append(f"{len(waiting)} projecttaak/taken wachten op input of een derde partij.")
        overdue = [action for action in actions if action["due_date"] and action["due_date"] < datetime.now().strftime("%Y-%m-%d")]
        if overdue:
            risks.append(f"{len(overdue)} actiepunt(en) hebben een verstreken einddatum.")
        return {
            "customer": dict(customer), "intake": dict(intake) if intake else {}, "tasks": tasks,
            "actions": actions, "tickets": tickets, "users": int(users["total"] or 0),
            "mfa": int(users["mfa"] or 0), "licenses": int(licenses["amount"] or 0),
            "hardware": int(hardware["amount"] or 0), "done": done, "progress": progress,
            "waiting": waiting, "risks": risks,
        }

    def compose(self, customer_id: int, contact_name: str = "relatie") -> dict:
        data = self.snapshot(customer_id)
        name = data["customer"]["name"]
        lines = [
            f"Beste {contact_name or 'relatie'},", "",
            f"Hierbij ontvangt u de actuele voortgang van het IT-project voor {name}.", "",
            "Managementsamenvatting",
            "---------------------",
            f"- Totale projectvoortgang: {data['progress']}%",
            f"- Projecttaken afgerond: {data['done']} van {len(data['tasks'])}",
            f"- Openstaande actiepunten: {len(data['actions'])}",
            f"- Openstaande servicedesktickets: {len(data['tickets'])}", "",
            "Omgeving",
            "---------",
            f"- Actieve gebruikers: {data['users']}",
            f"- MFA geregistreerd: {data['mfa']} van {data['users']}",
            f"- Licenties geregistreerd: {data['licenses']}",
            f"- Hardware geregistreerd: {data['hardware']}", "",
            "Openstaande projecttaken",
            "-------------------------",
        ]
        open_tasks = [task for task in data["tasks"] if task["status"] not in self.DONE]
        if open_tasks:
            for task in open_tasks[:12]:
                owner = task["owner"] or "NOWA"
                lines.append(f"- [{task['status']}] {task['phase']} — {task['task_name']} ({owner})")
                if task["dependency"]:
                    lines.append(f"  Afhankelijkheid: {task['dependency']}")
        else:
            lines.append("- Er zijn geen openstaande projecttaken.")
        lines.extend(["", "Acties en aandachtspunten", "------------------------"])
        if data["actions"]:
            for action in data["actions"][:10]:
                due = f", uiterlijk {action['due_date']}" if action["due_date"] else ""
                lines.append(f"- [{action['priority']}] {action['title']} ({action['owner']}{due})")
        else:
            lines.append("- Er zijn geen openstaande actiepunten.")
        if data["tickets"]:
            lines.extend(["", "Openstaande servicemeldingen", "----------------------------"])
            for ticket in data["tickets"][:10]:
                lines.append(f"- {ticket['number']} [{ticket['priority']}] {ticket['subject']} — {ticket['status']}")
        lines.extend(["", "Risico's en blokkades", "---------------------"])
        lines.extend(f"- {risk}" for risk in data["risks"])
        if not data["risks"]:
            lines.append("- Op basis van de geregistreerde gegevens zijn geen directe blokkades zichtbaar.")
        lines.extend(["", "Met vriendelijke groet,", "NOWA Solutions"])
        return {
            "subject": f"Voortgangsupdate IT-project — {name}",
            "body": "\n".join(lines),
            "recipient": data["customer"]["email"],
            "progress": data["progress"],
        }

    def save(self, customer_id: int, contact_name: str = "relatie") -> int:
        report = self.compose(customer_id, contact_name)
        with self.db.transaction() as conn:
            return int(conn.execute(
                "INSERT INTO project_reports(customer_id,subject,body,progress_percent,created_by) VALUES(?,?,?,?,?)",
                (customer_id, report["subject"], report["body"], report["progress"], self.actor)).lastrowid)

    def history(self, customer_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,customer_id,report_type,subject,progress_percent,created_by,created_at FROM project_reports "
                "WHERE customer_id=? ORDER BY id DESC", (customer_id,))]

    def get(self, report_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM project_reports WHERE id=?", (report_id,)).fetchone()
        return dict(row) if row else None

    def create_mail_draft(self, customer_id: int, contact_id: int | None = None, contact_name: str = "relatie") -> int:
        if not self.mail:
            raise ValueError("De mailmodule is niet gekoppeld")
        report = self.compose(customer_id, contact_name)
        self.save(customer_id, contact_name)
        return self.mail.create_draft(customer_id, report["recipient"], report["subject"], report["body"], contact_id)

    def export_text(self, customer_id: int, contact_name: str = "relatie") -> Path:
        report = self.compose(customer_id, contact_name)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in report["subject"] if ch.isalnum() or ch in " -_").strip()
        target = self.output_dir / f"{datetime.now():%Y%m%d-%H%M}-{safe}.txt"
        target.write_text(f"Onderwerp: {report['subject']}\n\n{report['body']}", encoding="utf-8")
        self.save(customer_id, contact_name)
        return target
