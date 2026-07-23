from __future__ import annotations

from datetime import date, timedelta

from nowa_crm.core.database import Database


class DaystartService:
    PRIORITY_ORDER = {"Kritiek": 0, "Hoog": 1, "Normaal": 2, "Laag": 3}

    def __init__(self, db: Database):
        self.db = db

    def items(self, owner: str = "", priority: str = "Alle", period: str = "Actueel") -> list[dict]:
        today = date.today().isoformat()
        soon = (date.today() + timedelta(days=30)).isoformat()
        rows: list[dict] = []
        with self.db.transaction() as conn:
            self._add(rows, "Actie", conn.execute("""SELECT a.id,a.customer_id,COALESCE(c.name,'Algemeen') customer_name,
                a.title,a.priority,a.owner assigned_to,a.due_date due_at,a.status detail FROM action_items a
                LEFT JOIN customers c ON c.id=a.customer_id WHERE a.status NOT IN ('Gereed','Geannuleerd')
                AND NOT (a.source_type='Telefoon' AND EXISTS (
                    SELECT 1 FROM call_events ce WHERE ce.id=a.source_id AND ce.callback_status='open'))""").fetchall())
            self._add(rows, "E-mail", conn.execute("""SELECT m.id,m.customer_id,COALESCE(c.name,'Ongekoppeld') customer_name,
                m.subject title,m.priority,m.assigned_to,m.follow_up_at due_at,m.triage_state detail FROM mail_messages m
                LEFT JOIN customers c ON c.id=m.customer_id WHERE m.direction='inkomend' AND m.triage_state<>'afgerond'""").fetchall())
            self._add(rows, "Terugbellen", conn.execute("""SELECT MAX(ce.id) id,ce.customer_id,COALESCE(c.name,'Onbekend') customer_name,
                CASE WHEN COUNT(*)>1 THEN 'Gemiste oproepen ('||COUNT(*)||'x) · '||ce.phone_number
                     ELSE COALESCE(NULLIF(MAX(ce.subject),''),'Terugbellen · '||ce.phone_number) END title,
                MAX(ce.priority) priority,MAX(ce.assigned_to) assigned_to,MIN(ce.callback_due) due_at,
                CASE WHEN COUNT(*)>1 THEN COUNT(*)||' oproepen wachten op terugbellen' ELSE 'Terugbellen vereist' END detail
                FROM call_events ce LEFT JOIN customers c ON c.id=ce.customer_id WHERE ce.callback_status='open'
                GROUP BY ce.customer_id,ce.normalized_number,date(ce.callback_due)""").fetchall())
            self._add(rows, "Ticket", conn.execute("""SELECT t.id,t.customer_id,c.name customer_name,t.number||' · '||t.subject title,
                t.priority,t.owner assigned_to,t.sla_due_at due_at,t.status detail FROM service_tickets t JOIN customers c ON c.id=t.customer_id
                WHERE t.status NOT IN ('Opgelost','Gesloten') AND (t.priority IN ('Hoog','Kritiek') OR t.sla_due_at='' OR datetime(t.sla_due_at)<=datetime('now','localtime','+8 hours'))""").fetchall())
            self._add(rows, "Offerte", conn.execute("""SELECT p.id,p.customer_id,c.name customer_name,p.number||' · '||p.title title,
                'Normaal' priority,'' assigned_to,date(p.updated_at,'+7 day') due_at,p.status detail FROM proposals p JOIN customers c ON c.id=p.customer_id
                WHERE p.status='verzonden' AND datetime(p.updated_at)<=datetime('now','localtime','-7 day')""").fetchall())
            self._add(rows, "Licentie", conn.execute("""SELECT l.id,l.customer_id,c.name customer_name,l.product||' verlengen' title,
                'Normaal' priority,'' assigned_to,l.renewal_date due_at,'Verlengdatum' detail FROM customer_licenses l JOIN customers c ON c.id=l.customer_id
                WHERE l.renewal_date<>'' AND l.renewal_date<=?""", (soon,)).fetchall())
            self._add(rows, "Onderhoud", conn.execute("""SELECT m.id,m.customer_id,c.name customer_name,m.title,
                'Hoog' priority,m.owner assigned_to,m.next_due_date due_at,m.frequency detail FROM maintenance_tasks m JOIN customers c ON c.id=m.customer_id
                WHERE m.active=1 AND m.next_due_date<>'' AND m.next_due_date<=?""", (soon,)).fetchall())
            self._add(rows, "Beveiliging", conn.execute("""SELECT u.id,u.customer_id,c.name customer_name,'MFA ontbreekt: '||u.display_name title,
                'Hoog' priority,'' assigned_to,'' due_at,'Actieve gebruiker zonder MFA' detail FROM customer_users u JOIN customers c ON c.id=u.customer_id
                WHERE u.active=1 AND u.mfa_enabled=0""").fetchall())
            states = {(r["item_kind"], int(r["entity_id"])): dict(r) for r in conn.execute("SELECT * FROM daystart_states")}
        visible = []
        for item in rows:
            state = states.get((item["kind"], item["entity_id"]), {})
            if state.get("dismissed") or (state.get("snoozed_until") and state["snoozed_until"] > today):
                continue
            item["assigned_to"] = state.get("assigned_to") or item["assigned_to"]
            item["overdue"] = bool(item["due_at"] and item["due_at"][:10] < today)
            if owner.strip() and owner.lower() not in item["assigned_to"].lower():continue
            if priority != "Alle" and item["priority"] != priority:continue
            if period == "Vandaag" and item["due_at"][:10] not in ("", today):continue
            if period == "Te laat" and not item["overdue"]:continue
            visible.append(item)
        return sorted(visible, key=lambda x: (not x["overdue"], self.PRIORITY_ORDER.get(x["priority"], 9), x["due_at"] or "9999", x["kind"], x["entity_id"]))

    @staticmethod
    def _add(target: list[dict], kind: str, rows) -> None:
        for row in rows:
            item = dict(row);item["kind"] = kind;item["entity_id"] = int(item.pop("id"));target.append(item)

    def _save_state(self, kind: str, entity_id: int, assigned_to: str | None = None,
                    snoozed_until: str | None = None, dismissed: int | None = None) -> None:
        with self.db.transaction() as conn:
            current = conn.execute("SELECT * FROM daystart_states WHERE item_kind=? AND entity_id=?", (kind, entity_id)).fetchone()
            owner = assigned_to if assigned_to is not None else (current["assigned_to"] if current else "")
            snooze = snoozed_until if snoozed_until is not None else (current["snoozed_until"] if current else "")
            done = dismissed if dismissed is not None else (current["dismissed"] if current else 0)
            conn.execute("""INSERT INTO daystart_states(item_kind,entity_id,assigned_to,snoozed_until,dismissed)
                VALUES(?,?,?,?,?) ON CONFLICT(item_kind,entity_id) DO UPDATE SET assigned_to=excluded.assigned_to,
                snoozed_until=excluded.snoozed_until,dismissed=excluded.dismissed,updated_at=CURRENT_TIMESTAMP""",
                (kind,entity_id,owner,snooze,done))

    def assign(self, kind: str, entity_id: int, owner: str) -> None:self._save_state(kind,entity_id,assigned_to=owner.strip())
    def snooze(self, kind: str, entity_id: int, until: str) -> None:
        try:date.fromisoformat(until)
        except ValueError:raise ValueError("Uitsteldatum moet jjjj-mm-dd zijn.")
        self._save_state(kind,entity_id,snoozed_until=until)
    def dismiss(self, kind: str, entity_id: int) -> None:self._save_state(kind,entity_id,dismissed=1)

    def summary(self) -> dict:
        items=self.items();return {"total":len(items),"overdue":sum(x["overdue"] for x in items),
            "urgent":sum(x["priority"] in ("Hoog","Kritiek") for x in items),"customers":len({x["customer_id"] for x in items if x["customer_id"]})}
