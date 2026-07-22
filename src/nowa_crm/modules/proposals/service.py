from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

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
    introduction: str
    terms: str
    sections_json: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProposalLine:
    id: int
    proposal_id: int
    kind: str
    description: str
    quantity: float
    unit_price_cents: int
    sort_order: int
    active: int
    billing_period: str
    group_name: str

    @property
    def line_total_cents(self) -> int:
        return round(self.quantity * self.unit_price_cents)


class ProposalService:
    STATUSES = ("concept", "verzonden", "geaccepteerd", "afgewezen", "verlopen")
    SECTION_TITLES = {
        "management_summary": "Managementsamenvatting", "current_situation": "Huidige situatie",
        "solution": "Voorgestelde oplossing", "planning": "Planning en oplevering",
        "activities": "Werkzaamheden", "scope": "Scope en uitsluitingen",
        "privacy": "AVG en gegevensbescherming", "disclaimer": "Disclaimer",
    }

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
                """SELECT p.id,p.customer_id,c.name customer_name,p.number,p.title,p.status,p.revision,p.total_cents,p.introduction,p.terms,p.sections_json,p.created_at,p.updated_at
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
                """SELECT p.id,p.customer_id,c.name customer_name,p.number,p.title,p.status,p.revision,p.total_cents,p.introduction,p.terms,p.sections_json,p.created_at,p.updated_at
                   FROM proposals p JOIN customers c ON c.id=p.customer_id WHERE p.id=?""", (proposal_id,)
            ).fetchone()
        return Proposal(**dict(row)) if row else None

    def lines(self, proposal_id: int) -> list[ProposalLine]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT id,proposal_id,kind,description,quantity,unit_price_cents,sort_order,active,billing_period,group_name FROM proposal_lines WHERE proposal_id=? ORDER BY sort_order,id",
                (proposal_id,),
            ).fetchall()
        return [ProposalLine(**dict(row)) for row in rows]

    def add_line(self, proposal_id: int, kind: str, description: str, quantity: float, unit_price_cents: int,
                 billing_period: str = "eenmalig", group_name: str = "") -> int:
        if not description.strip(): raise ValueError("Omschrijving is verplicht")
        if quantity <= 0: raise ValueError("Aantal moet groter zijn dan nul")
        if unit_price_cents < 0: raise ValueError("Prijs mag niet negatief zijn")
        with self.db.transaction() as conn:
            order = int(conn.execute("SELECT COALESCE(MAX(sort_order),0)+10 FROM proposal_lines WHERE proposal_id=?",(proposal_id,)).fetchone()[0])
            cur = conn.execute(
                "INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,sort_order,billing_period,group_name) VALUES(?,?,?,?,?,?,?,?)",
                (proposal_id,kind,description.strip(),quantity,unit_price_cents,order,billing_period,group_name.strip()),
            )
            line_id=int(cur.lastrowid); self._recalculate(conn,proposal_id); return line_id

    def update_line(self, line_id: int, kind: str, description: str, quantity: float,
                    unit_price_cents: int, billing_period: str, group_name: str) -> None:
        if not description.strip(): raise ValueError("Omschrijving is verplicht")
        if quantity <= 0: raise ValueError("Aantal moet groter zijn dan nul")
        if unit_price_cents < 0: raise ValueError("Prijs mag niet negatief zijn")
        if billing_period not in ("eenmalig", "maandelijks"): raise ValueError("Ongeldige facturatieperiode")
        with self.db.transaction() as conn:
            row=conn.execute("SELECT proposal_id FROM proposal_lines WHERE id=?",(line_id,)).fetchone()
            if not row: raise KeyError(line_id)
            conn.execute("""UPDATE proposal_lines SET kind=?,description=?,quantity=?,unit_price_cents=?,
                            billing_period=?,group_name=? WHERE id=?""",
                         (kind,description.strip(),quantity,unit_price_cents,billing_period,group_name.strip(),line_id))
            self._recalculate(conn,int(row["proposal_id"]))

    def duplicate_line(self, line_id: int) -> int:
        with self.db.transaction() as conn:
            source=conn.execute("SELECT * FROM proposal_lines WHERE id=?",(line_id,)).fetchone()
            if not source: raise KeyError(line_id)
            order=int(source["sort_order"])+5
            conn.execute("UPDATE proposal_lines SET sort_order=sort_order+10 WHERE proposal_id=? AND sort_order>?",(source["proposal_id"],source["sort_order"]))
            cur=conn.execute("""INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,
                               sort_order,catalog_item_id,active,billing_period,group_name)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""",
                             (source["proposal_id"],source["kind"],source["description"],source["quantity"],
                              source["unit_price_cents"],order,source["catalog_item_id"],source["active"],
                              source["billing_period"],source["group_name"]))
            self._recalculate(conn,int(source["proposal_id"]));return int(cur.lastrowid)

    def catalog(self, query: str = "", include_inactive: bool = False) -> list[dict]:
        term=f"%{query.strip()}%"; clauses=[]; values=[]
        if not include_inactive: clauses.append("active=1")
        if query.strip(): clauses.append("(code LIKE ? OR name LIKE ? OR category LIKE ?)");values.extend((term,term,term))
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute("SELECT id,code,name,category,unit,unit_price_cents,active,notes FROM product_catalog"+where+" ORDER BY category,name COLLATE NOCASE",values)]

    def save_catalog_item(self, code: str, name: str, category: str, unit: str, unit_price_cents: int, notes: str = "", item_id: int | None = None) -> int:
        if not code.strip() or not name.strip():raise ValueError("Artikelcode en naam zijn verplicht")
        if unit_price_cents<0:raise ValueError("Prijs mag niet negatief zijn")
        with self.db.transaction() as conn:
            if item_id:
                conn.execute("UPDATE product_catalog SET code=?,name=?,category=?,unit=?,unit_price_cents=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(code.strip(),name.strip(),category,unit.strip() or "stuk",unit_price_cents,notes.strip(),item_id));return item_id
            cur=conn.execute("INSERT INTO product_catalog(code,name,category,unit,unit_price_cents,notes) VALUES(?,?,?,?,?,?)",(code.strip(),name.strip(),category,unit.strip() or "stuk",unit_price_cents,notes.strip()));return int(cur.lastrowid)

    def add_catalog_line(self, proposal_id: int, catalog_item_id: int, quantity: float = 1) -> int:
        with self.db.transaction() as conn:item=conn.execute("SELECT * FROM product_catalog WHERE id=? AND active=1",(catalog_item_id,)).fetchone()
        if not item:raise ValueError("Catalogusartikel niet gevonden of niet actief")
        line_id=self.add_line(proposal_id,item["category"].lower(),item["name"],quantity,item["unit_price_cents"])
        with self.db.transaction() as conn:conn.execute("UPDATE proposal_lines SET catalog_item_id=? WHERE id=?",(catalog_item_id,line_id))
        return line_id

    def save_texts(self, proposal_id: int, introduction: str, terms: str) -> None:
        with self.db.transaction() as conn:conn.execute("UPDATE proposals SET introduction=?,terms=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(introduction.strip(),terms.strip(),proposal_id))

    def sections(self, proposal_id: int) -> dict[str, str]:
        proposal = self.get(proposal_id)
        stored = json.loads(proposal.sections_json or "{}") if proposal else {}
        defaults = {
            "management_summary": proposal.introduction if proposal else "",
            "current_situation": "De huidige omgeving en uitgangspunten zijn tijdens de klantintake vastgelegd.",
            "solution": "NOWA levert, configureert, test en documenteert de overeengekomen oplossing.",
            "planning": "De definitieve planning wordt in overleg met de opdrachtgever vastgesteld.",
            "activities": "De werkzaamheden worden gecontroleerd uitgevoerd en met de klant opgeleverd.",
            "scope": "Alleen de beschreven werkzaamheden en aantallen vallen binnen deze offerte.",
            "privacy": "Persoonsgegevens worden uitsluitend verwerkt voor uitvoering, beheer en ondersteuning.",
            "disclaimer": proposal.terms if proposal else "",
        }
        defaults.update({k: str(v) for k, v in stored.items() if k in self.SECTION_TITLES})
        return defaults

    def save_sections(self, proposal_id: int, sections: dict[str, str]) -> None:
        payload={k:str(sections.get(k," ")).strip() for k in self.SECTION_TITLES}
        with self.db.transaction() as conn:
            conn.execute("UPDATE proposals SET sections_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps(payload,ensure_ascii=False),proposal_id))

    def set_line_active(self, line_id: int, active: bool) -> None:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT proposal_id FROM proposal_lines WHERE id=?",(line_id,)).fetchone()
            if not row: raise KeyError(line_id)
            conn.execute("UPDATE proposal_lines SET active=? WHERE id=?",(int(active),line_id));self._recalculate(conn,int(row[0]))

    def move_line(self, line_id: int, direction: int) -> None:
        with self.db.transaction() as conn:
            line=conn.execute("SELECT proposal_id,sort_order FROM proposal_lines WHERE id=?",(line_id,)).fetchone()
            if not line: raise KeyError(line_id)
            op="<" if direction<0 else ">"; order="DESC" if direction<0 else "ASC"
            other=conn.execute(f"SELECT id,sort_order FROM proposal_lines WHERE proposal_id=? AND sort_order {op} ? ORDER BY sort_order {order},id {order} LIMIT 1",(line["proposal_id"],line["sort_order"])).fetchone()
            if other:
                conn.execute("UPDATE proposal_lines SET sort_order=? WHERE id=?",(other["sort_order"],line_id))
                conn.execute("UPDATE proposal_lines SET sort_order=? WHERE id=?",(line["sort_order"],other["id"]))

    def add_customer_assets(self, proposal_id: int) -> dict[str,int]:
        proposal=self.get(proposal_id)
        if not proposal: raise ValueError("Offerte niet gevonden")
        added={"licenses":0,"hardware":0}
        with self.db.transaction() as conn:
            licenses=conn.execute("SELECT * FROM customer_licenses WHERE customer_id=? AND included_in_proposal=1",(proposal.customer_id,)).fetchall()
            hardware=conn.execute("SELECT * FROM customer_hardware WHERE customer_id=?",(proposal.customer_id,)).fetchall()
        existing={x.description.lower() for x in self.lines(proposal_id)}
        for x in licenses:
            if x["product"].lower() not in existing:
                self.add_line(proposal_id,"licentie",x["product"],x["quantity"],x["unit_price_cents"],"maandelijks","Licenties");added["licenses"]+=1
        for x in hardware:
            description=" ".join(v for v in (x["brand"],x["model"],x["kind"]) if v).strip()
            if description and description.lower() not in existing:
                self.add_line(proposal_id,"hardware",description,x["quantity"],x["sales_price_cents"],"eenmalig","Hardware");added["hardware"]+=1
        return added

    def calculate_from_intake(self, proposal_id: int, hourly_rate_cents: int = 9400) -> float:
        proposal=self.get(proposal_id)
        with self.db.transaction() as conn:
            intake=conn.execute("SELECT * FROM project_intakes WHERE customer_id=?",(proposal.customer_id,)).fetchone() if proposal else None
            if not intake: raise ValueError("Vul eerst de projectintake van deze klant in")
            conn.execute("DELETE FROM proposal_lines WHERE proposal_id=? AND group_name='Automatische calculatie'",(proposal_id,))
        users=float(intake["users_count"] or 0);devices=float(intake["devices_count"] or 0)
        shared=float(intake["shared_mailboxes"] or 0);sites=float(intake["sharepoint_sites"] or 0)
        # Exacte commerciële normtijden uit het oorspronkelijke NOWA Workspace-pakket.
        exchange=1.5+users*.35+shared*.25+.75  # één domein als veilige standaard
        sharepoint=4.0+sites*1.5+(sites*2)*.4+((sites+2) if sites else 0)*.5+(2 if sites else 0)*.75
        mfa=1.0+users*.10+(2 if users else 0)*.5
        hardware=devices*1.25
        work=[("Exchange Online inrichting en migratie",exchange),("SharePoint inrichting",sharepoint),
              ("MFA en hardware tokens",mfa),("Hardware implementatie en werkplekken",hardware),
              ("Projectvoorbereiding en technisch ontwerp",6.0),("Documentatie, oplevering en instructie",12.0)]
        base=sum(hours for _,hours in work)
        management=base*.10;buffer=base*.08;total_before_minimum=base+management+buffer
        work.append(("Projectmanagement, afstemming en buffer",management+buffer))
        if total_before_minimum<56:work.append(("Afronding minimale projectomvang",56-total_before_minimum))
        total=0.0
        for description,hours in work:
            rounded=max(.25,round(hours*4)/4);total+=rounded
            self.add_line(proposal_id,"uren",description,rounded,hourly_rate_cents,"eenmalig","Automatische calculatie")
        return total

    def create_revision(self, proposal_id: int, label: str = "") -> int:
        proposal=self.get(proposal_id)
        if not proposal: raise ValueError("Offerte niet gevonden")
        revision=proposal.revision+1
        snapshot={"proposal":proposal.__dict__,"lines":[x.__dict__ for x in self.lines(proposal_id)],"sections":self.sections(proposal_id)}
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO proposal_revisions(proposal_id,revision_number,label,snapshot_json) VALUES(?,?,?,?)",(proposal_id,revision,label.strip(),json.dumps(snapshot,ensure_ascii=False)))
            conn.execute("UPDATE proposals SET revision=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(revision,proposal_id))
        return revision

    def revisions(self, proposal_id: int) -> list[dict]:
        with self.db.transaction() as conn:return [dict(x) for x in conn.execute("SELECT id,revision_number,label,created_at FROM proposal_revisions WHERE proposal_id=? ORDER BY revision_number DESC",(proposal_id,))]

    def restore_revision(self, proposal_id: int, revision_id: int) -> int:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT snapshot_json FROM proposal_revisions WHERE id=? AND proposal_id=?",(revision_id,proposal_id)).fetchone()
        if not row: raise ValueError("Revisie niet gevonden")
        snapshot=json.loads(row["snapshot_json"]);proposal=snapshot.get("proposal",{});lines=snapshot.get("lines",[])
        new_revision=self.create_revision(proposal_id,"Automatische back-up voor terugzetten")
        with self.db.transaction() as conn:
            conn.execute("""UPDATE proposals SET title=?,status=?,introduction=?,terms=?,sections_json=?,updated_at=CURRENT_TIMESTAMP
                            WHERE id=?""",(proposal.get("title","Offerte"),proposal.get("status","concept"),
                            proposal.get("introduction",""),proposal.get("terms",""),
                            json.dumps(snapshot.get("sections",{}),ensure_ascii=False),proposal_id))
            conn.execute("DELETE FROM proposal_lines WHERE proposal_id=?",(proposal_id,))
            conn.executemany("""INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,
                               sort_order,active,billing_period,group_name) VALUES(?,?,?,?,?,?,?,?,?)""",
                             [(proposal_id,x.get("kind","dienst"),x.get("description",""),x.get("quantity",1),
                               x.get("unit_price_cents",0),x.get("sort_order",i*10),x.get("active",1),
                               x.get("billing_period","eenmalig"),x.get("group_name","")) for i,x in enumerate(lines,1)])
            self._recalculate(conn,proposal_id)
        return new_revision

    def validate(self, proposal_id: int) -> list[str]:
        proposal=self.get(proposal_id);lines=[x for x in self.lines(proposal_id) if x.active]
        warnings=[]
        if not lines:warnings.append("De offerte bevat geen actieve regels.")
        if any(x.unit_price_cents==0 for x in lines):warnings.append("Een of meer actieve regels hebben een prijs van EUR 0,00.")
        if proposal and not self.sections(proposal_id)["management_summary"]:warnings.append("De managementsamenvatting is leeg.")
        return warnings

    def duplicate(self, proposal_id: int) -> int:
        source=self.get(proposal_id)
        if not source:raise ValueError("Offerte niet gevonden")
        new_id=self.create(source.customer_id,f"Kopie van {source.title}")
        with self.db.transaction() as conn:
            conn.execute("UPDATE proposals SET introduction=?,terms=?,sections_json=? WHERE id=?",(source.introduction,source.terms,source.sections_json,new_id))
            conn.execute("INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,sort_order,catalog_item_id,active,billing_period,group_name) SELECT ?,kind,description,quantity,unit_price_cents,sort_order,catalog_item_id,active,billing_period,group_name FROM proposal_lines WHERE proposal_id=?",(new_id,proposal_id));self._recalculate(conn,new_id)
        return new_id

    def save_as_template(self, proposal_id: int, name: str) -> int:
        proposal=self.get(proposal_id)
        if not proposal or not name.strip():raise ValueError("Naam voor het sjabloon is verplicht")
        with self.db.transaction() as conn:
            cur=conn.execute("INSERT INTO proposal_templates(name,description,introduction,terms) VALUES(?,?,?,?)",(name.strip(),f"Gebaseerd op {proposal.number}",proposal.introduction,proposal.terms));template_id=int(cur.lastrowid)
            conn.execute("INSERT INTO proposal_template_lines(template_id,kind,description,quantity,unit_price_cents,sort_order) SELECT ?,kind,description,quantity,unit_price_cents,sort_order FROM proposal_lines WHERE proposal_id=?",(template_id,proposal_id));return template_id

    def delete_line(self, line_id: int) -> None:
        with self.db.transaction() as conn:
            row=conn.execute("SELECT proposal_id FROM proposal_lines WHERE id=?",(line_id,)).fetchone()
            if not row: raise KeyError(line_id)
            conn.execute("DELETE FROM proposal_lines WHERE id=?",(line_id,)); self._recalculate(conn,int(row[0]))

    def _recalculate(self, conn, proposal_id: int) -> None:
        total=conn.execute("SELECT COALESCE(SUM(ROUND(quantity*unit_price_cents)),0) FROM proposal_lines WHERE proposal_id=? AND active=1 AND billing_period='eenmalig'",(proposal_id,)).fetchone()[0]
        conn.execute("UPDATE proposals SET total_cents=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(int(total),proposal_id))

    def totals(self, proposal_id: int, vat_rate: float = 0.21) -> dict[str,int]:
        proposal=self.get(proposal_id)
        subtotal=proposal.total_cents if proposal else 0; vat=round(subtotal*vat_rate)
        return {"subtotal_cents":subtotal,"vat_cents":vat,"total_cents":subtotal+vat}

    def monthly_total(self, proposal_id: int) -> int:
        with self.db.transaction() as conn:return int(conn.execute("SELECT COALESCE(SUM(ROUND(quantity*unit_price_cents)),0) FROM proposal_lines WHERE proposal_id=? AND active=1 AND billing_period='maandelijks'",(proposal_id,)).fetchone()[0])

    def count_open(self) -> int:
        with self.db.transaction() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM proposals WHERE status IN ('concept','verzonden')").fetchone()[0])

    def templates(self) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,name,description,introduction,terms,sections_json,calculation_json "
                "FROM proposal_templates ORDER BY name COLLATE NOCASE"
            )]

    def template_configuration(self, template_id: int) -> dict:
        with self.db.transaction() as conn:
            row=conn.execute(
                "SELECT name,sections_json,calculation_json FROM proposal_templates WHERE id=?",
                (template_id,),
            ).fetchone()
        if not row:
            raise ValueError("Offertesjabloon niet gevonden")
        return {
            "name": row["name"],
            "sections": json.loads(row["sections_json"] or "[]"),
            "calculation": json.loads(row["calculation_json"] or "{}"),
        }

    def apply_template(self, proposal_id: int, template_id: int) -> None:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT kind,description,quantity,unit_price_cents,sort_order FROM proposal_template_lines WHERE template_id=? ORDER BY sort_order,id", (template_id,)).fetchall()
            if not rows: raise ValueError("Dit offertesjabloon bevat geen regels")
            start = int(conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM proposal_lines WHERE proposal_id=?", (proposal_id,)).fetchone()[0])
            conn.executemany("INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,sort_order) VALUES(?,?,?,?,?,?)",
                             [(proposal_id, row["kind"], row["description"], row["quantity"], row["unit_price_cents"], start + row["sort_order"]) for row in rows])
            self._recalculate(conn, proposal_id)
            template=conn.execute("SELECT introduction,terms FROM proposal_templates WHERE id=?",(template_id,)).fetchone()
            if template:conn.execute("UPDATE proposals SET introduction=CASE WHEN introduction='' THEN ? ELSE introduction END,terms=CASE WHEN terms='' THEN ? ELSE terms END WHERE id=?",(template["introduction"],template["terms"],proposal_id))
