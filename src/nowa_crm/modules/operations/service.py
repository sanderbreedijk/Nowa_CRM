from __future__ import annotations

from nowa_crm.core.database import Database


class OperationsService:
    TABLES = {
        "users": "customer_users",
        "licenses": "customer_licenses",
        "hardware": "customer_hardware",
        "tasks": "project_tasks",
    }

    def __init__(self, db: Database):
        self.db = db

    def list_rows(self, kind: str, customer_id: int) -> list[dict]:
        table = self._table(kind)
        order = {"users": "display_name", "licenses": "product", "hardware": "kind,brand,model", "tasks": "start_date,phase,task_name"}[kind]
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE customer_id=? ORDER BY {order}", (customer_id,))]

    def save_user(self, customer_id: int, display_name: str, upn: str = "", department: str = "",
                  license_name: str = "", mfa_enabled: bool = False, active: bool = True, notes: str = "") -> int:
        if not display_name.strip():
            raise ValueError("Naam van de gebruiker is verplicht")
        return self._insert("customer_users",
            ("customer_id","display_name","user_principal_name","department","license_name","mfa_enabled","active","notes"),
            (customer_id,display_name.strip(),upn.strip(),department.strip(),license_name.strip(),int(mfa_enabled),int(active),notes.strip()))

    def save_license(self, customer_id: int, product: str, supplier: str = "Microsoft", quantity: int = 1,
                     unit_price_cents: int = 0, included: bool = True, renewal_date: str = "", notes: str = "") -> int:
        if not product.strip() or quantity < 1:
            raise ValueError("Product en een geldig aantal zijn verplicht")
        return self._insert("customer_licenses",
            ("customer_id","product","supplier","quantity","unit_price_cents","included_in_proposal","renewal_date","notes"),
            (customer_id,product.strip(),supplier.strip(),quantity,unit_price_cents,int(included),renewal_date.strip(),notes.strip()))

    def save_hardware(self, customer_id: int, kind: str, brand: str = "", model: str = "", serial_number: str = "",
                      quantity: int = 1, purchase_price_cents: int = 0, sales_price_cents: int = 0,
                      status: str = "In gebruik", notes: str = "") -> int:
        if not kind.strip() or quantity < 1:
            raise ValueError("Type hardware en een geldig aantal zijn verplicht")
        return self._insert("customer_hardware",
            ("customer_id","kind","brand","model","serial_number","quantity","purchase_price_cents","sales_price_cents","status","notes"),
            (customer_id,kind.strip(),brand.strip(),model.strip(),serial_number.strip(),quantity,purchase_price_cents,sales_price_cents,status.strip(),notes.strip()))

    def save_task(self, customer_id: int, phase: str, task_name: str, owner: str = "NOWA", start_date: str = "",
                  end_date: str = "", dependency: str = "", status: str = "Gepland", notes: str = "") -> int:
        if not task_name.strip():
            raise ValueError("Taaknaam is verplicht")
        return self._insert("project_tasks",
            ("customer_id","phase","task_name","owner","start_date","end_date","dependency","status","notes"),
            (customer_id,phase.strip(),task_name.strip(),owner.strip(),start_date.strip(),end_date.strip(),dependency.strip(),status.strip(),notes.strip()))

    def intake(self, customer_id: int) -> dict:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM project_intakes WHERE customer_id=?", (customer_id,)).fetchone()
        return dict(row) if row else {"customer_id": customer_id, "users_count": 0, "devices_count": 0, "shared_mailboxes": 0,
            "teams_count": 0, "sharepoint_sites": 0, "migration_source": "", "desired_date": "", "scope_notes": ""}

    def save_intake(self, customer_id: int, users_count: int, devices_count: int, shared_mailboxes: int,
                    teams_count: int, sharepoint_sites: int, migration_source: str, desired_date: str, scope_notes: str) -> None:
        counts = (users_count, devices_count, shared_mailboxes, teams_count, sharepoint_sites)
        if any(value < 0 for value in counts):
            raise ValueError("Aantallen mogen niet negatief zijn")
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO project_intakes(customer_id,users_count,devices_count,shared_mailboxes,teams_count,sharepoint_sites,migration_source,desired_date,scope_notes)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(customer_id) DO UPDATE SET users_count=excluded.users_count,devices_count=excluded.devices_count,
                shared_mailboxes=excluded.shared_mailboxes,teams_count=excluded.teams_count,sharepoint_sites=excluded.sharepoint_sites,
                migration_source=excluded.migration_source,desired_date=excluded.desired_date,scope_notes=excluded.scope_notes,updated_at=CURRENT_TIMESTAMP""",
                (customer_id,*counts,migration_source.strip(),desired_date.strip(),scope_notes.strip()))

    def delete(self, kind: str, row_id: int) -> None:
        table = self._table(kind)
        with self.db.transaction() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))

    def dashboard(self) -> dict[str, int]:
        with self.db.transaction() as conn:
            return {
                "users": int(conn.execute("SELECT COUNT(*) FROM customer_users WHERE active=1").fetchone()[0]),
                "licenses": int(conn.execute("SELECT COALESCE(SUM(quantity),0) FROM customer_licenses").fetchone()[0]),
                "hardware": int(conn.execute("SELECT COALESCE(SUM(quantity),0) FROM customer_hardware").fetchone()[0]),
                "open_tasks": int(conn.execute("SELECT COUNT(*) FROM project_tasks WHERE status NOT IN ('Gereed','Geannuleerd')").fetchone()[0]),
            }

    def license_warnings(self, customer_id: int) -> list[str]:
        with self.db.transaction() as conn:
            users = int(conn.execute("SELECT COUNT(*) FROM customer_users WHERE customer_id=? AND active=1", (customer_id,)).fetchone()[0])
            licenses = int(conn.execute("SELECT COALESCE(SUM(quantity),0) FROM customer_licenses WHERE customer_id=?", (customer_id,)).fetchone()[0])
            no_mfa = int(conn.execute("SELECT COUNT(*) FROM customer_users WHERE customer_id=? AND active=1 AND mfa_enabled=0", (customer_id,)).fetchone()[0])
        warnings = []
        if licenses < users: warnings.append(f"Er zijn {users - licenses} minder licenties dan actieve gebruikers.")
        if no_mfa: warnings.append(f"{no_mfa} actieve gebruikers hebben nog geen MFA-registratie.")
        return warnings

    def _insert(self, table: str, columns: tuple[str, ...], values: tuple) -> int:
        placeholders = ",".join("?" for _ in values)
        with self.db.transaction() as conn:
            cur = conn.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})", values)
            return int(cur.lastrowid)

    def _table(self, kind: str) -> str:
        try:
            return self.TABLES[kind]
        except KeyError as exc:
            raise ValueError("Onbekende operationele module") from exc
