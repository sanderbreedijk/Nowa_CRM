from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from nowa_crm.core.database import Database


@dataclass(frozen=True)
class ImportPreview:
    source: Path
    rows: tuple[dict, ...]
    created: int
    updated: int
    archived: int
    unchanged: int
    changes: tuple[dict, ...]
    warnings: tuple[str, ...]


class CustomerImportService:
    """Synchroniseert een Excel-adressenlijst met klantnummer als vaste sleutel."""

    HEADER_MAP = {
        "relatiecode": "customer_number",
        "klantnummer": "customer_number",
        "naam": "name",
        "contactpersoon": "contact_name",
        "adres": "street",
        "postcode": "postal_code",
        "plaats": "city",
        "landnaam": "country",
        "land": "country",
        "telefoon": "phone",
        "mobieletelefoon": "mobile_phone",
        "mobiel": "mobile_phone",
        "email": "email",
        "e-mail": "email",
    }
    COMPARE_FIELDS = ("name", "email", "phone", "mobile_phone", "street", "postal_code", "city", "country")

    def __init__(self, db: Database, actor: str):
        self.db, self.actor = db, actor

    def preview(self, source: Path) -> ImportPreview:
        rows = tuple(self._read_xlsx(source))
        if not rows:
            raise ValueError("Het Excel-bestand bevat geen klanten.")
        numbers = [row["customer_number"] for row in rows]
        duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
        if duplicates:
            raise ValueError("Dubbele klantnummers in import: " + ", ".join(duplicates[:10]))
        with self.db.transaction() as conn:
            existing = {str(row["customer_number"]): dict(row) for row in conn.execute(
                "SELECT customer_number,name,email,phone,mobile_phone,street,postal_code,city,country,active FROM customers"
            )}
        created = updated = unchanged = 0
        changes = []
        for row in rows:
            current = existing.get(row["customer_number"])
            if current is None:
                created += 1
                changes.append({"action": "Nieuw", "customer_number": row["customer_number"],
                                "name": row["name"], "fields": "Alle klantgegevens"})
            elif not current["active"] or any((current[field] or "").strip() != row[field] for field in self.COMPARE_FIELDS):
                updated += 1
                fields = [field for field in self.COMPARE_FIELDS if (current[field] or "").strip() != row[field]]
                if not current["active"]:
                    fields.insert(0, "opnieuw actief")
                changes.append({"action": "Bijwerken", "customer_number": row["customer_number"],
                                "name": row["name"], "fields": ", ".join(fields)})
            else:
                unchanged += 1
        imported = set(numbers)
        archived_rows = [(number, item) for number, item in existing.items() if bool(item["active"]) and number not in imported]
        for number, item in archived_rows:
            changes.append({"action": "Deactiveren", "customer_number": number,
                            "name": item["name"], "fields": "Niet aanwezig in import"})
        archived = len(archived_rows)
        active_count = sum(bool(item["active"]) for item in existing.values())
        warnings = []
        if active_count and archived / active_count >= .20:
            warnings.append(f"Let op: {archived} van {active_count} actieve klanten ({archived / active_count:.0%}) ontbreken.")
        if len(rows) < 5 and active_count >= 20:
            warnings.append("De import bevat opvallend weinig regels ten opzichte van het huidige klantenbestand.")
        return ImportPreview(source, rows, created, updated, archived, unchanged, tuple(changes), tuple(warnings))

    def apply(self, preview: ImportPreview) -> dict:
        backup = self.db.backup("voor-klantimport")
        imported_numbers = {row["customer_number"] for row in preview.rows}
        with self.db.transaction() as conn:
            run_id = int(conn.execute("""INSERT INTO customer_import_runs
                (source_name,source_rows,created_count,updated_count,archived_count,unchanged_count,
                 performed_by,backup_path,status)
                VALUES(?,?,?,?,?,?,?,?,'uitgevoerd')""",
                (preview.source.name, len(preview.rows), preview.created, preview.updated, preview.archived,
                 preview.unchanged, self.actor, str(backup))).lastrowid)
            for row in preview.rows:
                current = conn.execute("SELECT * FROM customers WHERE customer_number=?", (row["customer_number"],)).fetchone()
                values = tuple(row[field] for field in ("name", "email", "phone", "mobile_phone", "street", "postal_code", "city", "country"))
                if current:
                    before = self._customer_state(dict(current))
                    customer_id = int(current["id"])
                    conn.execute("""UPDATE customers SET name=?,email=?,phone=?,mobile_phone=?,street=?,postal_code=?,city=?,country=?,
                        active=1,updated_at=CURRENT_TIMESTAMP WHERE id=?""", (*values, customer_id))
                    changed = [field for field in self.COMPARE_FIELDS if (before.get(field) or "") != row[field]]
                    if not before["active"]:
                        changed.insert(0, "active")
                    action = "bijgewerkt" if changed else "ongewijzigd"
                else:
                    before = {}
                    customer_id = int(conn.execute("""INSERT INTO customers
                        (customer_number,name,email,phone,mobile_phone,street,postal_code,city,country)
                        VALUES(?,?,?,?,?,?,?,?,?)""", (row["customer_number"], *values)).lastrowid)
                    changed, action = list(self.COMPARE_FIELDS), "nieuw"
                if row["contact_name"]:
                    contact = conn.execute(
                        "SELECT id FROM contacts WHERE customer_id=? AND role='Contactpersoon (import)' ORDER BY id LIMIT 1",
                        (customer_id,),
                    ).fetchone()
                    if contact:
                        conn.execute("UPDATE contacts SET name=?,email=?,phone=? WHERE id=?",
                                     (row["contact_name"], row["email"], row["mobile_phone"] or row["phone"], contact["id"]))
                    else:
                        conn.execute("INSERT INTO contacts(customer_id,name,role,email,phone) VALUES(?,?,'Contactpersoon (import)',?,?)",
                                     (customer_id, row["contact_name"], row["email"], row["mobile_phone"] or row["phone"]))
                after = self._customer_state(dict(conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()))
                conn.execute("""INSERT INTO customer_import_changes
                    (run_id,customer_id,customer_number,customer_name,action,changed_fields,before_json,after_json)
                    VALUES(?,?,?,?,?,?,?,?)""", (run_id, customer_id, row["customer_number"], row["name"], action,
                    ", ".join(changed), json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))
            placeholders = ",".join("?" for _ in imported_numbers)
            archived_rows = conn.execute(
                f"SELECT * FROM customers WHERE active=1 AND customer_number NOT IN ({placeholders})",
                tuple(sorted(imported_numbers))).fetchall()
            for current in archived_rows:
                before = self._customer_state(dict(current))
                conn.execute("UPDATE customers SET active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (current["id"],))
                after = dict(before); after["active"] = 0
                conn.execute("""INSERT INTO customer_import_changes
                    (run_id,customer_id,customer_number,customer_name,action,changed_fields,before_json,after_json)
                    VALUES(?,?,?,?,?,'active',?,?)""", (run_id, current["id"], current["customer_number"],
                    current["name"], "gedeactiveerd", json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))
        return {"run_id": run_id, "backup": backup, "created": preview.created, "updated": preview.updated,
                "archived": preview.archived, "unchanged": preview.unchanged}

    def history(self) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM customer_import_runs ORDER BY id DESC LIMIT 50").fetchall()]

    def changes(self, run_id: int) -> list[dict]:
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM customer_import_changes WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]

    def undo(self, run_id: int) -> dict:
        with self.db.transaction() as conn:
            latest = conn.execute("SELECT * FROM customer_import_runs WHERE status='uitgevoerd' ORDER BY id DESC LIMIT 1").fetchone()
            if not latest or int(latest["id"]) != run_id:
                raise ValueError("Alleen de laatst uitgevoerde, nog niet herstelde import kan ongedaan worden gemaakt.")
            changes = conn.execute("SELECT * FROM customer_import_changes WHERE run_id=? ORDER BY id DESC", (run_id,)).fetchall()
            for change in changes:
                before = json.loads(change["before_json"])
                if not before:
                    conn.execute("UPDATE customers SET active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (change["customer_id"],))
                    continue
                fields = ("name", "email", "phone", "mobile_phone", "street", "postal_code", "city", "country", "active")
                conn.execute("""UPDATE customers SET name=?,email=?,phone=?,mobile_phone=?,street=?,postal_code=?,
                    city=?,country=?,active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (*(before.get(field, "") for field in fields), change["customer_id"]))
            conn.execute("UPDATE customer_import_runs SET status='hersteld',reversed_at=CURRENT_TIMESTAMP WHERE id=?", (run_id,))
        return {"run_id": run_id, "restored": len(changes)}

    def reactivate(self, customer_number: str) -> None:
        with self.db.transaction() as conn:
            result = conn.execute("UPDATE customers SET active=1,updated_at=CURRENT_TIMESTAMP WHERE customer_number=?",
                                  (customer_number.strip(),))
            if not result.rowcount:
                raise ValueError("Klantnummer niet gevonden.")

    def export_active(self, target: Path) -> Path:
        with self.db.transaction() as conn:
            rows = [dict(row) for row in conn.execute("""SELECT customer_number,name,email,phone,mobile_phone,
                street,postal_code,city,country FROM customers WHERE active=1 ORDER BY name COLLATE NOCASE""").fetchall()]
        headers = ["Klantnummer", "Naam", "E-mail", "Telefoon", "Mobiel", "Adres", "Postcode", "Plaats", "Land"]
        matrix = [headers] + [[row[key] or "" for key in
            ("customer_number", "name", "email", "phone", "mobile_phone", "street", "postal_code", "city", "country")] for row in rows]
        self._write_xlsx(target, matrix)
        return target

    @classmethod
    def _customer_state(cls, row: dict) -> dict:
        return {field: row.get(field, "") for field in (*cls.COMPARE_FIELDS, "active")}

    @staticmethod
    def _write_xlsx(target: Path, rows: list[list[str]]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        widths = [16, 36, 32, 18, 18, 32, 14, 24, 18]
        sheet_rows = []
        for row_index, row in enumerate(rows, 1):
            cells = []
            for column_index, value in enumerate(row):
                number, letters = column_index + 1, ""
                while number:
                    number, remainder = divmod(number - 1, 26)
                    letters = chr(65 + remainder) + letters
                style = ' s="1"' if row_index == 1 else ' s="2"'
                cells.append(f'<c r="{letters}{row_index}" t="inlineStr"{style}><is><t>{escape(str(value))}</t></is></c>')
            sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        columns = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, 1))
        sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 f'<cols>{columns}</cols><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                 f'<sheetData>{"".join(sheet_rows)}</sheetData><autoFilter ref="A1:I{len(rows)}"/></worksheet>')
        content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Klanten" sheetId="1" r:id="rId1"/></sheets></workbook>')
        workbook_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF123456"/><bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>')
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
            archive.writestr("xl/styles.xml", styles)

    def _read_xlsx(self, source: Path) -> list[dict]:
        if not source.is_file() or source.suffix.lower() != ".xlsx":
            raise ValueError("Selecteer een geldig Excel-bestand (.xlsx).")
        try:
            with zipfile.ZipFile(source) as archive:
                shared = self._shared_strings(archive)
                sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise ValueError("Het Excel-bestand kan niet worden gelezen.") from exc
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        matrix: list[list[str]] = []
        for row_node in sheet.findall(".//x:sheetData/x:row", namespace):
            values: dict[int, str] = {}
            for cell in row_node.findall("x:c", namespace):
                reference = cell.get("r", "")
                match = re.match(r"([A-Z]+)", reference)
                if not match:
                    continue
                column = self._column_index(match.group(1))
                cell_type = cell.get("t", "")
                if cell_type == "inlineStr":
                    value = "".join(node.text or "" for node in cell.findall(".//x:t", namespace))
                else:
                    value_node = cell.find("x:v", namespace)
                    value = value_node.text if value_node is not None and value_node.text is not None else ""
                    if cell_type == "s" and value:
                        value = shared[int(value)]
                values[column] = value.strip()
            if values:
                width = max(values) + 1
                matrix.append([values.get(index, "") for index in range(width)])
        if not matrix:
            return []
        mapping: dict[int, str] = {}
        for index, header in enumerate(matrix[0]):
            normalized = re.sub(r"[^a-z0-9-]", "", header.lower())
            if normalized in ("fax", "krediettermijn"):
                continue
            field = self.HEADER_MAP.get(normalized)
            if field:
                mapping[index] = field
        required = {"customer_number", "name"}
        if not required.issubset(mapping.values()):
            raise ValueError("De kolommen Relatiecode/Klantnummer en Naam zijn verplicht.")
        result = []
        for source_row in matrix[1:]:
            row = {field: (source_row[index] if index < len(source_row) else "").strip() for index, field in mapping.items()}
            if not any(row.values()):
                continue
            number = row.get("customer_number", "")
            if number.endswith(".0"):
                number = number[:-2]
            row["customer_number"] = number
            if not number or not row.get("name", ""):
                raise ValueError("Elke importregel moet een klantnummer en naam bevatten.")
            for field in ("contact_name", "street", "postal_code", "city", "country", "phone", "mobile_phone", "email"):
                row.setdefault(field, "")
            result.append(row)
        return result

    @staticmethod
    def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        return ["".join(node.text or "" for node in item.findall(".//x:t", namespace))
                for item in root.findall("x:si", namespace)]

    @staticmethod
    def _column_index(letters: str) -> int:
        value = 0
        for letter in letters:
            value = value * 26 + ord(letter) - 64
        return value - 1

