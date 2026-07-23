from __future__ import annotations

from datetime import date
from hashlib import sha256
import html
import json
from pathlib import Path
import secrets

from nowa_crm.core.paths import data_dir
from nowa_crm.modules.proposals.service import ProposalService


class ProposalApprovalService:
    """Builds a portable approval portal and safely imports its decision."""

    def __init__(self, proposals: ProposalService):
        self.proposals = proposals
        self.db = proposals.db

    def prepare(self, proposal_id: int, recipient_email: str, expires_at: str,
                output_dir: Path | None = None) -> dict:
        proposal = self.proposals.get(proposal_id)
        if not proposal:
            raise ValueError("Offerte niet gevonden.")
        try:
            expiry = date.fromisoformat(expires_at)
        except ValueError as exc:
            raise ValueError("Gebruik voor de vervaldatum jjjj-mm-dd.") from exc
        if expiry <= date.today():
            raise ValueError("De vervaldatum moet in de toekomst liggen.")
        warnings = self.proposals.validate(proposal_id)
        if warnings:
            raise ValueError("Los eerst de offertecontrole op:\n- " + "\n- ".join(warnings))

        token = secrets.token_urlsafe(32)
        token_hash = sha256(token.encode()).hexdigest()
        lines = self.proposals.lines(proposal_id)
        totals = self.proposals.totals(proposal_id)
        with self.db.transaction() as conn:
            licenses = [dict(row) for row in conn.execute(
                """SELECT id,product,supplier,quantity,unit_price_cents,
                          included_in_proposal,renewal_date
                   FROM customer_licenses WHERE customer_id=?
                   ORDER BY product COLLATE NOCASE""", (proposal.customer_id,))]
        license_changes = [{
            "license_id": row["id"], "product": row["product"], "supplier": row["supplier"],
            "current_quantity": row["quantity"], "requested_quantity": row["quantity"],
            "difference": 0, "unit_price_cents": row["unit_price_cents"],
            "current_monthly_cents": row["quantity"] * row["unit_price_cents"],
            "requested_monthly_cents": row["quantity"] * row["unit_price_cents"],
            "effective_date": "", "included_in_proposal": bool(row["included_in_proposal"]),
            "renewal_date": row["renewal_date"],
        } for row in licenses]
        snapshot = {
            "format": "nowa-proposal-approval-v2",
            "proposal": {"number": proposal.number, "revision": proposal.revision,
                         "title": proposal.title, "customer_name": proposal.customer_name,
                         "status": proposal.status},
            "lines": [{"group": row.group_name, "kind": row.kind,
                       "description": row.description, "quantity": row.quantity,
                       "unit_price_cents": row.unit_price_cents,
                       "billing_period": row.billing_period,
                       "optional": bool(row.optional)}
                      for row in lines if row.active],
            "totals": {**totals, "monthly_cents": self.proposals.monthly_total(proposal_id)},
            "sections": self.proposals.sections(proposal_id),
            "license_changes": license_changes,
            "expires_at": expires_at,
        }
        folder = output_dir or data_dir() / "exports" / "online-akkoord"
        portal_dir = folder / f"{proposal.number}-R{proposal.revision}"
        portal_dir.mkdir(parents=True, exist_ok=True)
        package = {**snapshot, "access_token": token,
                   "recipient_email": recipient_email.strip()}
        package_path = portal_dir / "akkoordpakket.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        portal_path = portal_dir / "index.html"
        portal_path.write_text(self._portal_html(package), encoding="utf-8")
        with self.db.transaction() as conn:
            conn.execute("""UPDATE proposal_publications
                            SET status='ingetrokken',revoked_at=CURRENT_TIMESTAMP
                            WHERE proposal_id=? AND status IN ('voorbereid','gepubliceerd')""",
                         (proposal_id,))
            cursor = conn.execute(
                """INSERT INTO proposal_publications
                   (proposal_id,revision,token_hash,token_hint,recipient_email,
                    expires_at,package_path,snapshot_json)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (proposal_id, proposal.revision, token_hash, token[-6:],
                 recipient_email.strip(), expires_at, str(portal_path),
                 json.dumps(snapshot, ensure_ascii=False)))
        return {"id": int(cursor.lastrowid), "path": portal_path,
                "folder": portal_dir, "token": token, "expires_at": expires_at}

    def import_decision(self, decision_path: Path) -> dict:
        try:
            decision = json.loads(Path(decision_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Het akkoordbestand kan niet worden gelezen.") from exc
        if decision.get("format") != "nowa-proposal-decision-v1":
            raise ValueError("Dit is geen geldig NOWA-akkoordbestand.")
        token = str(decision.get("access_token", ""))
        token_hash = sha256(token.encode()).hexdigest()
        with self.db.transaction() as conn:
            publication = conn.execute(
                """SELECT p.*,q.customer_id,q.number proposal_number
                   FROM proposal_publications p JOIN proposals q ON q.id=p.proposal_id
                   WHERE p.token_hash=?""", (token_hash,)).fetchone()
            if not publication:
                raise ValueError("De akkoordcode is onbekend of ongeldig.")
            if publication["status"] not in ("voorbereid", "gepubliceerd"):
                raise ValueError(f"Dit akkoord kan niet worden verwerkt: {publication['status']}.")
            if date.fromisoformat(publication["expires_at"]) < date.today():
                raise ValueError("De akkoordtermijn is verlopen.")
            if not decision.get("accepted"):
                raise ValueError("De klant heeft geen akkoord gegeven.")
            accepted_by = str(decision.get("accepted_by", "")).strip()
            if not accepted_by:
                raise ValueError("De naam van de akkoordgever ontbreekt.")
            snapshot = json.loads(publication["snapshot_json"])
            expected = {int(item["license_id"]): item for item in snapshot["license_changes"]}
            changes = self._validated_changes(decision.get("license_changes", []), expected)
            conn.execute(
                """UPDATE proposal_publications SET status='geaccepteerd',
                   accepted_at=CURRENT_TIMESTAMP,accepted_by=?,accepted_function=?,
                   acceptance_comment=?,license_changes_json=?
                   WHERE id=?""",
                (accepted_by, str(decision.get("accepted_function", "")).strip(),
                 str(decision.get("comment", "")).strip(),
                 json.dumps(changes, ensure_ascii=False), publication["id"]))
        return {"publication_id": publication["id"],
                "proposal_number": publication["proposal_number"],
                "accepted_by": accepted_by, "license_changes": changes}

    def apply_license_changes(self, publication_id: int) -> dict:
        with self.db.transaction() as conn:
            publication = conn.execute(
                """SELECT p.*,q.customer_id FROM proposal_publications p
                   JOIN proposals q ON q.id=p.proposal_id WHERE p.id=?""",
                (publication_id,)).fetchone()
            if not publication or publication["status"] != "geaccepteerd":
                raise ValueError("Alleen een gecontroleerd akkoord kan worden verwerkt.")
            if publication["applied_at"]:
                raise ValueError("Deze licentiewijzigingen zijn al verwerkt.")
            changes = json.loads(publication["license_changes_json"])
            applied_ids = set(json.loads(publication["applied_license_ids_json"]))
            changed = 0
            pending = 0
            for item in changes:
                license_id = int(item["license_id"])
                if item["requested_quantity"] == item["current_quantity"] or license_id in applied_ids:
                    continue
                effective = item.get("effective_date", "")
                if effective and date.fromisoformat(effective) > date.today():
                    pending += 1
                    continue
                cursor = conn.execute(
                    """UPDATE customer_licenses SET quantity=?
                       WHERE id=? AND customer_id=? AND quantity=?""",
                    (item["requested_quantity"], item["license_id"],
                     publication["customer_id"], item["current_quantity"]))
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"{item['product']} is intussen lokaal gewijzigd. Controleer dit handmatig.")
                applied_ids.add(license_id)
                changed += 1
            remaining = [item for item in changes
                         if item["requested_quantity"] != item["current_quantity"]
                         and int(item["license_id"]) not in applied_ids]
            conn.execute(
                """UPDATE proposal_publications SET applied_license_ids_json=?,
                   applied_at=CASE WHEN ?=0 THEN CURRENT_TIMESTAMP ELSE applied_at END
                   WHERE id=?""",
                (json.dumps(sorted(applied_ids)), len(remaining), publication_id))
            conn.execute(
                """INSERT INTO customer_change_log(customer_id,action,changed_fields,detail)
                   VALUES(?,?,?,?)""",
                (publication["customer_id"], "offerte-akkoord",
                 "licenties", f"{changed} licentiewijziging(en) verwerkt; {pending} gepland"))
        return {"changed": changed, "pending": pending, "complete": not remaining}

    def overview(self) -> list[dict]:
        """Returns one compact sales worklist without exposing tokens or snapshots."""
        with self.db.transaction() as conn:
            rows = [dict(row) for row in conn.execute(
                """SELECT p.id,p.proposal_id,p.revision,p.recipient_email,p.expires_at,
                          p.status,p.created_at,p.accepted_at,p.accepted_by,p.applied_at,
                          p.license_changes_json,p.applied_license_ids_json,
                          q.number,q.title,c.name customer_name
                   FROM proposal_publications p
                   JOIN proposals q ON q.id=p.proposal_id
                   JOIN customers c ON c.id=q.customer_id
                   ORDER BY COALESCE(p.accepted_at,p.created_at) DESC""")]
        today = date.today()
        result = []
        for row in rows:
            changes = json.loads(row.pop("license_changes_json") or "[]")
            applied_ids = set(json.loads(row.pop("applied_license_ids_json") or "[]"))
            changed = [item for item in changes
                       if item["requested_quantity"] != item["current_quantity"]]
            due = [item for item in changed if int(item["license_id"]) not in applied_ids
                   and (not item.get("effective_date")
                        or date.fromisoformat(item["effective_date"]) <= today)]
            future = [item for item in changed if int(item["license_id"]) not in applied_ids
                      and item.get("effective_date")
                      and date.fromisoformat(item["effective_date"]) > today]
            display_status = row["status"]
            if display_status in ("voorbereid", "gepubliceerd") and date.fromisoformat(row["expires_at"]) < today:
                display_status = "verlopen"
            elif display_status == "geaccepteerd" and row["applied_at"]:
                display_status = "verwerkt"
            elif display_status == "geaccepteerd" and due:
                display_status = "te verwerken"
            elif display_status == "geaccepteerd" and future:
                display_status = "ingepland"
            row.update(display_status=display_status, changed_count=len(changed),
                       due_count=len(due), future_count=len(future),
                       next_effective=min((item["effective_date"] for item in future), default=""))
            result.append(row)
        return result

    def expire_publications(self) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """UPDATE proposal_publications SET status='verlopen'
                   WHERE status IN ('voorbereid','gepubliceerd') AND expires_at<?""",
                (date.today().isoformat(),))
            return cursor.rowcount

    def history(self, proposal_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                """SELECT id,revision,token_hint,recipient_email,expires_at,status,
                          package_path,created_at,revoked_at,accepted_at,accepted_by,applied_at
                   FROM proposal_publications WHERE proposal_id=?
                   ORDER BY id DESC""", (proposal_id,))]

    def revoke(self, publication_id: int) -> None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status FROM proposal_publications WHERE id=?",
                               (publication_id,)).fetchone()
            if not row:
                raise ValueError("Publicatie niet gevonden.")
            if row["status"] in ("geaccepteerd", "ingetrokken"):
                raise ValueError("Deze publicatie kan niet meer worden ingetrokken.")
            conn.execute("""UPDATE proposal_publications
                            SET status='ingetrokken',revoked_at=CURRENT_TIMESTAMP
                            WHERE id=?""", (publication_id,))

    def revoke_for_new_revision(self, proposal_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("""UPDATE proposal_publications
                            SET status='ingetrokken',revoked_at=CURRENT_TIMESTAMP
                            WHERE proposal_id=? AND status IN ('voorbereid','gepubliceerd')""",
                         (proposal_id,))

    @staticmethod
    def _validated_changes(received: list, expected: dict[int, dict]) -> list[dict]:
        if not isinstance(received, list):
            raise ValueError("De licentiewijzigingen zijn ongeldig.")
        result = []
        seen = set()
        for raw in received:
            license_id = int(raw.get("license_id", 0))
            if license_id not in expected or license_id in seen:
                raise ValueError("Het akkoord bevat een onbekende of dubbele licentie.")
            seen.add(license_id)
            original = expected[license_id]
            requested = int(raw.get("requested_quantity", -1))
            if requested < 0 or requested > 100000:
                raise ValueError(f"Ongeldig aantal voor {original['product']}.")
            effective = str(raw.get("effective_date", "")).strip()
            if effective:
                try:
                    date.fromisoformat(effective)
                except ValueError as exc:
                    raise ValueError(
                        f"Ongeldige ingangsdatum voor {original['product']}.") from exc
            result.append({**original, "requested_quantity": requested,
                           "difference": requested - original["current_quantity"],
                           "requested_monthly_cents": requested * original["unit_price_cents"],
                           "effective_date": effective})
        if seen != set(expected):
            raise ValueError("Niet alle bestaande licenties staan in het akkoord.")
        return result

    @staticmethod
    def _portal_html(package: dict) -> str:
        payload = json.dumps(package, ensure_ascii=False).replace("</", "<\\/")
        title = html.escape(package["proposal"]["title"])
        return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>NOWA akkoord – {title}</title>
<style>
:root{{--navy:#0b2342;--blue:#1677ff;--bg:#f3f6fb;--line:#d9e2ef;--muted:#5d6d83}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--navy);font:15px Segoe UI,Arial,sans-serif}}
header{{background:linear-gradient(120deg,#071b35,#123e70);color:white;padding:28px max(24px,calc((100% - 1120px)/2))}}
.brand{{font-weight:800;letter-spacing:.08em}}main{{max-width:1120px;margin:28px auto;padding:0 22px}}
.card{{background:white;border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:18px;box-shadow:0 8px 28px #0b234210}}
h1{{font-size:30px;margin:8px 0}}h2{{font-size:20px;margin:0 0 16px}}.muted{{color:var(--muted)}}
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.stat{{background:#f5f8fc;border-radius:12px;padding:16px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:12px 10px;border-bottom:1px solid var(--line);text-align:left}}
th{{background:#edf3fa}}input,textarea{{width:100%;padding:11px;border:1px solid #b8c7da;border-radius:9px;font:inherit}}
input[type=number]{{max-width:110px}}label{{font-weight:600;display:block;margin:12px 0 6px}}
.accept{{display:flex;gap:10px;align-items:flex-start;background:#eef6ff;padding:14px;border-radius:10px;margin:18px 0}}
.accept input{{width:auto;margin-top:3px}}button{{border:0;border-radius:10px;background:var(--blue);color:white;padding:13px 20px;font-weight:700;cursor:pointer}}
.delta{{font-weight:700}}@media(max-width:760px){{.stats{{grid-template-columns:1fr}}table{{font-size:13px}}th,td{{padding:8px 5px}}}}
</style></head><body>
<header><div class="brand">NOWA SOLUTIONS · DIGITAAL AKKOORD</div><h1 id="title"></h1><div id="customer"></div></header>
<main><section class="card"><h2>Offerteoverzicht</h2><div class="stats">
<div class="stat"><b>Offertenummer</b><div id="number"></div></div>
<div class="stat"><b>Eenmalig excl. btw</b><div id="once"></div></div>
<div class="stat"><b>Maandelijks excl. btw</b><div id="monthly"></div></div></div>
<p class="muted" id="expiry"></p></section>
<section class="card"><h2>Onderdelen</h2><table><thead><tr><th>Omschrijving</th><th>Aantal</th><th>Periode</th><th>Prijs</th></tr></thead><tbody id="lines"></tbody></table></section>
<section class="card" id="licenses-card"><h2>Bestaande licenties aanpassen</h2>
<p class="muted">Controleer het gewenste nieuwe totaal. Een lager aantal is een vermindering; nul beëindigt de registratie.</p>
<table><thead><tr><th>Licentie</th><th>Huidig</th><th>Gewenst</th><th>Verschil</th><th>Ingangsdatum</th></tr></thead><tbody id="licenses"></tbody></table></section>
<section class="card"><h2>Akkoordverklaring</h2>
<label>Naam akkoordgever</label><input id="name" autocomplete="name">
<label>Functie</label><input id="role">
<label>Opmerking (optioneel)</label><textarea id="comment" rows="3"></textarea>
<label class="accept"><input type="checkbox" id="accept"><span>Ik ben bevoegd namens de opdrachtgever en ga akkoord met deze offerte en de hierboven gekozen licentieaantallen.</span></label>
<button id="download">Akkoord bevestigen en bewijs downloaden</button>
<p class="muted">Stuur het gedownloade akkoordbestand terug naar NOWA Solutions. Uw gegevens blijven in dit bestand en worden niet door deze pagina verzonden.</p></section></main>
<script>const p={payload};const euro=c=>new Intl.NumberFormat('nl-NL',{{style:'currency',currency:'EUR'}}).format(c/100);
title.textContent=p.proposal.title;customer.textContent=p.proposal.customer_name;number.textContent=p.proposal.number+' · revisie '+p.proposal.revision;
once.textContent=euro(p.totals.subtotal_cents);monthly.textContent=euro(p.totals.monthly_cents);expiry.textContent='Geldig tot en met '+p.expires_at;
p.lines.forEach(x=>{{const r=lines.insertRow();r.innerHTML='<td></td><td></td><td></td><td></td>';r.cells[0].textContent=x.description+(x.optional?' (optie)':'');r.cells[1].textContent=x.quantity;r.cells[2].textContent=x.billing_period;r.cells[3].textContent=euro(x.unit_price_cents);}});
if(!p.license_changes.length)document.querySelector('#licenses-card').hidden=true;
p.license_changes.forEach((x,i)=>{{const r=licenses.insertRow();r.innerHTML='<td></td><td></td><td><input type="number" min="0" max="100000"></td><td class="delta">0</td><td><input type="date"></td>';r.cells[0].textContent=x.product;r.cells[1].textContent=x.current_quantity;const q=r.querySelector('[type=number]');q.value=x.current_quantity;q.oninput=()=>r.cells[3].textContent=(+q.value-x.current_quantity>0?'+':'')+(+q.value-x.current_quantity);}});
download.onclick=()=>{{if(!accept.checked||!name.value.trim()){{alert('Vul uw naam in en bevestig het akkoord.');return}};const rows=[...licenses.rows];const decision={{format:'nowa-proposal-decision-v1',access_token:p.access_token,proposal_number:p.proposal.number,revision:p.proposal.revision,accepted:true,accepted_by:name.value.trim(),accepted_function:role.value.trim(),comment:comment.value.trim(),decided_at:new Date().toISOString(),license_changes:p.license_changes.map((x,i)=>({{license_id:x.license_id,requested_quantity:+rows[i].querySelector('[type=number]').value,effective_date:rows[i].querySelector('[type=date]').value}}))}};const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(decision,null,2)],{{type:'application/json'}}));a.download=p.proposal.number+'-akkoord.json';a.click();URL.revokeObjectURL(a.href);}};
</script></body></html>"""
