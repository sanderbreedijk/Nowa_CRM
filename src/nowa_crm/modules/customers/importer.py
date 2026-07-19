from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
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
        for row in rows:
            current = existing.get(row["customer_number"])
            if current is None:
                created += 1
            elif not current["active"] or any((current[field] or "").strip() != row[field] for field in self.COMPARE_FIELDS):
                updated += 1
            else:
                unchanged += 1
        imported = set(numbers)
        archived = sum(bool(item["active"]) and number not in imported for number, item in existing.items())
        return ImportPreview(source, rows, created, updated, archived, unchanged)

    def apply(self, preview: ImportPreview) -> dict:
        backup = self.db.backup("voor-klantimport")
        imported_numbers = {row["customer_number"] for row in preview.rows}
        with self.db.transaction() as conn:
            for row in preview.rows:
                current = conn.execute("SELECT id,notes FROM customers WHERE customer_number=?", (row["customer_number"],)).fetchone()
                values = tuple(row[field] for field in ("name", "email", "phone", "mobile_phone", "street", "postal_code", "city", "country"))
                if current:
                    customer_id = int(current["id"])
                    conn.execute("""UPDATE customers SET name=?,email=?,phone=?,mobile_phone=?,street=?,postal_code=?,city=?,country=?,
                        active=1,updated_at=CURRENT_TIMESTAMP WHERE id=?""", (*values, customer_id))
                else:
                    customer_id = int(conn.execute("""INSERT INTO customers
                        (customer_number,name,email,phone,mobile_phone,street,postal_code,city,country)
                        VALUES(?,?,?,?,?,?,?,?,?)""", (row["customer_number"], *values)).lastrowid)
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
            placeholders = ",".join("?" for _ in imported_numbers)
            conn.execute(f"UPDATE customers SET active=0,updated_at=CURRENT_TIMESTAMP WHERE active=1 AND customer_number NOT IN ({placeholders})",
                         tuple(sorted(imported_numbers)))
            run_id = int(conn.execute("""INSERT INTO customer_import_runs
                (source_name,source_rows,created_count,updated_count,archived_count,performed_by)
                VALUES(?,?,?,?,?,?)""", (preview.source.name, len(preview.rows), preview.created, preview.updated, preview.archived, self.actor)).lastrowid)
        return {"run_id": run_id, "backup": backup, "created": preview.created, "updated": preview.updated,
                "archived": preview.archived, "unchanged": preview.unchanged}

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
