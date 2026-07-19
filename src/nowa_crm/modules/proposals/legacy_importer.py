from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from nowa_crm.core.database import Database
from nowa_crm.modules.assets.service import CustomerAssetsService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.proposals.service import ProposalService


@dataclass(frozen=True)
class LegacyProposalPreview:
    source: Path
    fingerprint: str
    source_number: str
    source_date: str
    title: str
    lines: tuple[dict, ...]
    intake: dict
    licenses: tuple[dict, ...]
    hardware: tuple[dict, ...]
    pdf_file: str
    subtotal_cents: int
    labor_hours: float


class LegacyProposalImportService:
    FORMAT = "nowa-crm-legacy-proposal"

    def __init__(self, db: Database, proposals: ProposalService, operations: OperationsService,
                 assets: CustomerAssetsService):
        self.db, self.proposals, self.operations, self.assets = db, proposals, operations, assets

    def preview(self, source: Path) -> LegacyProposalPreview:
        data = self._read_manifest(source)
        required = ("source_fingerprint", "source_number", "title", "proposal_lines", "intake")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError("Importpakket mist verplichte gegevens: " + ", ".join(missing))
        lines = tuple(self._line(item) for item in data["proposal_lines"])
        subtotal = sum(round(item["quantity"] * item["unit_price_cents"]) for item in lines)
        labor_hours = sum(item["quantity"] for item in lines if item["kind"] == "uren")
        expected = data.get("expected_totals", {})
        if expected.get("subtotal_cents") is not None and int(expected["subtotal_cents"]) != subtotal:
            raise ValueError("Het berekende offertetotaal komt niet overeen met het importpakket.")
        return LegacyProposalPreview(
            source=source,
            fingerprint=str(data["source_fingerprint"]).strip(),
            source_number=str(data["source_number"]).strip(),
            source_date=str(data.get("source_date", "")).strip(),
            title=str(data["title"]).strip(),
            lines=lines,
            intake=dict(data.get("intake") or {}),
            licenses=tuple(dict(item) for item in data.get("licenses", [])),
            hardware=tuple(dict(item) for item in data.get("hardware", [])),
            pdf_file=str(data.get("pdf_file", "")).strip(),
            subtotal_cents=subtotal,
            labor_hours=labor_hours,
        )

    def apply(self, preview: LegacyProposalPreview, customer_id: int) -> dict:
        with self.db.transaction() as conn:
            customer = conn.execute("SELECT id,name FROM customers WHERE id=? AND active=1", (customer_id,)).fetchone()
            duplicate = conn.execute(
                "SELECT proposal_id,customer_id FROM legacy_proposal_imports WHERE source_fingerprint=?",
                (preview.fingerprint,),
            ).fetchone()
        if not customer:
            raise ValueError("De gekozen klant bestaat niet of is niet actief.")
        if duplicate:
            raise ValueError("Deze oude offerte is al geïmporteerd.")
        data = self._read_manifest(preview.source)
        backup = self.db.backup("voor-offerte-import")
        document_id = None
        warnings: list[str] = []
        with TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            pdf_path = self._extract_pdf(preview.source, preview.pdf_file, Path(folder))
            proposal_id = self._create_proposal(customer_id, preview, data)
            self._merge_intake(customer_id, preview.intake, warnings)
            created_licenses = self._merge_licenses(customer_id, preview.licenses, warnings)
            created_hardware = self._merge_hardware(customer_id, preview.hardware, warnings)
            if pdf_path:
                document_id = self.assets.add_document(
                    customer_id,
                    f"Oorspronkelijke offerte {preview.source_number}",
                    pdf_path,
                    "Offerte",
                    f"Historische bron-PDF van {preview.source_date or 'onbekende datum'}",
                )
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO legacy_proposal_imports(
                       source_fingerprint,source_number,source_date,proposal_id,customer_id,document_id,snapshot_json
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (preview.fingerprint, preview.source_number, preview.source_date, proposal_id, customer_id,
                     document_id, json.dumps(data, ensure_ascii=False)),
                )
                conn.execute(
                    """INSERT INTO audit_events(actor,action,entity_type,entity_id,customer_id,reason,metadata)
                       VALUES('offerte-import','legacy_proposal.imported','proposal',?,?,?,?)""",
                    (proposal_id, customer_id, f"Oude offerte {preview.source_number} geïmporteerd",
                     json.dumps({"fingerprint": preview.fingerprint, "document_id": document_id})),
                )
        return {
            "proposal_id": proposal_id,
            "document_id": document_id,
            "lines": len(preview.lines),
            "licenses": created_licenses,
            "hardware": created_hardware,
            "warnings": warnings,
            "backup": backup,
        }

    def _create_proposal(self, customer_id: int, preview: LegacyProposalPreview, data: dict) -> int:
        number = preview.source_number
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM proposals WHERE number=?", (number,)).fetchone():
                number = f"{number}-IMP-{customer_id}"
            cur = conn.execute(
                """INSERT INTO proposals(customer_id,number,title,status,introduction,terms)
                   VALUES(?,?,?,?,?,?)""",
                (customer_id, number, preview.title, "concept", str(data.get("introduction", "")).strip(),
                 str(data.get("terms", "")).strip()),
            )
            proposal_id = int(cur.lastrowid)
            conn.executemany(
                """INSERT INTO proposal_lines(proposal_id,kind,description,quantity,unit_price_cents,sort_order)
                   VALUES(?,?,?,?,?,?)""",
                [(proposal_id, line["kind"], line["description"], line["quantity"], line["unit_price_cents"], index * 10)
                 for index, line in enumerate(preview.lines, 1)],
            )
            self.proposals._recalculate(conn, proposal_id)
        return proposal_id

    def _merge_intake(self, customer_id: int, imported: dict, warnings: list[str]) -> None:
        current = self.operations.intake(customer_id)
        keys = ("users_count", "devices_count", "shared_mailboxes", "teams_count", "sharepoint_sites")
        merged = {}
        for key in keys:
            old, new = int(current.get(key) or 0), int(imported.get(key) or 0)
            merged[key] = old or new
            if old and new and old != new:
                warnings.append(f"Intakeveld {key} bleef op bestaande waarde {old}; offertewaarde was {new}.")
        text_keys = ("migration_source", "desired_date", "scope_notes")
        for key in text_keys:
            old, new = str(current.get(key) or "").strip(), str(imported.get(key) or "").strip()
            merged[key] = old or new
            if old and new and old != new:
                warnings.append(f"Bestaande waarde voor {key} is behouden.")
        self.operations.save_intake(customer_id, *(merged[key] for key in keys), *(merged[key] for key in text_keys))

    def _merge_licenses(self, customer_id: int, items: tuple[dict, ...], warnings: list[str]) -> int:
        existing = self.operations.list_rows("licenses", customer_id)
        created = 0
        for item in items:
            duplicate = next((row for row in existing if row["product"].casefold() == str(item["product"]).casefold()
                              and row["supplier"].casefold() == str(item.get("supplier", "")).casefold()), None)
            if duplicate:
                if duplicate["quantity"] != int(item.get("quantity", 1)):
                    warnings.append(f"Licentie {item['product']} bestond al; bestaand aantal is behouden.")
                continue
            self.operations.save_license(
                customer_id, str(item["product"]), str(item.get("supplier", "")), int(item.get("quantity", 1)),
                int(item.get("unit_price_cents", 0)), bool(item.get("included", False)),
                notes=str(item.get("notes", "")),
            )
            created += 1
        return created

    def _merge_hardware(self, customer_id: int, items: tuple[dict, ...], warnings: list[str]) -> int:
        existing = self.operations.list_rows("hardware", customer_id)
        created = 0
        for item in items:
            signature = (str(item["kind"]).casefold(), str(item.get("brand", "")).casefold(),
                         str(item.get("model", "")).casefold())
            duplicate = next((row for row in existing if
                              (row["kind"].casefold(), row["brand"].casefold(), row["model"].casefold()) == signature), None)
            if duplicate:
                if duplicate["quantity"] != int(item.get("quantity", 1)):
                    warnings.append(f"Hardware {item['brand']} {item['model']} bestond al; bestaand aantal is behouden.")
                continue
            self.operations.save_hardware(
                customer_id, str(item["kind"]), str(item.get("brand", "")), str(item.get("model", "")),
                quantity=int(item.get("quantity", 1)), sales_price_cents=int(item.get("sales_price_cents", 0)),
                notes=str(item.get("notes", "")),
            )
            created += 1
        return created

    @staticmethod
    def _line(item: dict) -> dict:
        line = {
            "kind": str(item.get("kind", "dienst")).strip(),
            "description": str(item.get("description", "")).strip(),
            "quantity": float(item.get("quantity", 0)),
            "unit_price_cents": int(item.get("unit_price_cents", 0)),
        }
        if not line["description"] or line["quantity"] <= 0 or line["unit_price_cents"] < 0:
            raise ValueError("Het importpakket bevat een ongeldige offerteregel.")
        return line

    @classmethod
    def _read_manifest(cls, source: Path) -> dict:
        if not source.is_file() or source.suffix.lower() != ".zip":
            raise ValueError("Selecteer het lokale zipbestand van de geëxtraheerde oude offerte.")
        try:
            with zipfile.ZipFile(source) as archive:
                names = archive.namelist()
                if "proposal_import.json" not in names:
                    raise ValueError("Dit zipbestand bevat geen NOWA-offerte-import.")
                if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                    raise ValueError("Het importpakket bevat een onveilig bestandspad.")
                data = json.loads(archive.read("proposal_import.json").decode("utf-8"))
        except zipfile.BadZipFile as exc:
            raise ValueError("Het gekozen bestand is geen leesbaar zipbestand.") from exc
        if data.get("format") != cls.FORMAT or int(data.get("format_version", 0)) != 1:
            raise ValueError("Deze versie van het offerte-importformaat wordt niet ondersteund.")
        return data

    @staticmethod
    def _extract_pdf(source: Path, pdf_name: str, folder: Path) -> Path | None:
        if not pdf_name:
            return None
        with zipfile.ZipFile(source) as archive:
            if pdf_name not in archive.namelist():
                raise ValueError("De oorspronkelijke offerte-PDF ontbreekt in het importpakket.")
            target = folder / Path(pdf_name).name
            target.write_bytes(archive.read(pdf_name))
            if target.suffix.lower() != ".pdf" or not target.read_bytes().startswith(b"%PDF"):
                raise ValueError("Het gekoppelde offertedocument is geen geldige PDF.")
            return target
