from __future__ import annotations

import json
import re
import hashlib
from html import unescape
from datetime import date, datetime, timedelta
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

from nowa_crm.core.database import Database
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService
from nowa_crm.core.phone import normalize_phone
from nowa_crm.integrations.google_calendar import GoogleCalendar


class IntegrationService:
    PROVIDERS = ("outlook", "coligo", "sip", "shomi", "google_calendar")

    def __init__(self, db: Database, mail: MailService, telephony: TelephonyService, actor: str):
        self.db, self.mail, self.telephony, self.actor = db, mail, telephony, actor
        self.google_calendar=GoogleCalendar(db)

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

    def save_sip(self, enabled: bool, settings: dict, password: str = "") -> None:
        current=self.settings("sip")["settings"]
        safe=dict(settings)
        if password:safe["password_token"]=self._cipher().encrypt(password.encode()).decode()
        elif current.get("password_token"):safe["password_token"]=current["password_token"]
        self.save("sip",enabled,safe)

    def sip_runtime_settings(self) -> dict:
        item=self.settings("sip");result=dict(item["settings"]);token=result.pop("password_token","")
        result["password"]=""
        if token:
            try:result["password"]=self._cipher().decrypt(token.encode()).decode()
            except (InvalidToken,ValueError):pass
        result["enabled"]=item["enabled"]
        return result

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

    def ingest_coligo_event(self, payload: dict) -> dict:
        """Vertaal gangbare Coligo/webhook-velden naar één lokaal gesprek."""
        phone = self._first(payload, "phone_number", "phone", "caller", "from", "remoteNumber", "remote_number")
        if not phone:
            raise ValueError("Het Coligo-event bevat geen telefoonnummer.")
        external_id = self._first(payload, "external_id", "call_id", "callId", "id")
        display_name = self._first(payload, "display_name", "displayName", "name", "line_name")
        state = self._first(payload, "state", "status", "event").lower()
        if state in {"missed", "no_answer", "unanswered", "gemist"}:
            call_id = self.telephony.mark_missed(phone, external_id)
            action = "gemiste_oproep"
        else:
            call_id = self.telephony.register_call(phone, "inkomend", external_id)
            action = "inkomend_gesprek"
        call = self.telephony.get(call_id)
        detail = f"{call['phone_number']} · {call['customer_name']}"
        if display_name:
            detail += f" · {display_name}"
        self.log("coligo", action, detail, True, "call", call_id)
        return call

    def ingest_sip_event(self, payload: dict) -> dict:
        phone=self._first(payload,"phone_number","caller","from")
        if not phone:raise ValueError("Het SIP-event bevat geen telefoonnummer.")
        call_id=self.telephony.register_call(phone,"inkomend",self._first(payload,"external_id","call_id"))
        call=self.telephony.get(call_id);name=self._first(payload,"display_name","name")
        self.log("sip","inkomend_gesprek",f"{call['phone_number']} · {call['customer_name']}"+(f" · {name}" if name else ""),True,"call",call_id)
        return call

    def ingest_shomi_event(self, payload: dict) -> dict:
        """Ontvang een flexibel Shomi-resultaat en koppel dit idempotent aan het lokale gesprek."""
        if not self.settings("shomi")["enabled"]:raise ValueError("Schakel de Shomi-koppeling eerst in.")
        analysis=payload.get("analysis") if isinstance(payload.get("analysis"),dict) else payload
        event_id=self._first(payload,"event_id","analysis_id","id","external_id") or self._first(analysis,"event_id","analysis_id","id")
        call_external=self._first(payload,"call_id","callId","external_call_id","externalId") or self._first(analysis,"call_id","callId")
        phone=self._first(payload,"phone_number","phone","caller","remote_number","remoteNumber") or self._first(analysis,"phone_number","phone","caller")
        summary=self._first(analysis,"summary","call_summary","callSummary","samenvatting")
        transcript=self._first(analysis,"transcript","transcription","full_transcript","tekst")
        if not event_id:event_id=call_external or f"{normalize_phone(phone)}-{abs(hash(summary+transcript))}"
        with self.db.transaction() as conn:
            duplicate=conn.execute("SELECT id,call_id FROM call_analyses WHERE provider='shomi' AND source_event_id=?",(event_id,)).fetchone()
            if duplicate:return {"analysis_id":int(duplicate["id"]),"call":self.telephony.get(int(duplicate["call_id"])),"actions_created":0,"duplicate":True}
            call=None
            if call_external:
                call=conn.execute("SELECT id FROM call_events WHERE external_id=?",(call_external,)).fetchone()
            if not call and phone:
                normalized=normalize_phone(phone)
                call=conn.execute("""SELECT id FROM call_events WHERE normalized_number=? ORDER BY
                    CASE WHEN ended_at IS NULL THEN 0 ELSE 1 END,started_at DESC,id DESC LIMIT 1""",(normalized,)).fetchone()
        direction=self._first(payload,"direction") or "inkomend"
        if call:call_id=int(call["id"])
        elif phone:call_id=self.telephony.register_call(phone,direction,call_external or event_id)
        else:raise ValueError("Shomi-resultaat bevat geen herkenbaar gespreks-ID of telefoonnummer.")
        call_data=self.telephony.get(call_id);points=self._shomi_points(analysis,transcript)
        with self.db.transaction() as conn:
            analysis_id=int(conn.execute("""INSERT INTO call_analyses
                (call_id,customer_id,provider,source_event_id,summary,transcript,action_points_json,raw_payload_json)
                VALUES(?,?,'shomi',?,?,?,?,?)""",(call_id,call_data.get("customer_id"),event_id,summary,transcript,
                json.dumps(points,ensure_ascii=False),json.dumps(payload,ensure_ascii=False))).lastrowid)
            if summary:
                shomi_subject=self._first(payload,"subject") or "Shomi gesprekssamenvatting"
                conn.execute("""UPDATE call_events SET notes=CASE WHEN notes='' THEN ? ELSE notes||char(10)||char(10)||? END,
                    subject=CASE WHEN subject='' THEN ? ELSE subject END,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (summary,"Shomi: "+summary,shomi_subject,call_id))
        created=0
        if call_data.get("customer_id"):
            for point in points[:10]:
                self.telephony.workspace.add_action(call_data["customer_id"],point["title"],point.get("owner") or self.actor,
                    point["due_date"],point["priority"],point.get("detail",""),"Opvolging",
                    reminder_at=point.get("reminder_at",""),source_type="Shomi",source_id=analysis_id);created+=1
        self.log("shomi","gespreksanalyse",f"{call_data['customer_name']} · {len(points)} actiepunten · {created} ingepland",True,"call",call_id)
        return {"analysis_id":analysis_id,"call":self.telephony.get(call_id),"actions_created":created,"duplicate":False}

    def ingest_shomi_email(self, subject: str, body: str, message_id: str = "") -> dict:
        """Verwerk het vaste Shomi-mailbericht zonder het originele bericht buiten de lokale database te bewaren."""
        payload=self.parse_shomi_email(subject,body,message_id,self.settings("shomi")["settings"].get("own_numbers",""))
        return self.ingest_shomi_event(payload)

    def sync_shomi_mail(self) -> dict:
        """Verwerk nog niet verwerkte Shomi-berichten uit de lokale mailmodule."""
        if not self.settings("shomi")["enabled"]:
            return {"found":0,"processed":0,"duplicates":0,"errors":0}
        result={"found":0,"processed":0,"duplicates":0,"errors":0}
        for row in self.mail.list_messages(query="shomi",queue="alle"):
            message=self.mail.get(int(row["id"]))
            sender=(message or {}).get("sender","").lower()
            if "hello@shomi.ai" not in sender and "call between" not in (message or {}).get("subject","").lower():
                continue
            result["found"]+=1
            try:
                parsed=self.ingest_shomi_email(message["subject"],message["body"],message.get("external_id",""))
                result["duplicates" if parsed["duplicate"] else "processed"]+=1
            except Exception as exc:
                result["errors"]+=1
                self.log("shomi","bericht_fout",str(exc),False,"mail",int(row["id"]))
        return result

    @classmethod
    def parse_shomi_email(cls, subject: str, body: str, message_id: str = "", own_numbers: str = "") -> dict:
        text=cls._plain_mail_text(body)
        sections=cls._shomi_sections(text)
        started=cls._parse_shomi_started(sections.get("CONVERSATIE GESTART",""),subject)
        participants=cls._phone_numbers(sections.get("DEELNEMERS",""))
        subject_match=re.search(r"(?i)call between\s+(.+?)\s+and\s+(.+?)\s+-\s+(.+)$",subject.strip())
        subject_phones=cls._phone_numbers(" ".join(subject_match.groups()[:2])) if subject_match else []
        for number in subject_phones:
            if number not in participants:participants.append(number)
        topic=(sections.get("ONDERWERP","").strip() or (subject_match.group(3).strip() if subject_match else "Shomi-gesprek"))
        report=cls._bullet_lines(sections.get("VERSLAG",""))
        followups=cls._bullet_lines(sections.get("VERVOLGACTIES",""))
        own={normalize_phone(number) for number in re.split(r"[,;\s]+",own_numbers) if normalize_phone(number)}
        remote=next((number for number in participants if normalize_phone(number) not in own),participants[-1] if participants else "")
        direction=cls._shomi_direction(report,participants,own)
        points=[cls._shomi_email_point(line,started) for line in followups]
        event_id=(message_id or "sha256:"+hashlib.sha256((subject+"\n"+text).encode("utf-8")).hexdigest()).strip()
        return {"event_id":event_id,"phone_number":remote,"direction":direction,
                "started_at":started.isoformat(timespec="seconds") if started else "",
                "subject":topic,"summary":"\n".join(f"• {line}" for line in report),
                "action_points":points,"provider":"shomi"}

    @staticmethod
    def _plain_mail_text(body: str) -> str:
        text=re.sub(r"(?is)<(script|style).*?>.*?</\1>"," ",body or "")
        text=re.sub(r"(?i)<br\s*/?>","\n",text)
        text=re.sub(r"(?i)</(p|div|li|tr|h\d)>","\n",text)
        text=re.sub(r"(?s)<[^>]+>"," ",text)
        text=unescape(text).replace("\r","")
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())

    @staticmethod
    def _shomi_sections(text: str) -> dict:
        headings=("CONVERSATIE GESTART","DEELNEMERS","ONDERWERP","VERSLAG","VERVOLGACTIES")
        pattern=r"(?im)^("+("|".join(map(re.escape,headings)))+r")\s*$"
        matches=list(re.finditer(pattern,text));result={}
        for index,match in enumerate(matches):
            end=matches[index+1].start() if index+1<len(matches) else len(text)
            value=text[match.end():end]
            value=re.split(r"(?im)^Kind regards,",value,maxsplit=1)[0].strip()
            result[match.group(1).upper()]=value
        return result

    @staticmethod
    def _bullet_lines(value: str) -> list[str]:
        lines=[];current=""
        for raw in value.splitlines():
            clean=raw.strip()
            is_bullet=bool(re.match(r"^[*•\-]\s+",clean))
            clean=re.sub(r"^[*•\-]\s*","",clean).strip(" \\")
            if not clean:continue
            if is_bullet:
                if current:lines.append(re.sub(r"\s+"," ",current).strip())
                current=clean
            elif current:current+=" "+clean
            else:current=clean
        if current:lines.append(re.sub(r"\s+"," ",current).strip())
        return lines

    @staticmethod
    def _phone_numbers(value: str) -> list[str]:
        result=[]
        for number in re.findall(r"\+\d[\d\s().-]{7,}\d",value or ""):
            clean="+"+re.sub(r"\D","",number)
            if clean not in result:result.append(clean)
        return result

    @staticmethod
    def _parse_shomi_started(value: str, subject: str) -> datetime | None:
        match=re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})\s*@\s*(\d{1,2}):(\d{2})",value)
        if match:
            day,month,year,hour,minute=map(int,match.groups());return datetime(year,month,day,hour,minute)
        match=re.match(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{1,2}):(\d{2})",subject)
        months={"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
        if match:
            day,mon,year,hour,minute=match.groups()
            if mon.lower() in months:return datetime(int(year),months[mon.lower()],int(day),int(hour),int(minute))
        return None

    @staticmethod
    def _shomi_direction(report: list[str], participants: list[str], own: set[str]) -> str:
        joined=" ".join(report).lower()
        if re.search(r"\b(de beller|caller)\b.*\b(callee|gebeld|sander)\b",joined):return "inkomend"
        if re.search(r"\b(sander|opnemer)\b.*\b(de callee|callee)\b",joined):return "uitgaand"
        if own and participants:return "uitgaand" if normalize_phone(participants[0]) in own else "inkomend"
        return "inkomend"

    @staticmethod
    def _shomi_email_point(line: str, started: datetime | None) -> dict:
        base=started or datetime.now();lower=line.lower();reminder="";due=""
        match=re.search(r"binnen\s+(?:een\s+)?(half\s+uur|uur|\d+\s+minuten?)",lower)
        if match:
            token=match.group(1);minutes=30 if token=="half uur" else 60 if token=="uur" else int(re.search(r"\d+",token).group())
            moment=base+timedelta(minutes=minutes);due=moment.date().isoformat();reminder=moment.isoformat(timespec="minutes")
        elif "morgenochtend" in lower or re.search(r"\bmorgen\b",lower):
            moment=(base+timedelta(days=1)).replace(hour=9,minute=0);due=moment.date().isoformat();reminder=moment.isoformat(timespec="minutes")
        else:
            explicit=re.search(r"(?:per|op)\s+(\d{1,2})-(\d{1,2})(?:-(\d{2,4}))?",lower)
            if explicit:
                day,month,year=explicit.groups();year=int(year) if year else base.year
                if year<100:year+=2000
                try:due=date(year,int(month),int(day)).isoformat()
                except ValueError:pass
        owner_match=re.match(r"(?:de\s+)?(.+?)(?:\s+\([^)]*\))?\s+(?:zal|gaat|haalt)\b",line,re.I)
        return {"title":line[:180],"detail":"Automatisch uit Shomi-vervolgactie",
                "owner":owner_match.group(1).strip() if owner_match else "NOWA",
                "due_date":due,"reminder_at":reminder,"priority":"Normaal"}

    def call_analysis(self, call_id: int) -> dict | None:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT * FROM call_analyses WHERE call_id=? ORDER BY received_at DESC,id DESC LIMIT 1",(call_id,)).fetchone()
        return dict(row) if row else None

    def _shomi_points(self, analysis: dict, transcript: str) -> list[dict]:
        raw=analysis.get("action_points",analysis.get("actionPoints",analysis.get("actions",analysis.get("follow_up",[]))))
        questions=analysis.get("questions",analysis.get("open_questions",[]))
        if isinstance(raw,str):raw=[line.strip(" -•\t") for line in raw.splitlines() if line.strip()]
        if isinstance(questions,str):questions=[line.strip(" -•\t") for line in questions.splitlines() if line.strip()]
        items=list(raw) if isinstance(raw,list) else []
        items += [{"title":f"Beantwoorden: {item}","priority":"Normaal"} for item in questions if isinstance(item,str)]
        if not items:
            for line in transcript.splitlines():
                clean=line.strip(" -•\t")
                if re.match(r"(?i)^(actie|todo|afspraak|vervolg|vraag)\s*:",clean) or clean.endswith("?"):items.append(clean)
        result=[]
        for item in items:
            data=item if isinstance(item,dict) else {"title":str(item)}
            title=self._first(data,"title","action","text","description","task","question").strip()
            if not title:continue
            due=self._first(data,"due_date","dueDate","deadline","date")
            result.append({"title":title[:180],"detail":self._first(data,"detail","context","notes"),
                           "due_date":self._action_due(due),"reminder_at":self._first(data,"reminder_at","reminderAt"),
                           "owner":self._first(data,"owner","assignee"),
                           "priority":self._first(data,"priority","urgency").title() or "Normaal"})
        return result

    @staticmethod
    def _action_due(value: str) -> str:
        text=(value or "").strip().lower();today=date.today()
        if not text:return ""
        if text=="vandaag":return today.isoformat()
        if text=="morgen":return (today+timedelta(days=1)).isoformat()
        match=re.search(r"\d{4}-\d{2}-\d{2}",text)
        return match.group(0) if match else ""

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
        result["shomi"]=self.sync_shomi_mail()
        self.log("outlook","map_ingelezen",f"{result['imported']} nieuw · {result['linked']} gekoppeld · {result['unlinked']} ongekoppeld · {result['duplicates']} dubbel",result["errors"]==0)
        return result

    def latest_draft(self) -> dict | None:
        rows = self.mail.list_messages()
        for row in rows:
            if row["status"] in ("concept", "klaar") and row["direction"] == "uitgaand":
                return row
        return None

    def connect_google_calendar(self) -> str:
        settings=self.settings("google_calendar")["settings"]
        path=settings.get("client_config_path","")
        if not path:raise ValueError("Kies eerst het Google OAuth-clientbestand.")
        expiry=self.google_calendar.connect(Path(path))
        self.log("google_calendar","verbonden",f"Google Agenda verbonden · token lokaal geldig tot {expiry}",True)
        return expiry

    def sync_google_calendar(self) -> dict:
        item=self.settings("google_calendar")
        if not item["enabled"]:raise ValueError("Schakel Google Agenda eerst in.")
        if not self.google_calendar.connected():raise ValueError("Verbind eerst met Google Agenda.")
        actions=self.telephony.workspace.actions(include_done=False)
        result=self.google_calendar.sync_actions(actions,item["settings"].get("calendar_id","primary") or "primary",
            item["settings"].get("include_details","")=="1")
        self.log("google_calendar","acties_gesynchroniseerd",
            f"{result['created']} nieuw · {result['updated']} bijgewerkt · {result['skipped']} zonder datum · {result['errors']} fouten",
            result["errors"]==0)
        return result

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

    def cleanup_sip_connection_noise(self) -> int:
        with self.db.transaction() as conn:
            return int(conn.execute("""DELETE FROM integration_events
                WHERE provider='sip' AND action='verbinding'""").rowcount)

    @staticmethod
    def _safe_settings(provider: str, settings: dict) -> dict:
        allowed = {"outlook": {"mode", "mailbox_address", "sender_address", "folder_path"},
                   "coligo": {"mode", "line_name", "webhook_port", "webhook_key"},
                   "sip": {"server","server_port","local_port","username","domain","transport","auto_start","password_token"},
                   "shomi": {"mode","webhook_port","webhook_key","auto_start","own_numbers"},
                   "google_calendar": {"client_config_path","calendar_id","auto_sync","include_details"}}[provider]
        return {key: str(value).strip() for key, value in settings.items() if key in allowed}

    def _cipher(self) -> Fernet:
        key_path=self.db.path.parent/"sip-monitor.key"
        if not key_path.exists():key_path.write_bytes(Fernet.generate_key())
        return Fernet(key_path.read_bytes())

    @staticmethod
    def _first(payload: dict, *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @classmethod
    def _validate(cls, provider: str):
        if provider not in cls.PROVIDERS: raise ValueError("Onbekende koppeling")
