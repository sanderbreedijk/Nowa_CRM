from __future__ import annotations

from nowa_crm.core.database import Database
from nowa_crm.modules.assets.service import CustomerAssetsService
from nowa_crm.modules.mail.service import MailService


class DocumentCenterService:
    def __init__(self, db: Database, assets: CustomerAssetsService, mail: MailService):
        self.db, self.assets, self.mail = db, assets, mail

    def profile(self) -> dict:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM organization_profile WHERE id=1").fetchone()
        return dict(row) if row else {}

    def save_profile(self, company_name: str, address: str, postal_city: str, phone: str, email: str,
                     website: str, primary_color: str, footer_text: str, logo_path: str = "") -> None:
        if not company_name.strip():
            raise ValueError("Bedrijfsnaam is verplicht")
        color = primary_color.strip().upper()
        if len(color) != 7 or not color.startswith("#"):
            raise ValueError("Gebruik een kleurcode zoals #0B2342")
        int(color[1:], 16)
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO organization_profile
                (id,company_name,address,postal_city,phone,email,website,primary_color,footer_text,logo_path,updated_at)
                VALUES(1,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET company_name=excluded.company_name,address=excluded.address,
                postal_city=excluded.postal_city,phone=excluded.phone,email=excluded.email,website=excluded.website,
                primary_color=excluded.primary_color,footer_text=excluded.footer_text,logo_path=excluded.logo_path,
                updated_at=CURRENT_TIMESTAMP""",
                (company_name.strip(), address.strip(), postal_city.strip(), phone.strip(), email.strip(),
                 website.strip(), color, footer_text.strip(), logo_path.strip()))

    def search(self, query: str = "", customer_id: int | None = None, kind: str = "Alles") -> list[dict]:
        term = f"%{query.strip()}%"
        clauses = ["(?='' OR title LIKE ? OR customer_name LIKE ? OR reference LIKE ?)"]
        values: list = [query.strip(), term, term, term]
        if customer_id is not None:
            clauses.append("customer_id=?"); values.append(customer_id)
        if kind != "Alles":
            clauses.append("kind=?"); values.append(kind)
        sql = """SELECT * FROM (
            SELECT d.id,d.customer_id,c.name customer_name,'Document' kind,d.title,
                   d.document_type status,d.original_name reference,d.created_at date
            FROM customer_documents d JOIN customers c ON c.id=d.customer_id
            UNION ALL
            SELECT p.id,p.customer_id,c.name,'Offerte',p.title,p.status,p.number,p.updated_at
            FROM proposals p JOIN customers c ON c.id=p.customer_id
            UNION ALL
            SELECT r.id,r.customer_id,c.name,'Rapportage',r.subject,
                   CAST(r.progress_percent AS TEXT)||'%','Rapport '||r.id,r.created_at
            FROM project_reports r JOIN customers c ON c.id=r.customer_id
        ) WHERE """ + " AND ".join(clauses) + " ORDER BY date DESC,id DESC LIMIT 750"
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(sql, values)]

    def templates(self) -> list[dict]:
        with self.db.transaction() as conn:
            proposal = [dict(row) | {"kind": "Offerte"} for row in conn.execute(
                "SELECT id,name,description summary FROM proposal_templates ORDER BY name")]
            mail = [dict(row) | {"kind": "E-mail"} for row in conn.execute(
                "SELECT id,name,subject_template summary,category FROM mail_templates WHERE active=1 ORDER BY category,name")]
        return proposal + mail

    def mail_template(self, template_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM mail_templates WHERE id=?", (template_id,)).fetchone()
        return dict(row) if row else None

    def document_path(self, document_id: int):
        return self.assets.document_path(document_id)

    def report_preview(self, report_id: int) -> str:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT subject,body FROM project_reports WHERE id=?", (report_id,)).fetchone()
        return f"{row['subject']}\n\n{row['body']}" if row else ""
