from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nowa_crm.core.database import Database
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService


class IntegrationService:
    PROVIDERS = ("outlook", "coligo")

    def __init__(self, db: Database, mail: MailService, telephony: TelephonyService, actor: str):
        self.db, self.mail, self.telephony, self.actor = db, mail, telephony, actor

    def settings(self, provider: str) -> dict:
        self._validate(provider)
        with self.db.transaction() as conn:
            row = conn.execute("SELECT enabled,settings_json,updated_at FROM integration_settings WHERE provider=?",
                               (provider,)).fetchone()
        if not row:
            return {"provider": provider, "enabled": False, "settings": {}, "updated_at": ""}
        try: settings = json.loads(row["settings_json"])
        except (TypeError, json.JSONDecodeError): settings = {}
        return {"provider": provider, "enabled": bool(row["enabled"]), "settings": settings, "updated_at": row["updated_at"]}

    def save(self, provider: str, enabled: bool, settings: dict | None = None) -> None:
        self._validate(provider)
        safe = self._safe_settings(provider, settings or {})
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO integration_settings(provider,enabled,settings_json,updated_at)
                VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(provider) DO UPDATE SET enabled=excluded.enabled,
                settings_json=excluded.settings_json,updated_at=CURRENT_TIMESTAMP""",
                (provider, int(enabled), json.dumps(safe, ensure_ascii=False)))
        self.log(provider, "instellingen", "actief" if enabled else "uitgeschakeld", True)

    def status(self) -> list[dict]:
        result = []
        for provider in self.PROVIDERS:
            item = self.settings(provider)
            item["state"] = "Actief" if item["enabled"] else "Niet actief"
            result.append(item)
        return result

    def ingest_coligo(self, phone_number: str, external_id: str = "", display_name: str = "") -> dict:
        if not self.settings("coligo")["enabled"]:
            raise ValueError("Schakel de Coligo-koppeling eerst in.")
        call_id = self.telephony.register_call(phone_number, "inkomend", external_id)
        call = self.telephony.get(call_id)
        detail = f"{phone_number} · {call['customer_name']}"
        if display_name: detail += f" · {display_name}"
        self.log("coligo", "inkomend_gesprek", detail, True, "call", call_id)
        return call

    def prepare_outlook(self, message_id: int):
        if not self.settings("outlook")["enabled"]:
            raise ValueError("Schakel de Outlook-koppeling eerst in.")
        path = self.mail.export_eml(message_id)
        self.log("outlook", "mail_overgedragen", path.name, True, "mail", message_id)
        return path

    def sync_outlook_folder(self) -> dict:
        settings=self.settings("outlook")
        if not settings["enabled"]:raise ValueError("Schakel de Outlook-koppeling eerst in.")
        folder=settings["settings"].get("folder_path","")
        if not folder:raise ValueError("Kies eerst een lokale Outlook-importmap.")
        result=self.mail.import_folder(Path(folder))
        self.log("outlook","map_ingelezen",f"{result['imported']} nieuw · {result['linked']} gekoppeld · {result['unlinked']} ongekoppeld · {result['duplicates']} dubbel",result["errors"]==0)
        return result

    def latest_draft(self) -> dict | None:
        rows = self.mail.list_messages()
        for row in rows:
            if row["status"] in ("concept", "klaar") and row["direction"] == "uitgaand":
                return row
        return None

    def log(self, provider: str, action: str, detail: str = "", successful: bool = True,
            entity_type: str = "", entity_id: int | None = None) -> int:
        with self.db.transaction() as conn:
            return int(conn.execute("""INSERT INTO integration_events
                (provider,action,detail,successful,entity_type,entity_id,actor)
                VALUES(?,?,?,?,?,?,?)""",(provider,action,detail,int(successful),entity_type,entity_id,self.actor)).lastrowid)

    def events(self, limit: int = 250) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM integration_events ORDER BY occurred_at DESC,id DESC LIMIT ?", (limit,))]

    @staticmethod
    def _safe_settings(provider: str, settings: dict) -> dict:
        allowed = {"outlook": {"mode", "mailbox_address", "sender_address", "folder_path"}, "coligo": {"mode", "line_name"}}[provider]
        return {key: str(value).strip() for key, value in settings.items() if key in allowed}

    @classmethod
    def _validate(cls, provider: str):
        if provider not in cls.PROVIDERS: raise ValueError("Onbekende koppeling")
