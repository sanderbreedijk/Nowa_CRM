from __future__ import annotations

import hashlib
import hmac
import os
import socket
from dataclasses import dataclass

from nowa_crm.core.database import Database

ROLES = {
    "administrator": frozenset({"customers.write", "proposals.write", "vault.read", "vault.write", "users.manage"}),
    "sales": frozenset({"customers.write", "proposals.write"}),
    "service": frozenset({"customers.write", "vault.read", "vault.write"}),
    "viewer": frozenset(),
}


@dataclass(frozen=True)
class Session:
    user_id: int
    username: str
    display_name: str
    role: str

    def can(self, permission: str) -> bool:
        return permission in ROLES[self.role]

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise PermissionError(f"Geen bevoegdheid voor: {permission}")


class AuthService:
    def __init__(self, db: Database): self.db = db

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)

    def has_users(self) -> bool:
        with self.db.transaction() as conn: return bool(conn.execute("SELECT 1 FROM app_users LIMIT 1").fetchone())

    def create_user(self, username: str, display_name: str, password: str, role: str) -> int:
        if role not in ROLES: raise ValueError("Onbekende rol")
        if len(username.strip()) < 3 or len(password) < 10: raise ValueError("Gebruikersnaam minimaal 3 tekens; wachtwoord minimaal 10 tekens")
        salt=os.urandom(16)
        with self.db.transaction() as conn:
            cur=conn.execute("INSERT INTO app_users(username,display_name,password_hash,password_salt,role) VALUES(?,?,?,?,?)",(username.strip(),display_name.strip() or username.strip(),self._hash(password,salt),salt,role))
            return int(cur.lastrowid)

    def authenticate(self, username: str, password: str) -> Session | None:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT * FROM app_users WHERE username=? AND active=1",(username.strip(),)).fetchone()
            valid=bool(row and hmac.compare_digest(row["password_hash"],self._hash(password,row["password_salt"])))
            conn.execute("INSERT INTO login_events(username,successful,workstation) VALUES(?,?,?)",(username.strip(),int(valid),socket.gethostname()))
            if not valid:return None
            conn.execute("UPDATE app_users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?",(row["id"],))
            return Session(int(row["id"]),row["username"],row["display_name"],row["role"])
