from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class GoogleCalendar:
    SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

    def __init__(self, db):
        self.db = db
        self.token_path = db.path.parent / "google-calendar.token"
        self.key_path = db.path.parent / "google-calendar.key"

    def connect(self, client_config: Path) -> str:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise RuntimeError("Google Agenda-onderdelen ontbreken in deze installatie.") from exc
        if not client_config.is_file():
            raise ValueError("Selecteer het OAuth-clientbestand dat je bij Google hebt gedownload.")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_config), self.SCOPES)
        credentials = flow.run_local_server(port=0, open_browser=True, prompt="consent")
        self.token_path.write_bytes(self._cipher().encrypt(credentials.to_json().encode("utf-8")))
        return credentials.expiry.isoformat(timespec="minutes") if credentials.expiry else "verbonden"

    def disconnect(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()

    def connected(self) -> bool:
        return self.token_path.is_file()

    def sync_actions(self, actions: list[dict], calendar_id: str = "primary", include_details: bool = False) -> dict:
        service = self._service()
        result = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
        for action in actions:
            if not action.get("due_date") and not action.get("reminder_at"):
                result["skipped"] += 1
                continue
            try:
                body = self._event_body(action,include_details)
                with self.db.transaction() as conn:
                    link = conn.execute(
                        "SELECT external_event_id FROM calendar_event_links WHERE provider='google_calendar' AND action_id=?",
                        (action["id"],)).fetchone()
                if link:
                    service.events().update(calendarId=calendar_id, eventId=link["external_event_id"], body=body).execute()
                    result["updated"] += 1
                else:
                    event = service.events().insert(calendarId=calendar_id, body=body).execute()
                    with self.db.transaction() as conn:
                        conn.execute("""INSERT INTO calendar_event_links(provider,action_id,external_event_id,calendar_id)
                            VALUES('google_calendar',?,?,?)""",(action["id"],event["id"],calendar_id))
                    result["created"] += 1
            except Exception:
                result["errors"] += 1
        return result

    def _service(self):
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Google Agenda-onderdelen ontbreken in deze installatie.") from exc
        if not self.token_path.is_file():
            raise ValueError("Verbind eerst met Google Agenda.")
        try:
            payload=self._cipher().decrypt(self.token_path.read_bytes()).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValueError("De lokale Google-inlog kan niet worden gelezen. Verbind opnieuw.") from exc
        credentials=Credentials.from_authorized_user_info(json.loads(payload),self.SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_path.write_bytes(self._cipher().encrypt(credentials.to_json().encode("utf-8")))
        return build("calendar","v3",credentials=credentials,cache_discovery=False)

    @staticmethod
    def _event_body(action: dict, include_details: bool = False) -> dict:
        reminder=(action.get("reminder_at") or "").strip()
        due=(action.get("due_date") or "").strip()
        if reminder:
            start=datetime.fromisoformat(reminder);end=start+timedelta(minutes=30)
            timing={"start":{"dateTime":start.isoformat(),"timeZone":"Europe/Amsterdam"},
                    "end":{"dateTime":end.isoformat(),"timeZone":"Europe/Amsterdam"}}
        else:
            day=datetime.fromisoformat(due).date();timing={"start":{"date":day.isoformat()},
                "end":{"date":(day+timedelta(days=1)).isoformat()}}
        description="\n".join(part for part in (
            f"Klant: {action.get('customer_name','')}" if action.get("customer_name") else "",
            f"Toegewezen: {action.get('owner','')}" if action.get("owner") else "",
            action.get("notes",""),"Aangemaakt vanuit NOWA CRM") if part)
        return {"summary":(action.get("title") or "NOWA CRM-actie") if include_details else "NOWA CRM-actie",
                "description":description if include_details else "Details blijven lokaal in NOWA CRM.",**timing}

    def _cipher(self) -> Fernet:
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
        return Fernet(self.key_path.read_bytes())
