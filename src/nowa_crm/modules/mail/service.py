from __future__ import annotations

import mimetypes
import shutil
import hashlib
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir


class MailService:
    STATUSES = ("concept","klaar","verzonden","ontvangen","gearchiveerd")

    def __init__(self, db: Database, actor: str, root: Path | None = None):
        self.db, self.actor = db, actor
        self.root = root or data_dir()
        self.attachments_root = self.root / "mail-bijlagen"
        self.exports_root = self.root / "exports" / "mail"

    def templates(self) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("SELECT id,name,subject_template,body_template,category FROM mail_templates WHERE active=1 ORDER BY category,name")]

    def save_template(self, name: str, subject: str, body: str, category: str = "Algemeen") -> int:
        if not name.strip() or not body.strip():
            raise ValueError("Sjabloonnaam en tekst zijn verplicht")
        with self.db.transaction() as conn:
            row=conn.execute("SELECT id FROM mail_templates WHERE name=? COLLATE NOCASE",(name.strip(),)).fetchone()
            if row:
                conn.execute("UPDATE mail_templates SET subject_template=?,body_template=?,category=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (subject.strip(),body.strip(),category.strip(),row["id"]))
                return int(row["id"])
            cur=conn.execute("INSERT INTO mail_templates(name,subject_template,body_template,category) VALUES(?,?,?,?)",
                             (name.strip(),subject.strip(),body.strip(),category.strip()))
            return int(cur.lastrowid)

    def render_template(self, template_id: int, customer_id: int, contact_id: int | None = None,
                        proposal_id: int | None = None, progress: str = "") -> dict:
        with self.db.transaction() as conn:
            template=conn.execute("SELECT subject_template,body_template FROM mail_templates WHERE id=?",(template_id,)).fetchone()
            customer=conn.execute("SELECT customer_number,name,email FROM customers WHERE id=?",(customer_id,)).fetchone()
            contact=conn.execute("SELECT name,email FROM contacts WHERE id=? AND customer_id=?",(contact_id,customer_id)).fetchone() if contact_id else None
            proposal=conn.execute("SELECT number,title FROM proposals WHERE id=? AND customer_id=?",(proposal_id,customer_id)).fetchone() if proposal_id else None
        if not template or not customer:
            raise ValueError("Sjabloon of klant niet gevonden")
        values={
            "klantnaam":customer["name"],"klantnummer":customer["customer_number"],
            "contactnaam":contact["name"] if contact else "relatie",
            "offertenummer":proposal["number"] if proposal else "",
            "offertetitel":proposal["title"] if proposal else "",
            "voortgang":progress,
        }
        return {"subject":template["subject_template"].format_map(_Safe(values)),
                "body":template["body_template"].format_map(_Safe(values)),
                "recipient":contact["email"] if contact and contact["email"] else customer["email"]}

    def create_draft(self, customer_id: int, recipients: str, subject: str, body: str,
                     contact_id: int | None = None, cc: str = "", sender: str = "") -> int:
        if not recipients.strip() or not subject.strip():
            raise ValueError("Ontvanger en onderwerp zijn verplicht")
        with self.db.transaction() as conn:
            cur=conn.execute("""INSERT INTO mail_messages(customer_id,contact_id,direction,status,sender,recipients,cc,subject,body,created_by)
                VALUES(?,?,'uitgaand','concept',?,?,?,?,?,?)""",
                (customer_id,contact_id,sender.strip(),recipients.strip(),cc.strip(),subject.strip(),body,self.actor))
            return int(cur.lastrowid)

    def update_draft(self, message_id: int, recipients: str, cc: str, subject: str, body: str, status: str = "concept") -> None:
        if status not in self.STATUSES:
            raise ValueError("Ongeldige mailstatus")
        with self.db.transaction() as conn:
            conn.execute("UPDATE mail_messages SET recipients=?,cc=?,subject=?,body=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (recipients.strip(),cc.strip(),subject.strip(),body,status,message_id))

    def record_incoming(self, sender: str, recipients: str, subject: str, body: str, occurred_at: str = "") -> int:
        customer_id,contact_id=self.detect_customer(sender)
        with self.db.transaction() as conn:
            cur=conn.execute("""INSERT INTO mail_messages(customer_id,contact_id,direction,status,sender,recipients,subject,body,occurred_at,created_by)
                VALUES(?,?,'inkomend','ontvangen',?,?,?,?,?,?)""",
                (customer_id,contact_id,sender.strip(),recipients.strip(),subject.strip(),body,occurred_at or datetime.now().isoformat(timespec="seconds"),self.actor))
            return int(cur.lastrowid)

    def detect_customer(self, address: str) -> tuple[int | None,int | None]:
        email=address.strip().lower()
        domain=email.split("@",1)[1] if "@" in email else ""
        with self.db.transaction() as conn:
            contact=conn.execute("SELECT id,customer_id FROM contacts WHERE lower(email)=?",(email,)).fetchone()
            if contact:return int(contact["customer_id"]),int(contact["id"])
            customer=conn.execute("SELECT id FROM customers WHERE lower(email)=?",(email,)).fetchone()
            if customer:return int(customer["id"]),None
            if domain:
                customer=conn.execute("""SELECT id FROM customers WHERE lower(email) LIKE ?
                    OR EXISTS(SELECT 1 FROM contacts WHERE contacts.customer_id=customers.id AND lower(contacts.email) LIKE ?)
                    ORDER BY id LIMIT 1""",(f"%@{domain}",f"%@{domain}")).fetchone()
                if customer:return int(customer["id"]),None
        return None,None

    def list_messages(self, customer_id: int | None = None, query: str = "") -> list[dict]:
        term=f"%{query.strip()}%"; clauses=["(?='' OR m.subject LIKE ? OR m.recipients LIKE ? OR m.sender LIKE ? OR m.body LIKE ?)"]; values=[query.strip(),term,term,term,term]
        if customer_id is not None:clauses.append("m.customer_id=?"); values.append(customer_id)
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("""SELECT m.id,m.customer_id,COALESCE(c.name,'Ongekoppeld') customer_name,m.direction,m.status,
                m.sender,m.recipients,m.subject,m.occurred_at,m.updated_at FROM mail_messages m LEFT JOIN customers c ON c.id=m.customer_id
                WHERE """+" AND ".join(clauses)+" ORDER BY m.occurred_at DESC,m.id DESC LIMIT 500",values)]

    def get(self, message_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT * FROM mail_messages WHERE id=?",(message_id,)).fetchone()
        return dict(row) if row else None

    def add_attachment(self, message_id: int, source: Path) -> int:
        if not source.is_file():
            raise ValueError("Bijlage niet gevonden")
        folder=self.attachments_root/str(message_id); folder.mkdir(parents=True,exist_ok=True)
        stored=f"{uuid4().hex}-{source.name}"; target=folder/stored; shutil.copy2(source,target)
        relative=target.relative_to(self.root)
        with self.db.transaction() as conn:
            cur=conn.execute("INSERT INTO mail_attachments(message_id,original_name,stored_name,relative_path,size_bytes) VALUES(?,?,?,?,?)",
                             (message_id,source.name,stored,str(relative),target.stat().st_size))
            return int(cur.lastrowid)

    def _store_attachment(self, message_id: int, filename: str, payload: bytes) -> int:
        safe_name=Path(filename or "bijlage").name
        folder=self.attachments_root/str(message_id);folder.mkdir(parents=True,exist_ok=True)
        stored=f"{uuid4().hex}-{safe_name}";target=folder/stored;target.write_bytes(payload)
        relative=target.relative_to(self.root)
        with self.db.transaction() as conn:
            return int(conn.execute("INSERT INTO mail_attachments(message_id,original_name,stored_name,relative_path,size_bytes) VALUES(?,?,?,?,?)",(message_id,safe_name,stored,str(relative),len(payload))).lastrowid)

    def import_eml(self, source: Path) -> tuple[int,bool]:
        if not source.is_file() or source.suffix.lower()!=".eml":raise ValueError("Selecteer een geldig EML-bestand")
        raw=source.read_bytes();message=BytesParser(policy=policy.default).parsebytes(raw)
        external=(message.get("Message-ID") or "").strip() or "sha256:"+hashlib.sha256(raw).hexdigest()
        with self.db.transaction() as conn:
            existing=conn.execute("SELECT id FROM mail_messages WHERE external_id=?",(external,)).fetchone()
        if existing:return int(existing["id"]),False
        senders=getaddresses(message.get_all("From",[]));recipients=getaddresses(message.get_all("To",[])+message.get_all("Cc",[]))
        sender=senders[0][1] if senders else str(message.get("From", ""));recipient_text=", ".join(address for _,address in recipients if address)
        customer_id,contact_id=self.detect_customer(sender)
        if customer_id is None:
            for _,address in recipients:
                customer_id,contact_id=self.detect_customer(address)
                if customer_id is not None:break
        body=""
        preferred=message.get_body(preferencelist=("plain","html")) if message.is_multipart() else message
        if preferred:
            try:body=preferred.get_content()
            except (LookupError,UnicodeDecodeError):body=str(preferred.get_payload(decode=True) or b"",errors="replace")
        occurred=datetime.now().isoformat(timespec="seconds")
        if message.get("Date"):
            try:occurred=parsedate_to_datetime(message["Date"]).astimezone().isoformat(timespec="seconds")
            except (TypeError,ValueError,OverflowError):pass
        with self.db.transaction() as conn:
            cur=conn.execute("""INSERT INTO mail_messages(customer_id,contact_id,direction,status,sender,recipients,cc,subject,body,external_id,occurred_at,created_by,source_path)
                VALUES(?,?,'inkomend','ontvangen',?,?,?,?,?,?,?,?,?)""",(customer_id,contact_id,sender,recipient_text,str(message.get("Cc","")),str(message.get("Subject","(geen onderwerp)")),body,external,occurred,self.actor,str(source)))
            message_id=int(cur.lastrowid)
        for part in message.iter_attachments():
            payload=part.get_payload(decode=True)
            if payload:self._store_attachment(message_id,part.get_filename() or "bijlage",payload)
        return message_id,True

    def import_folder(self, folder: Path) -> dict:
        if not folder.is_dir():raise ValueError("De Outlook-importmap bestaat niet")
        result={"found":0,"imported":0,"duplicates":0,"linked":0,"unlinked":0,"errors":0}
        for source in sorted(folder.glob("*.eml")):
            result["found"]+=1
            try:
                message_id,created=self.import_eml(source)
                if not created:result["duplicates"]+=1;continue
                result["imported"]+=1
                if self.get(message_id)["customer_id"] is None:result["unlinked"]+=1
                else:result["linked"]+=1
            except Exception:result["errors"]+=1
        return result

    def link_customer(self, message_id: int, customer_id: int, contact_id: int | None = None) -> None:
        with self.db.transaction() as conn:
            if not conn.execute("SELECT 1 FROM customers WHERE id=?",(customer_id,)).fetchone():raise ValueError("Klant niet gevonden")
            conn.execute("UPDATE mail_messages SET customer_id=?,contact_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(customer_id,contact_id,message_id))

    def dossier_stats(self) -> dict:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT COUNT(*) total,SUM(customer_id IS NOT NULL) linked,SUM(customer_id IS NULL) unlinked,SUM(direction='inkomend') incoming FROM mail_messages").fetchone()
        return {key:int(row[key] or 0) for key in ("total","linked","unlinked","incoming")}

    def attachments(self, message_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("SELECT id,original_name,relative_path,size_bytes FROM mail_attachments WHERE message_id=? ORDER BY id",(message_id,))]

    def export_eml(self, message_id: int) -> Path:
        row=self.get(message_id)
        if not row:raise ValueError("Mail niet gevonden")
        message=EmailMessage(); message["To"]=row["recipients"]; message["Cc"]=row["cc"]; message["Subject"]=row["subject"]
        if row["sender"]:message["From"]=row["sender"]
        message.set_content(row["body"])
        for attachment in self.attachments(message_id):
            path=self.root/attachment["relative_path"]
            if not path.exists():continue
            mime,_=mimetypes.guess_type(path.name); maintype,subtype=(mime or "application/octet-stream").split("/",1)
            message.add_attachment(path.read_bytes(),maintype=maintype,subtype=subtype,filename=attachment["original_name"])
        self.exports_root.mkdir(parents=True,exist_ok=True)
        target=self.exports_root/f"mail-{message_id}-{_safe_filename(row['subject'])}.eml"; target.write_bytes(message.as_bytes())
        self.update_draft(message_id,row["recipients"],row["cc"],row["subject"],row["body"],"klaar")
        return target

    def mark_sent(self, message_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE mail_messages SET status='verzonden',occurred_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(message_id,))


class _Safe(dict):
    def __missing__(self,key):return ""


def _safe_filename(value: str) -> str:
    cleaned="".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value).strip("-")
    return cleaned[:60] or "concept"
