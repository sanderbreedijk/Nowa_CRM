from __future__ import annotations

import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet

from nowa_crm.core.database import Database
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.workspace.service import WorkspaceService
from nowa_crm.modules.assets.service import CustomerAssetsService


class LegacyImportService:
    TABLES=("customers","contacts","customer_users","licenses","hardware_items","project_tasks","notes","proposals","secrets","locations","third_party_software","documents")

    def __init__(self, db: Database, customers: CustomerService, proposals: ProposalService, vault: VaultService,
                 operations: OperationsService, workspace: WorkspaceService, assets: CustomerAssetsService | None = None):
        self.db,self.customers,self.proposals,self.vault=db,customers,proposals,vault
        self.operations,self.workspace=operations,workspace
        self.assets=assets or CustomerAssetsService(db)

    def preview(self, source: Path, key_file: Path | None = None) -> dict:
        self._validate(source)
        with sqlite3.connect(source) as conn:
            available={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts={name:(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] if name in available else 0) for name in self.TABLES}
        warnings=[]
        if counts["secrets"] and not (key_file and key_file.is_file()):
            warnings.append("Kluisitems worden overgeslagen: selecteer de oude secret.key.")
        return {"source":str(source),"counts":counts,"warnings":warnings,"total":sum(counts.values())}

    def import_database(self, source: Path, key_file: Path | None = None) -> dict:
        preview=self.preview(source,key_file); backup=self.db.backup("voor-oude-workspace-import")
        report={"created":{name:0 for name in self.TABLES},"skipped":{name:0 for name in self.TABLES},
                "warnings":list(preview["warnings"]),"backup":str(backup)}
        legacy=sqlite3.connect(source); legacy.row_factory=sqlite3.Row
        try:
            customer_map=self._customers(legacy,report)
            self._contacts(legacy,customer_map,report)
            self._operations(legacy,customer_map,report)
            self._notes(legacy,customer_map,report)
            self._proposals(legacy,customer_map,report)
            self._secrets(legacy,customer_map,key_file,report)
            self._assets(legacy,customer_map,source.parent,report)
        finally:legacy.close()
        return report

    def _customers(self, conn, report):
        mapping={}; existing=self.customers.search()
        by_number={x.customer_number.casefold():x.id for x in existing}; by_name={x.name.casefold():x.id for x in existing}
        for row in self._rows(conn,"customers"):
            number=(row["customer_number"] or "").strip(); name=(row["name"] or "").strip()
            target=by_number.get(number.casefold()) or by_name.get(name.casefold())
            if target:report["skipped"]["customers"]+=1
            else:
                target=self.customers.create(number or f"LEG-{row['id']:05d}",name or f"Oude klant {row['id']}",
                    row["email"] or "",row["phone"] or "",row["street"] or row["address"] or "",
                    row["postcode"] or "",row["city"] or "",row["notes"] or "")
                report["created"]["customers"]+=1; by_number[number.casefold()]=target; by_name[name.casefold()]=target
            mapping[row["id"]]=target
        return mapping

    def _contacts(self,conn,mapping,report):
        for row in self._rows(conn,"contacts"):
            customer_id=mapping.get(row["customer_id"])
            if not customer_id:report["skipped"]["contacts"]+=1; continue
            present=self.customers.contacts(customer_id)
            duplicate=any((row["email"] and x.email.casefold()==row["email"].casefold()) or
                          (row["phone"] and x.phone==row["phone"]) or x.name.casefold()==(row["name"] or "").casefold() for x in present)
            if duplicate:report["skipped"]["contacts"]+=1
            else:self.customers.save_contact(customer_id,row["name"] or "Contact",row["role"] or "",row["email"] or "",row["phone"] or ""); report["created"]["contacts"]+=1

    def _operations(self,conn,mapping,report):
        specs=(("customer_users","users",lambda r,c:self.operations.save_user(c,r["display_name"] or "Gebruiker",r["upn"] or "",r["department"] or "",r["license_name"] or "",bool(r["mfa_method"]),str(r["status"] or "").lower()!="inactief")),
               ("licenses","licenses",lambda r,c:self.operations.save_license(c,r["product"] or "Licentie",r["supplier"] or "",int(r["quantity"] or 1),round(float(r["price_month"] or 0)*100),bool(r["included_in_price"]))),
               ("hardware_items","hardware",lambda r,c:self.operations.save_hardware(c,r["category"] or "Hardware",r["brand"] or "",r["model"] or "",quantity=int(r["quantity"] or 1),sales_price_cents=round(float(r["sell_price"] or 0)*100))),
               ("project_tasks","tasks",lambda r,c:self.operations.save_task(c,r["phase"] or "",r["task_name"] or "Taak",r["owner"] or "NOWA",r["start_date"] or "",r["end_date"] or "",r["dependency"] or "",r["status"] or "Gepland",r["notes"] or "")))
        for table,kind,save in specs:
            for row in self._rows(conn,table):
                customer_id=mapping.get(row["customer_id"])
                if not customer_id:report["skipped"][table]+=1; continue
                existing=self.operations.list_rows(kind,customer_id)
                duplicate=(
                    kind=="users" and any((x["user_principal_name"] and x["user_principal_name"].casefold()==(row["upn"] or "").casefold()) or x["display_name"].casefold()==(row["display_name"] or "").casefold() for x in existing)
                    or kind=="licenses" and any(x["product"].casefold()==(row["product"] or "").casefold() for x in existing)
                    or kind=="hardware" and any((x["kind"],x["brand"],x["model"])==((row["category"] or ""),(row["brand"] or ""),(row["model"] or "")) for x in existing)
                    or kind=="tasks" and any((x["phase"],x["task_name"])==((row["phase"] or ""),(row["task_name"] or "")) for x in existing))
                if duplicate:report["skipped"][table]+=1; continue
                save(row,customer_id); report["created"][table]+=1

    def _notes(self,conn,mapping,report):
        for row in self._rows(conn,"notes"):
            customer_id=mapping.get(row["customer_id"])
            duplicate=customer_id and any(x["subject"]==(row["title"] or "Oude notitie") and x["body"]==(row["body"] or "") for x in self.workspace.notes(customer_id))
            if duplicate:report["skipped"]["notes"]+=1
            elif customer_id:self.workspace.add_note(customer_id,row["title"] or "Oude notitie",row["body"] or ""); report["created"]["notes"]+=1
            else:report["skipped"]["notes"]+=1

    def _proposals(self,conn,mapping,report):
        for row in self._rows(conn,"proposals"):
            customer_id=mapping.get(row["customer_id"])
            title=row["title"] or "Geïmporteerde offerte"
            duplicate=customer_id and any(x.customer_id==customer_id and x.title==title for x in self.proposals.list())
            if duplicate:report["skipped"]["proposals"]+=1
            elif customer_id:self.proposals.create(customer_id,title); report["created"]["proposals"]+=1
            else:report["skipped"]["proposals"]+=1

    def _secrets(self,conn,mapping,key_file,report):
        rows=self._rows(conn,"secrets")
        if not rows:return
        if not key_file or not key_file.is_file():report["skipped"]["secrets"]+=len(rows); return
        cipher=Fernet(key_file.read_bytes().strip())
        for row in rows:
            customer_id=mapping.get(row["customer_id"])
            try:secret=cipher.decrypt(row["encrypted_value"]).decode("utf-8")
            except Exception:report["skipped"]["secrets"]+=1; report["warnings"].append(f"Kluisitem {row['id']} kon niet worden ontsleuteld."); continue
            duplicate=customer_id and any(x["label"]==(row["label"] or "Kluisitem") and x["username"]==(row["username"] or "") for x in self.vault.search(customer_id))
            if duplicate:report["skipped"]["secrets"]+=1
            elif customer_id:self.vault.add(customer_id,row["label"] or "Kluisitem",row["username"] or "",secret,row["category"] or "Account",row["url"] or "",row["vault_path"] or "",row["host"] or "",row["notes"] or ""); report["created"]["secrets"]+=1
            else:report["skipped"]["secrets"]+=1

    def _assets(self,conn,mapping,source_folder,report):
        for row in self._rows(conn,"locations"):
            customer_id=mapping.get(row["customer_id"])
            before={x["id"] for x in self.assets.list("locations",customer_id)} if customer_id else set()
            if customer_id:
                item=self.assets.add_location(customer_id,row["name"] or "Locatie",row["address"] or "",row["city"] or "",row["notes"] or "")
                report["skipped" if item in before else "created"]["locations"]+=1
            else:report["skipped"]["locations"]+=1
        for row in self._rows(conn,"third_party_software"):
            customer_id=mapping.get(row["customer_id"])
            before={x["id"] for x in self.assets.list("software",customer_id)} if customer_id else set()
            if customer_id:
                item=self.assets.add_software(customer_id,row["name"] or "Applicatie",row["vendor"] or "",support_scope=row["support_scope"] or "")
                report["skipped" if item in before else "created"]["third_party_software"]+=1
            else:report["skipped"]["third_party_software"]+=1
        for row in self._rows(conn,"documents"):
            customer_id=mapping.get(row["customer_id"]); candidate=Path(row["file_path"] or "")
            if not candidate.is_absolute():candidate=source_folder/candidate
            if customer_id and candidate.is_file():
                before={x["id"] for x in self.assets.list("documents",customer_id)}
                item=self.assets.add_document(customer_id,row["title"] or candidate.stem,candidate,row["document_type"] or "Algemeen",row["notes"] or "")
                report["skipped" if item in before else "created"]["documents"]+=1
            else:
                report["skipped"]["documents"]+=1
                if row["file_path"]:report["warnings"].append(f"Document niet gevonden: {row['file_path']}")

    @staticmethod
    def _rows(conn,table):
        available={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return conn.execute(f"SELECT * FROM {table}").fetchall() if table in available else []

    @staticmethod
    def _validate(source):
        if not source.is_file():raise ValueError("Selecteer een bestaande oude NOWA-database.")
        try:
            with sqlite3.connect(f"file:{source}?mode=ro",uri=True) as conn:
                tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.Error as exc:raise ValueError("Dit bestand is geen leesbare SQLite-database.") from exc
        if "customers" not in tables:raise ValueError("Dit is geen herkende NOWA Workspace-database.")
