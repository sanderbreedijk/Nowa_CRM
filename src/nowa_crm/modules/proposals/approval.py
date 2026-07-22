from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import secrets

from nowa_crm.core.paths import data_dir
from nowa_crm.modules.proposals.service import ProposalService


class ProposalApprovalService:
    """Creates revocable local hand-off packages for a future approval portal."""

    def __init__(self, proposals: ProposalService):
        self.proposals=proposals;self.db=proposals.db

    def prepare(self, proposal_id: int, recipient_email: str, expires_at: str, output_dir: Path | None = None) -> dict:
        proposal=self.proposals.get(proposal_id)
        if not proposal:raise ValueError("Offerte niet gevonden.")
        try:expiry=date.fromisoformat(expires_at)
        except ValueError:raise ValueError("Gebruik voor de vervaldatum jjjj-mm-dd.")
        if expiry<=date.today():raise ValueError("De vervaldatum moet in de toekomst liggen.")
        warnings=self.proposals.validate(proposal_id)
        if warnings:raise ValueError("Los eerst de offertecontrole op:\n- " + "\n- ".join(warnings))
        token=secrets.token_urlsafe(32);token_hash=sha256(token.encode()).hexdigest();lines=self.proposals.lines(proposal_id);totals=self.proposals.totals(proposal_id)
        snapshot={"format":"nowa-proposal-approval-v1","proposal":{"number":proposal.number,"revision":proposal.revision,"title":proposal.title,"customer_name":proposal.customer_name,"status":proposal.status},
                  "lines":[{"group":x.group_name,"kind":x.kind,"description":x.description,"quantity":x.quantity,"unit_price_cents":x.unit_price_cents,"billing_period":x.billing_period,"optional":bool(x.optional)} for x in lines if x.active],
                  "totals":{**totals,"monthly_cents":self.proposals.monthly_total(proposal_id)},"sections":self.proposals.sections(proposal_id),"expires_at":expires_at}
        folder=output_dir or data_dir()/"exports"/"online-akkoord";folder.mkdir(parents=True,exist_ok=True);target=folder/f"{proposal.number}-R{proposal.revision}-akkoordpakket.json"
        package={**snapshot,"access_token":token,"recipient_email":recipient_email.strip()};target.write_text(json.dumps(package,ensure_ascii=False,indent=2),encoding="utf-8")
        with self.db.transaction() as conn:
            conn.execute("UPDATE proposal_publications SET status='ingetrokken',revoked_at=CURRENT_TIMESTAMP WHERE proposal_id=? AND status IN ('voorbereid','gepubliceerd')",(proposal_id,))
            cur=conn.execute("""INSERT INTO proposal_publications(proposal_id,revision,token_hash,token_hint,recipient_email,expires_at,package_path,snapshot_json)
                VALUES(?,?,?,?,?,?,?,?)""",(proposal_id,proposal.revision,token_hash,token[-6:],recipient_email.strip(),expires_at,str(target),json.dumps(snapshot,ensure_ascii=False)))
        return {"id":int(cur.lastrowid),"path":target,"token":token,"expires_at":expires_at}

    def history(self, proposal_id: int) -> list[dict]:
        with self.db.transaction() as conn:return [dict(x) for x in conn.execute("SELECT id,revision,token_hint,recipient_email,expires_at,status,package_path,created_at,revoked_at,accepted_at,accepted_by FROM proposal_publications WHERE proposal_id=? ORDER BY id DESC",(proposal_id,))]

    def revoke(self, publication_id: int) -> None:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT status FROM proposal_publications WHERE id=?",(publication_id,)).fetchone()
            if not row:raise ValueError("Publicatie niet gevonden.")
            if row["status"] in ("geaccepteerd","ingetrokken"):raise ValueError("Deze publicatie kan niet meer worden ingetrokken.")
            conn.execute("UPDATE proposal_publications SET status='ingetrokken',revoked_at=CURRENT_TIMESTAMP WHERE id=?",(publication_id,))

    def revoke_for_new_revision(self, proposal_id: int) -> None:
        with self.db.transaction() as conn:conn.execute("UPDATE proposal_publications SET status='ingetrokken',revoked_at=CURRENT_TIMESTAMP WHERE proposal_id=? AND status IN ('voorbereid','gepubliceerd')",(proposal_id,))
