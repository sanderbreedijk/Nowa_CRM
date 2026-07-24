from __future__ import annotations

import base64
import hashlib
import json
import secrets
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

from nowa_crm.core.database import Database
from cryptography.fernet import Fernet


def _pack(value):
    if isinstance(value,bytes):return {"__bytes__":base64.b64encode(value).decode("ascii")}
    return value


def _unpack(value):
    if isinstance(value,dict) and set(value)=={"__bytes__"}:return base64.b64decode(value["__bytes__"])
    return value


class CentralDatabaseServer:
    def __init__(self, database: Database, host: str, port: int, access_key: str):
        self.database=database;self.host=host;self.port=int(port);self.access_key=access_key
        self.fernet=Fernet(base64.urlsafe_b64encode(hashlib.sha256(access_key.encode()).digest()))
        self.authorization=hashlib.sha256(("nowa:"+access_key).encode()).hexdigest()
        self.transactions={};self.lock=threading.RLock();self.transaction_gate=threading.Lock()
        self.httpd=None;self.thread=None

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.database.migrate();owner=self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                try:
                    if self.headers.get("Authorization")!=f"NOWA {owner.authorization}":
                        return self.reply(401,{"error":"Ongeldige toegangssleutel."})
                    length=int(self.headers.get("Content-Length","0"))
                    try:payload=json.loads(owner.fernet.decrypt(self.rfile.read(length)).decode("utf-8"))
                    except InvalidToken: return self.reply(401,{"error":"De versleutelde verbinding kon niet worden gecontroleerd."})
                    endpoint=self.path.rstrip("/").split("/")[-1]
                    result=owner.dispatch(endpoint,payload)
                    self.reply(200,result)
                except Exception as exc:
                    self.reply(400,{"error":str(exc)})
            def reply(self,status,payload):
                body=owner.fernet.encrypt(json.dumps(payload,ensure_ascii=False).encode("utf-8"))
                self.send_response(status);self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)

        self.httpd=ThreadingHTTPServer((self.host,self.port),Handler)
        self.thread=threading.Thread(target=self.httpd.serve_forever,name="NOWA-Centrale-Database",daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd:self.httpd.shutdown();self.httpd.server_close()
        with self.lock:
            for conn in self.transactions.values():
                try:conn.rollback();conn.close()
                except Exception:pass
            self.transactions.clear()
        self.httpd=None;self.thread=None

    def dispatch(self,endpoint: str,payload: dict) -> dict:
        if endpoint=="health":
            with self.database.transaction() as conn:
                users=conn.execute("SELECT COUNT(*) FROM app_users WHERE active=1").fetchone()[0]
                customers=conn.execute("SELECT COUNT(*) FROM customers WHERE active=1").fetchone()[0]
            return {"status":"ok","users":users,"customers":customers,"server_time":datetime.now().isoformat(timespec="seconds")}
        if endpoint=="vault-key":
            key_path=self.database.path.parent/"vault.key"
            if not key_path.exists():key_path.write_bytes(Fernet.generate_key())
            return {"key":base64.b64encode(key_path.read_bytes()).decode("ascii")}
        if endpoint=="backup":
            backup=self.database.backup(str(payload.get("label") or "werkplek"))
            try:return {"database":base64.b64encode(backup.read_bytes()).decode("ascii")}
            finally:backup.unlink(missing_ok=True)
        if endpoint=="begin":
            if not self.transaction_gate.acquire(timeout=20):
                raise RuntimeError("De centrale database is tijdelijk bezet. Probeer het opnieuw.")
            try:
                tx=uuid.uuid4().hex;conn=self.database.connect();conn.execute("BEGIN")
                with self.lock:self.transactions[tx]=conn
                return {"transaction_id":tx}
            except Exception:
                self.transaction_gate.release();raise
        if endpoint=="finish":
            with self.lock:conn=self.transactions.pop(payload["transaction_id"],None)
            if not conn:raise ValueError("De databasesessie is verlopen.")
            try:conn.commit() if payload.get("commit") else conn.rollback()
            finally:conn.close();self.transaction_gate.release()
            return {"ok":True}
        if endpoint in ("execute","executemany"):
            with self.lock:
                conn=self.transactions.get(payload.get("transaction_id"))
                if not conn:raise ValueError("De databasesessie is verlopen.")
                parameters=payload.get("parameters",[])
                if endpoint=="execute":cursor=conn.execute(payload["sql"],tuple(_unpack(v) for v in parameters))
                else:cursor=conn.executemany(payload["sql"],[tuple(_unpack(v) for v in row) for row in parameters])
                columns=[item[0] for item in cursor.description] if cursor.description else []
                rows=[[_pack(value) for value in row] for row in cursor.fetchall()] if columns else []
                return {"columns":columns,"rows":rows,"lastrowid":cursor.lastrowid,"rowcount":cursor.rowcount}
        if endpoint=="import":return self._import_database(payload)
        raise ValueError("Onbekende serveropdracht.")

    def _import_database(self,payload: dict) -> dict:
        with self.lock:
            if self.transactions:raise RuntimeError("Migratie kan niet terwijl gebruikers actief zijn.")
            raw=base64.b64decode(payload["database"]);target=self.database.path
            temporary=target.with_suffix(".import.sqlite3");temporary.write_bytes(raw)
            try:
                with sqlite3.connect(f"file:{temporary}?mode=ro",uri=True) as conn:
                    required={"customers","app_users","schema_versions"}
                    found={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not required<=found:raise ValueError("Dit is geen geldige NOWA CRM-database.")
                backup=self.database.backup("voor-centrale-import")
                for suffix in ("-wal","-shm"):
                    Path(str(target)+suffix).unlink(missing_ok=True)
                target.unlink(missing_ok=True);shutil.move(temporary,target);self.database.migrate()
                return {"ok":True,"backup":str(backup)}
            finally:
                temporary.unlink(missing_ok=True)


def generate_access_key() -> str:
    return secrets.token_urlsafe(32)

