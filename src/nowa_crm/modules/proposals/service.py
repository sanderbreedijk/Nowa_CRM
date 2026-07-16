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

    def count_open(self) -> int:
        with self.db.transaction() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM proposals WHERE status IN ('concept','verzonden')").fetchone()[0])
