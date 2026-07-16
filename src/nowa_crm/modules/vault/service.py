from __future__ import annotations

import json
import os
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

    def add(self, customer_id: int, label: str, username: str, secret: str, category: str = "Account", url: str = "") -> int:
        if self.session: self.session.require("vault.write")
        if not label.strip() or not secret:
            raise ValueError("Omschrijving en geheim zijn verplicht")
        encrypted = self._cipher.encrypt(secret.encode("utf-8"))
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO vault_entries(customer_id,category,label,username,secret,url) VALUES(?,?,?,?,?,?)",
                (customer_id, category, label.strip(), username.strip(), encrypted, url.strip()),
            )
            entry_id = int(cur.lastrowid)
            self._audit(conn, "vault.create", entry_id, customer_id, "")
        return entry_id

    def search(self, customer_id: int, query: str = "") -> list[dict]:
        if self.session: self.session.require("vault.read")
        term = f"%{query.strip()}%"
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT id,customer_id,category,label,username,url,notes,updated_at FROM vault_entries
                   WHERE customer_id=? AND (?='' OR label LIKE ? OR username LIKE ? OR url LIKE ? OR category LIKE ?)
                   ORDER BY category,label LIMIT 200""",
                (customer_id, query.strip(), term, term, term, term),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_all(self, query: str = "") -> list[dict]:
        if self.session: self.session.require("vault.read")
        term = f"%{query.strip()}%"
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT v.id,v.customer_id,c.name customer_name,c.customer_number,v.category,v.label,v.username,v.url,v.notes,v.updated_at
                   FROM vault_entries v JOIN customers c ON c.id=v.customer_id
                   WHERE ?='' OR c.name LIKE ? OR c.customer_number LIKE ? OR v.label LIKE ? OR v.username LIKE ? OR v.url LIKE ?
                   ORDER BY c.name,v.category,v.label LIMIT 300""",
                (query.strip(), term, term, term, term, term),
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

    def _audit(self, conn, action: str, entity_id: int, customer_id: int, reason: str) -> None:
        conn.execute(
            "INSERT INTO audit_events(actor,action,entity_type,entity_id,customer_id,reason,metadata) VALUES(?,?,?,?,?,?,?)",
            (self.actor, action, "vault_entry", entity_id, customer_id, reason, json.dumps({"source": "desktop"})),
        )
