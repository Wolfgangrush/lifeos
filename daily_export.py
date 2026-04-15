#!/usr/bin/env python3
"""Daily offline export helpers."""

import csv
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape


EXPORT_DIR = Path("data") / "excel_exports"


def _cell_ref(column_index: int, row_index: int) -> str:
    letters = ""
    column = column_index
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index}"


def _write_xlsx(csv_path: Path, xlsx_path: Path) -> None:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            ref = _cell_ref(column_index, row_index)
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        f'{"".join(sheet_rows)}'
        '</sheetData>'
        '</worksheet>'
    )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Completed Tasks" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def export_completed_task(task, source: str = "telegram") -> Path:
    """Append a completed task to the daily spreadsheet."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    completed_at = task.completed_at or datetime.now()
    csv_path = EXPORT_DIR / f"completed_tasks_{completed_at.date().isoformat()}.csv"
    xlsx_path = EXPORT_DIR / f"completed_tasks_{completed_at.date().isoformat()}.xlsx"
    write_header = not csv_path.exists()

    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow([
                "completed_at",
                "task_id",
                "description",
                "priority",
                "focus_required",
                "source",
            ])
        writer.writerow([
            completed_at.isoformat(timespec="seconds"),
            task.id,
            task.description,
            task.priority,
            bool(task.focus_required),
            source,
        ])

    _write_xlsx(csv_path, xlsx_path)
    return xlsx_path


def rebuild_completed_tasks_export(tasks, export_date, source: str = "database") -> Path:
    """Rewrite one day's completed-task spreadsheet from the current database rows."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = EXPORT_DIR / f"completed_tasks_{export_date.isoformat()}.csv"
    xlsx_path = EXPORT_DIR / f"completed_tasks_{export_date.isoformat()}.xlsx"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "completed_at",
            "task_id",
            "description",
            "priority",
            "focus_required",
            "source",
        ])
        for task in tasks:
            completed_at = task.completed_at or datetime.now()
            writer.writerow([
                completed_at.isoformat(timespec="seconds"),
                task.id,
                task.description,
                task.priority,
                bool(task.focus_required),
                source,
            ])

    _write_xlsx(csv_path, xlsx_path)
    return xlsx_path
