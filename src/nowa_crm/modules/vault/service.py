from __future__ import annotations

import json
import os
import csv
from pathlib import Path

from cryptography.fernet import Fernet

from nowa_crm.core.database import Database
from nowa_crm.core.auth import Session


class VaultService:
    def __init__(self, db: Database, key_path: Path, actor: str, session: Session | None = None):
        self.db, self.actor, self.session = db, actor, session
        self._cipher = Fernet(self._load_key(key_path))

    @staticmethod
    def _load_key(path: Path) -> bytes:
        if path.exists():
            return path.read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        path.write_bytes(key)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    def add(self, customer_id: int, label: str, username: str, secret: str, category: str = "Account", url: str = "", group_path: str = "", host: str = "", notes: str = "") -> int:
        if self.session: self.session.require("vault.write")
        if not label.strip() or not secret:
            raise ValueError("Omschrijving en geheim zijn verplicht")
        encrypted = self._cipher.encrypt(secret.encode("utf-8"))
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO vault_entries(customer_id,category,label,username,secret,url,group_path,host,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                (customer_id, category, label.strip(), username.strip(), encrypted, url.strip(), group_path.strip(), host.strip(), notes.strip()),
            )
            entry_id = int(cur.lastrowid)
            self._audit(conn, "vault.create", entry_id, customer_id, "")
        return entry_id

    def search(self, customer_id: int, query: str = "") -> list[dict]:
        if self.session: self.session.require("vault.read")
        term = f"%{query.strip()}%"
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT id,customer_id,category,label,username,url,group_path,host,notes,updated_at FROM vault_entries
                   WHERE customer_id=? AND (?='' OR label LIKE ? OR username LIKE ? OR url LIKE ? OR category LIKE ? OR group_path LIKE ? OR host LIKE ?)
                   ORDER BY category,label LIMIT 200""",
                (customer_id, query.strip(), term, term, term, term, term, term),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_all(self, query: str = "") -> list[dict]:
        if self.session: self.session.require("vault.read")
        term = f"%{query.strip()}%"
        phone_digits = "".join(ch for ch in query if ch.isdigit())
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT v.id,v.customer_id,c.name customer_name,c.customer_number,c.phone customer_phone,v.category,v.label,v.username,v.url,v.group_path,v.host,v.notes,v.updated_at
                   FROM vault_entries v JOIN customers c ON c.id=v.customer_id
                   WHERE ?='' OR c.name LIKE ? OR c.customer_number LIKE ? OR
                   (?!='' AND REPLACE(REPLACE(REPLACE(REPLACE(c.phone,' ',''),'-',''),'(', ''),')','') LIKE ?) OR
                   v.label LIKE ? OR v.username LIKE ? OR v.url LIKE ? OR v.group_path LIKE ? OR v.host LIKE ?
                   ORDER BY c.name,v.category,v.label LIMIT 300""",
                (query.strip(), term, term, phone_digits, f"%{phone_digits}%", term, term, term, term, term),
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self.db.transaction() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM vault_entries").fetchone()[0])

    def delete(self, entry_id: int, reason: str) -> None:
        if self.session: self.session.require("vault.write")
        if len(reason.strip()) < 5:
            raise ValueError("Leg kort vast waarom dit gegeven wordt verwijderd")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT customer_id FROM vault_entries WHERE id=?", (entry_id,)).fetchone()
            if not row:
                raise KeyError(entry_id)
            self._audit(conn, "vault.delete", entry_id, int(row["customer_id"]), reason.strip())
            conn.execute("DELETE FROM vault_entries WHERE id=?", (entry_id,))

    def reveal(self, entry_id: int, reason: str) -> str:
        if self.session: self.session.require("vault.read")
        if len(reason.strip()) < 5:
            raise ValueError("Leg kort vast waarom dit gegeven wordt opgevraagd")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT customer_id,secret FROM vault_entries WHERE id=?", (entry_id,)).fetchone()
            if not row:
                raise KeyError(entry_id)
            self._audit(conn, "vault.reveal", entry_id, int(row["customer_id"]), reason.strip())
            return self._cipher.decrypt(row["secret"]).decode("utf-8")

    def import_keepass_csv(self, customer_id: int, path: Path) -> int:
        if self.session: self.session.require("vault.write")
        imported = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                normalized = {str(k).strip().lower(): (v or "") for k, v in row.items()}
                label = normalized.get("title") or normalized.get("name") or normalized.get("omschrijving")
                secret = normalized.get("password") or normalized.get("wachtwoord")
                if not label or not secret:
                    continue
                group = normalized.get("group") or normalized.get("groep") or ""
                category = self._category_from(group, label)
                self.add(customer_id, label, normalized.get("username") or normalized.get("gebruikersnaam") or "", secret,
                         category, normalized.get("url") or "", group, normalized.get("host") or "", normalized.get("notes") or normalized.get("notities") or "")
                imported += 1
        return imported

    @staticmethod
    def _category_from(group: str, label: str) -> str:
        value = f"{group} {label}".lower()
        for needle, category in (("microsoft", "Microsoft 365"), ("network", "Netwerk"), ("netwerk", "Netwerk"),
                                 ("domain", "Domein"), ("domein", "Domein"), ("hosting", "Hosting"),
                                 ("device", "Apparaat"), ("apparaat", "Apparaat")):
            if needle in value: return category
        return "Account"

    def _audit(self, conn, action: str, entity_id: int, customer_id: int, reason: str) -> None:
        conn.execute(
            "INSERT INTO audit_events(actor,action,entity_type,entity_id,customer_id,reason,metadata) VALUES(?,?,?,?,?,?,?)",
            (self.actor, action, "vault_entry", entity_id, customer_id, reason, json.dumps({"source": "desktop"})),
        )
