from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir


class CustomerAssetsService:
    TABLES={"locations":"customer_locations","software":"customer_software","documents":"customer_documents"}

    def __init__(self,db: Database,storage: Path | None=None):
        self.db=db; self.storage=storage or data_dir()/"documents"

    def list(self,kind: str,customer_id: int) -> list[dict]:
        table=self.TABLES[kind]; order="created_at DESC" if kind=="documents" else "name"
        with self.db.transaction() as conn:return [dict(x) for x in conn.execute(f"SELECT * FROM {table} WHERE customer_id=? ORDER BY {order}",(customer_id,))]

    def add_location(self,customer_id: int,name: str,address: str="",city: str="",notes: str="") -> int:
        if not name.strip():raise ValueError("Locatienaam is verplicht")
        with self.db.transaction() as conn:
            row=conn.execute("SELECT id FROM customer_locations WHERE customer_id=? AND name=? COLLATE NOCASE",(customer_id,name.strip())).fetchone()
            if row:return int(row["id"])
            return int(conn.execute("INSERT INTO customer_locations(customer_id,name,address,city,notes) VALUES(?,?,?,?,?)",(customer_id,name.strip(),address.strip(),city.strip(),notes.strip())).lastrowid)

    def add_software(self,customer_id: int,name: str,vendor: str="",version: str="",support_scope: str="",notes: str="") -> int:
        if not name.strip():raise ValueError("Applicatienaam is verplicht")
        with self.db.transaction() as conn:
            row=conn.execute("SELECT id FROM customer_software WHERE customer_id=? AND name=? COLLATE NOCASE",(customer_id,name.strip())).fetchone()
            if row:return int(row["id"])
            return int(conn.execute("INSERT INTO customer_software(customer_id,name,vendor,version,support_scope,notes) VALUES(?,?,?,?,?,?)",(customer_id,name.strip(),vendor.strip(),version.strip(),support_scope.strip(),notes.strip())).lastrowid)

    def add_document(self,customer_id: int,title: str,source: Path,document_type: str="Algemeen",notes: str="") -> int:
        if not title.strip() or not source.is_file():raise ValueError("Titel en een bestaand document zijn verplicht")
        with self.db.transaction() as conn:
            row=conn.execute("SELECT id FROM customer_documents WHERE customer_id=? AND title=? COLLATE NOCASE AND original_name=?",(customer_id,title.strip(),source.name)).fetchone()
            if row:return int(row["id"])
        folder=self.storage/str(customer_id); folder.mkdir(parents=True,exist_ok=True)
        stored=f"{uuid4().hex}{source.suffix.lower()}"; target=folder/stored; shutil.copy2(source,target)
        relative=str(Path(str(customer_id))/stored)
        with self.db.transaction() as conn:
            return int(conn.execute("""INSERT INTO customer_documents(customer_id,title,document_type,original_name,relative_path,notes,size_bytes)
                VALUES(?,?,?,?,?,?,?)""",(customer_id,title.strip(),document_type.strip(),source.name,relative,notes.strip(),target.stat().st_size)).lastrowid)

    def document_path(self,document_id: int) -> Path:
        with self.db.transaction() as conn:row=conn.execute("SELECT relative_path FROM customer_documents WHERE id=?",(document_id,)).fetchone()
        if not row:raise ValueError("Document niet gevonden")
        path=(self.storage/row["relative_path"]).resolve(); root=self.storage.resolve()
        if root not in path.parents or not path.is_file():raise ValueError("Het lokale documentbestand ontbreekt")
        return path

    def delete(self,kind: str,row_id: int) -> None:
        table=self.TABLES[kind]; path=self.document_path(row_id) if kind=="documents" else None
        with self.db.transaction() as conn:conn.execute(f"DELETE FROM {table} WHERE id=?",(row_id,))
        if path:path.unlink(missing_ok=True)
