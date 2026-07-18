from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir


class SecurityService:
    def __init__(self,db: Database,output_dir: Path | None=None):
        self.db=db; self.output_dir=output_dir or data_dir()/"exports"/"beveiliging"

    def users(self,customer_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("""SELECT id,display_name,user_principal_name,department,
                license_name,mfa_enabled,active,notes,updated_at FROM customer_users WHERE customer_id=?
                ORDER BY active DESC,display_name""",(customer_id,))]

    def checks(self,customer_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            users=[dict(r) for r in conn.execute("SELECT * FROM customer_users WHERE customer_id=? AND active=1",(customer_id,))]
            licenses=int(conn.execute("SELECT COALESCE(SUM(quantity),0) FROM customer_licenses WHERE customer_id=?",(customer_id,)).fetchone()[0])
            vault=[dict(r) for r in conn.execute("SELECT id,label,username,updated_at FROM vault_entries WHERE customer_id=?",(customer_id,))]
            critical=int(conn.execute("""SELECT COUNT(*) FROM service_tickets WHERE customer_id=? AND priority='Kritiek'
                AND status NOT IN ('Opgelost','Gesloten')""",(customer_id,)).fetchone()[0])
            overdue=int(conn.execute("""SELECT COUNT(*) FROM action_items WHERE customer_id=? AND due_date!=''
                AND due_date<date('now') AND status NOT IN ('Gereed','Geannuleerd')""",(customer_id,)).fetchone()[0])
        findings=[]
        missing_mfa=[u for u in users if not u["mfa_enabled"]]
        if missing_mfa:self._add(findings,"Hoog","MFA",f"{len(missing_mfa)} actieve gebruiker(s) hebben geen MFA-registratie.","Registreer en controleer MFA.")
        missing_upn=[u for u in users if not u["user_principal_name"].strip()]
        if missing_upn:self._add(findings,"Normaal","Identiteit",f"{len(missing_upn)} actieve gebruiker(s) hebben geen UPN.","Vul de gebruikersidentiteit aan.")
        upns=[u["user_principal_name"].strip().lower() for u in users if u["user_principal_name"].strip()]
        duplicates=sorted({upn for upn in upns if upns.count(upn)>1})
        if duplicates:self._add(findings,"Kritiek","Identiteit",f"Dubbele UPN gevonden: {', '.join(duplicates)}.","Corrigeer de dubbele gebruikersidentiteit.")
        if licenses<len(users):self._add(findings,"Hoog","Licenties",f"{len(users)-licenses} actieve gebruiker(s) hebben mogelijk geen licentie.","Controleer licentietoewijzing.")
        if licenses>len(users):self._add(findings,"Laag","Licenties",f"{licenses-len(users)} licentie(s) meer dan actieve gebruikers.","Controleer of overcapaciteit gewenst is.")
        if users and not vault:self._add(findings,"Hoog","IT Kluis","Voor deze klant zijn geen beheercredentials geregistreerd.","Leg minimaal de beheeraccounts veilig vast.")
        cutoff=(datetime.now()-timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")
        stale=[v for v in vault if v["updated_at"]<cutoff]
        if stale:self._add(findings,"Normaal","IT Kluis",f"{len(stale)} kluisitem(s) zijn langer dan 180 dagen niet bijgewerkt.","Controleer geldigheid en actualiseer de registratie.")
        if critical:self._add(findings,"Kritiek","Servicedesk",f"{critical} kritisch servicedeskticket(s) staan open.","Behandel of escaleer deze tickets.")
        if overdue:self._add(findings,"Hoog","Actiepunten",f"{overdue} beveiligingsrelevant actiepunt(en) kunnen achterstallig zijn.","Controleer de verlopen acties.")
        return findings

    def summary(self,customer_id: int) -> dict:
        findings=self.checks(customer_id); users=[u for u in self.users(customer_id) if u["active"]]
        weights={"Kritiek":25,"Hoog":15,"Normaal":8,"Laag":3}
        score=max(0,100-sum(weights[x["severity"]] for x in findings))
        mfa=sum(1 for user in users if user["mfa_enabled"])
        return {"score":score,"findings":findings,"users":len(users),"mfa":mfa,
                "critical":sum(1 for x in findings if x["severity"]=="Kritiek"),
                "high":sum(1 for x in findings if x["severity"]=="Hoog")}

    def audit(self,customer_id: int,limit: int=100) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("""SELECT occurred_at,actor,action,entity_type,entity_id,reason
                FROM audit_events WHERE customer_id=? ORDER BY id DESC LIMIT ?""",(customer_id,limit))]

    def export_csv(self,customer_id: int) -> Path:
        folder=self._folder(customer_id); target=folder/"beveiligingscontrole.csv"; findings=self.checks(customer_id)
        with target.open("w",encoding="utf-8-sig",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=("severity","category","finding","advice"),delimiter=";")
            writer.writeheader(); writer.writerows(findings)
        return target

    def export_report(self,customer_id: int) -> Path:
        with self.db.transaction() as conn:customer=conn.execute("SELECT customer_number,name FROM customers WHERE id=?",(customer_id,)).fetchone()
        if not customer:raise ValueError("Klant bestaat niet")
        summary=self.summary(customer_id); target=self._folder(customer_id)/"beveiligingscontrole.txt"
        lines=[f"Beveiligingscontrole — {customer['customer_number']} — {customer['name']}",
               f"Datum: {datetime.now():%d-%m-%Y %H:%M}",f"Beveiligingsscore: {summary['score']}/100",
               f"MFA: {summary['mfa']} van {summary['users']} actieve gebruikers",""]
        for item in summary["findings"]:
            lines.extend([f"[{item['severity']}] {item['category']}: {item['finding']}",f"Advies: {item['advice']}",""])
        if not summary["findings"]:lines.append("Geen directe beveiligingsaandachtspunten gevonden.")
        target.write_text("\n".join(lines),encoding="utf-8");return target

    def _folder(self,customer_id):
        folder=self.output_dir/f"klant-{customer_id}";folder.mkdir(parents=True,exist_ok=True);return folder

    @staticmethod
    def _add(target,severity,category,finding,advice):
        target.append({"severity":severity,"category":category,"finding":finding,"advice":advice})
