from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

from nowa_crm.core.auth import AuthService
from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir


class MultiUserService:
    ROLES={"administrator":"Beheerder","sales":"Verkoop","service":"Servicedesk","viewer":"Alleen lezen"}

    def __init__(self, db: Database, root: Path | None = None):
        self.db=db;self.root=root or data_dir();self.config_path=self.root/"multiuser.json";self.auth=AuthService(db)

    def settings(self) -> dict:
        defaults={"mode":"local","host":"","port":5432,"database":"nowa_crm","tls":True,"shared_documents":""}
        if not self.config_path.exists():return defaults
        try:defaults.update(json.loads(self.config_path.read_text(encoding="utf-8")))
        except (OSError,ValueError,TypeError):pass
        return defaults

    def save(self, host: str, port: int, database: str, tls: bool, shared_documents: str = "") -> None:
        if not host.strip():raise ValueError("Vul de naam of het IP-adres van de CRM-server in.")
        if not 1<=int(port)<=65535:raise ValueError("De serverpoort is ongeldig.")
        if not database.strip():raise ValueError("Vul de naam van de centrale database in.")
        folder=Path(shared_documents) if shared_documents.strip() else None
        if folder and not folder.exists():raise ValueError("De gedeelde documentenmap bestaat niet.")
        value={"mode":"server-ready","host":host.strip(),"port":int(port),"database":database.strip(),
               "tls":bool(tls),"shared_documents":str(folder) if folder else "","updated_at":datetime.now().isoformat(timespec="seconds")}
        self.root.mkdir(parents=True,exist_ok=True);self.config_path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding="utf-8")

    def test_server(self, host: str, port: int, timeout: float = 3.0) -> dict:
        started=datetime.now()
        try:
            with socket.create_connection((host.strip(),int(port)),timeout=timeout):pass
            return {"reachable":True,"milliseconds":int((datetime.now()-started).total_seconds()*1000),
                    "detail":"Serverpoort bereikbaar. Database-aanmelding wordt in de serverrelease geactiveerd."}
        except OSError as exc:
            return {"reachable":False,"milliseconds":0,"detail":f"Server niet bereikbaar: {exc}"}

    def readiness(self) -> dict:
        settings=self.settings();path=self.db.path.resolve();network=self._network_path(path)
        with self.db.transaction() as conn:
            tables=int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
            users=int(conn.execute("SELECT COUNT(*) FROM app_users WHERE active=1").fetchone()[0])
            customers=int(conn.execute("SELECT COUNT(*) FROM customers WHERE active=1").fetchone()[0])
        issues=[]
        if network:issues.append("De actieve SQLite-database staat op een netwerkpad. Verplaats deze terug naar lokale opslag.")
        if users<2:issues.append("Maak voor multi-usergebruik minimaal een tweede persoonlijk account aan.")
        if not settings["host"]:issues.append("De centrale CRM-server is nog niet ingesteld.")
        return {"ready":not issues,"issues":issues,"database_path":str(path),"network_path":network,
                "tables":tables,"users":users,"customers":customers,"settings":settings}

    def migration_snapshot(self) -> dict:
        backup=self.db.backup("voor-multi-user-migratie")
        manifest=backup.with_suffix(".json")
        status=self.readiness()
        manifest.write_text(json.dumps({"created_at":datetime.now().isoformat(timespec="seconds"),
            "source_database":str(self.db.path),"backup":str(backup),"customers":status["customers"],
            "tables":status["tables"],"contains_customer_data":True,
            "warning":"Alleen invoeren op de eigen beveiligde NOWA CRM-server; nooit uploaden naar GitHub."},
            indent=2,ensure_ascii=False),encoding="utf-8")
        return {"backup":backup,"manifest":manifest}

    def users(self) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("""SELECT id,username,display_name,role,active,
                COALESCE(last_login_at,'') last_login_at FROM app_users ORDER BY active DESC,display_name""")]

    def create_user(self, username: str, name: str, password: str, role: str) -> int:
        return self.auth.create_user(username,name,password,role)

    def set_user_active(self, user_id: int, active: bool) -> None:
        with self.db.transaction() as conn:
            if not conn.execute("SELECT 1 FROM app_users WHERE id=?",(user_id,)).fetchone():raise KeyError(user_id)
            if not active and int(conn.execute("SELECT COUNT(*) FROM app_users WHERE active=1 AND role='administrator'").fetchone()[0])<=1:
                role=conn.execute("SELECT role FROM app_users WHERE id=?",(user_id,)).fetchone()["role"]
                if role=="administrator":raise ValueError("De laatste actieve beheerder kan niet worden uitgeschakeld.")
            conn.execute("UPDATE app_users SET active=? WHERE id=?",(int(active),user_id))

    @staticmethod
    def _network_path(path: Path) -> bool:
        text=str(path)
        if text.startswith(("\\\\","//")):return True
        try:
            import ctypes
            root=path.drive+"\\"
            return bool(root and ctypes.windll.kernel32.GetDriveTypeW(root)==4)
        except (AttributeError,OSError):return False
