from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nowa_crm.core.auth import AuthService
from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir
from nowa_crm.core.central_server import CentralDatabaseServer, generate_access_key
from nowa_crm.core.remote_database import RemoteDatabase

_SERVER: CentralDatabaseServer | None = None


class MultiUserService:
    ROLES={"administrator":"Beheerder","sales":"Verkoop","service":"Servicedesk","viewer":"Alleen lezen"}

    def __init__(self, db: Database, root: Path | None = None):
        self.db=db;self.root=root or data_dir();self.config_path=self.root/"multiuser.json";self.auth=AuthService(db)

    def settings(self) -> dict:
        defaults={"mode":"local","host":"","port":5088,"database":"nowa_crm","tls":True,"shared_documents":"","access_key":"","server_enabled":False}
        if not self.config_path.exists():return defaults
        try:defaults.update(json.loads(self.config_path.read_text(encoding="utf-8")))
        except (OSError,ValueError,TypeError):pass
        return defaults

    def save(self, host: str, port: int, database: str, tls: bool, shared_documents: str = "", access_key: str = "", server_enabled: bool = False, mode: str = "server-ready") -> None:
        if not host.strip():raise ValueError("Vul de naam of het IP-adres van de CRM-server in.")
        if not 1<=int(port)<=65535:raise ValueError("De serverpoort is ongeldig.")
        if not database.strip():raise ValueError("Vul de naam van de centrale database in.")
        folder=Path(shared_documents) if shared_documents.strip() else None
        if folder and not folder.exists():raise ValueError("De gedeelde documentenmap bestaat niet.")
        current=self.settings();key=access_key.strip() or current.get("access_key") or generate_access_key()
        value={"mode":mode,"host":host.strip(),"port":int(port),"database":database.strip(),
               "tls":True,"shared_documents":str(folder) if folder else "","access_key":key,
               "server_enabled":bool(server_enabled),"updated_at":datetime.now().isoformat(timespec="seconds")}
        self.root.mkdir(parents=True,exist_ok=True);self.config_path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding="utf-8")

    def test_server(self, host: str, port: int, timeout: float = 3.0, access_key: str = "") -> dict:
        started=datetime.now()
        try:
            key=access_key.strip() or self.settings().get("access_key","")
            if not key:raise ValueError("Vul eerst de toegangssleutel in.")
            result=RemoteDatabase(host.strip(),int(port),key).health()
            return {"reachable":True,"milliseconds":int((datetime.now()-started).total_seconds()*1000),
                    "detail":f"Centrale database verbonden · {result['customers']} klanten · {result['users']} gebruikers"}
        except (OSError,ConnectionError,ValueError) as exc:
            return {"reachable":False,"milliseconds":0,"detail":f"Server niet bereikbaar: {exc}"}

    def start_server(self, host: str, port: int, access_key: str) -> dict:
        global _SERVER
        if getattr(self.db,"is_remote",False):raise ValueError("Een centrale werkplek kan niet zelf als server optreden.")
        if _SERVER:_SERVER.stop()
        _SERVER=CentralDatabaseServer(self.db,host,int(port),access_key);_SERVER.start()
        return {"running":True,"host":host,"port":int(port)}

    def stop_server(self) -> None:
        global _SERVER
        if _SERVER:_SERVER.stop();_SERVER=None

    def activate_client(self, active: bool) -> None:
        settings=self.settings();settings["mode"]="central" if active else "local"
        settings["updated_at"]=datetime.now().isoformat(timespec="seconds")
        self.root.mkdir(parents=True,exist_ok=True)
        self.config_path.write_text(json.dumps(settings,indent=2,ensure_ascii=False),encoding="utf-8")

    def migrate_to_server(self) -> dict:
        if getattr(self.db,"is_remote",False):raise ValueError("Deze werkplek gebruikt de centrale database al.")
        settings=self.settings()
        if not settings.get("access_key"):raise ValueError("Stel eerst een toegangssleutel in.")
        snapshot=self.migration_snapshot()
        result=RemoteDatabase(settings["host"],settings["port"],settings["access_key"]).import_sqlite(snapshot["backup"])
        return {**result,"snapshot":snapshot["backup"]}

    def readiness(self) -> dict:
        settings=self.settings();remote=bool(getattr(self.db,"is_remote",False));path=self.db.path if remote else self.db.path.resolve();network=False if remote else self._network_path(path)
        with self.db.transaction() as conn:
            tables=int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
            users=int(conn.execute("SELECT COUNT(*) FROM app_users WHERE active=1").fetchone()[0])
            customers=int(conn.execute("SELECT COUNT(*) FROM customers WHERE active=1").fetchone()[0])
        issues=[]
        if network:issues.append("De actieve SQLite-database staat op een netwerkpad. Verplaats deze terug naar lokale opslag.")
        if users<2:issues.append("Maak voor multi-usergebruik minimaal een tweede persoonlijk account aan.")
        if not settings["host"]:issues.append("De centrale CRM-server is nog niet ingesteld.")
        return {"ready":not issues,"issues":issues,"database_path":str(path),"network_path":network,"remote":remote,
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
