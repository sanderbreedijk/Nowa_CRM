from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nowa_crm.core.database import Database


@dataclass(frozen=True)
class Proposal:
    id: int
    customer_id: int
    customer_name: str
    number: str
    title: str
    status: str
    revision: int
    total_cents: int


@dataclass(frozen=True)
class ProposalLine:
    id: int
    proposal_id: int
    kind: str
    description: str
    quantity: float
    unit_price_cents: int
    sort_order: int

    @property
    def line_total_cents(self) -> int:
        return round(self.quantity * self.unit_price_cents)


class ProposalService:
    STATUSES = ("concept", "verzonden", "geaccepteerd", "afgewezen", "verlopen")

    def __init__(self, db: Database):
        self.db = db

    def create(self, customer_id: int, title: str) -> int:
        if not title.strip():
            raise ValueError("Titel is verplicht")
        prefix = datetime.now().strftime("OFF-%Y%m")
        with self.db.transaction() as conn:
            seq = conn.execute("SELECT COUNT(*) FROM proposals WHERE number LIKE ?", (prefix + "-%",)).fetchone()[0] + 1
            number = f"{prefix}-{seq:04d}"
            cur = conn.execute("INSERT INTO proposals(customer_id,number,title) VALUES(?,?,?)", (customer_id, number, title.strip()))
            return int(cur.lastrowid)

    def list(self, query: str = "") -> list[Proposal]:
        term = f"%{query.strip()}%"
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT p.id,p.customer_id,c.name customer_name,p.number,p.title,p.status,p.revision,p.total_cents
                   FROM proposals p JOIN customers c ON c.id=p.customer_id
                   WHERE ?='' OR p.number LIKE ? OR p.title LIKE ? OR c.name LIKE ?
                   ORDER BY p.updated_at DESC,p.id DESC""", (query.strip(), term, term, term)
            ).fetchall()
        return [Proposal(**dict(row)) for row in rows]

    def set_status(self, proposal_id: int, status: str) -> None:
        if status not in self.STATUSES:
            raise ValueError("Ongeldige offertestatus")
        with self.db.transaction() as conn:
            conn.execute("UPDATE proposals SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, proposal_id))

    def get(self, proposal_id: int) -> Proposal | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                """SELECT p.id,p.customer_id,c.name customer_name,p.number,p.title,p.status,p.revision,p.total_cents
                   FROM proposals p JOIN customers c ON c.id=p.customer_id WHERE p.id=?""", (proposal_id,)
            ).fetchone()
        return Proposal(**dict(row)) if row else None

    def lines(self, proposal_id: int) -> list[ProposalLine]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT id,proposal_id,kind,description,quantity,unit_price_cents,sort_order FROM proposal_lines WHERE proposal_id=? ORDER BY sort_order,id",
                (proposal_id,),
            ).fetchall()
        return [ProposalLine(**dict(row)) for row in rows]

    def add_line(self, proposal_id: int, kind: str, description: str, quantity: float, unit_price_cents: int) -> int:
        if not description.strip(): raise ValueError("Omschrijving is verplicht")
        if quantity <= 0: raise ValueError("Aantal moet groter zijn dan nul")
        if unit_price_cents < 0: raise ValueError("Prijs mag niet negatief zijn")
        with self.db.transaction() as conn:
            order = int(conn.execute("SELECT COALESCE(MAX(sort_order),0)+10 FROM proposal_lines WHERE proposal_id=?",(proposal_id,)).fetchone()[0])
            cur = conn.execute(
                "INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,sort_order) VALUES(?,?,?,?,?,?)",
                (proposal_id,kind,description.strip(),quantity,unit_price_cents,order),
            )
            line_id=int(cur.lastrowid); self._recalculate(conn,proposal_id); return line_id

    def delete_line(self, line_id: int) -> None:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT proposal_id FROM proposal_lines WHERE id=?",(line_id,)).fetchone()
            if not row: raise KeyError(line_id)
            conn.execute("DELETE FROM proposal_lines WHERE id=?",(line_id,)); self._recalculate(conn,int(row[0]))

    def _recalculate(self, conn, proposal_id: int) -> None:
        total=conn.execute("SELECT COALESCE(SUM(ROUND(quantity*unit_price_cents)),0) FROM proposal_lines WHERE proposal_id=?",(proposal_id,)).fetchone()[0]
        conn.execute("UPDATE proposals SET total_cents=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(int(total),proposal_id))

    def totals(self, proposal_id: int, vat_rate: float = 0.21) -> dict[str,int]:
        proposal=self.get(proposal_id)
        subtotal=proposal.total_cents if proposal else 0; vat=round(subtotal*vat_rate)
        return {"subtotal_cents":subtotal,"vat_cents":vat,"total_cents":subtotal+vat}

    def count_open(self) -> int:
        with self.db.transaction() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM proposals WHERE status IN ('concept','verzonden')").fetchone()[0])

    def templates(self) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("SELECT id,name,description FROM proposal_templates ORDER BY name COLLATE NOCASE")]

    def apply_template(self, proposal_id: int, template_id: int) -> None:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT kind,description,quantity,unit_price_cents,sort_order FROM proposal_template_lines WHERE template_id=? ORDER BY sort_order,id", (template_id,)).fetchall()
            if not rows: raise ValueError("Dit offertesjabloon bevat geen regels")
            start = int(conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM proposal_lines WHERE proposal_id=?", (proposal_id,)).fetchone()[0])
            conn.executemany("INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,sort_order) VALUES(?,?,?,?,?,?)",
                             [(proposal_id, row["kind"], row["description"], row["quantity"], row["unit_price_cents"], start + row["sort_order"]) for row in rows])
            self._recalculate(conn, proposal_id)
