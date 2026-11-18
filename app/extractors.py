from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

import fitz
from docx import Document
from docx.document import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError

_BULLET_MARKERS = frozenset({"•", "●", "▪", "◦", "‣", "⁃", "·", "*"})


class DocumentExtractionError(ValueError):
    """Raised when a supported file cannot be safely or usefully extracted."""


def _docx_blocks(document: DocxDocument) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for order, item in enumerate(document.element.body.iterchildren()):
        if isinstance(item, CT_P):
            paragraph = Paragraph(item, document)
            text = paragraph.text.strip()
            if text:
                style_name = paragraph.style.name if paragraph.style else None
                list_kind = None
                if style_name and style_name.startswith("List Bullet"):
                    list_kind = "bullet"
                elif style_name and style_name.startswith("List Number"):
                    list_kind = "number"
                blocks.append(
                    {
                        "type": "list_item" if list_kind else "paragraph",
                        "order": order,
                        "text": text,
                        "style": style_name,
                        **({"list_kind": list_kind} if list_kind else {}),
                    }
                )
        elif isinstance(item, CT_Tbl):
            table = Table(item, document)
            rows = [
                [cell.text.strip() for cell in row.cells]
                for row in table.rows
            ]
            if any(any(cell for cell in row) for row in rows):
                blocks.append({"type": "table", "order": order, "rows": rows})
    return blocks


def _extract_docx(data: bytes) -> dict[str, Any]:
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentExtractionError("The uploaded file is not a valid DOCX document.")
        document = Document(BytesIO(data))
    except DocumentExtractionError:
        raise
    except (BadZipFile, KeyError, ValueError, PackageNotFoundError, XMLSyntaxError) as exc:
        raise DocumentExtractionError("The uploaded file is not a valid DOCX document.") from exc

    blocks = _docx_blocks(document)
    if not blocks:
        raise DocumentExtractionError("No readable text or tables were found in this DOCX.")
    return {"blocks": blocks, "page_count": None}


def _extract_pdf(data: bytes) -> dict[str, Any]:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except (fitz.FileDataError, RuntimeError) as exc:
        raise DocumentExtractionError("The uploaded file is not a readable PDF.") from exc

    with document:
        if document.needs_pass:
            raise DocumentExtractionError("This PDF is password-protected and cannot be extracted.")
        pages: list[dict[str, Any]] = []
        has_text = False
        for page_number, page in enumerate(document, start=1):
            positioned_blocks: list[tuple[float, float, dict[str, Any]]] = []
            detected_tables = page.find_tables().tables
            table_boxes = []
            for table in detected_tables:
                rows = [
                    [cell.strip() if cell else "" for cell in row]
                    for row in table.extract()
                ]
                if not any(any(cell for cell in row) for row in rows):
                    continue
                bbox = [round(float(value), 2) for value in table.bbox]
                table_boxes.append(table.bbox)
                positioned_blocks.append(
                    (
                        float(table.bbox[1]),
                        float(table.bbox[0]),
                        {"type": "table", "rows": rows, "bbox": bbox},
                    )
                )

            raw_blocks = page.get_text("blocks", sort=True)
            for raw in raw_blocks:
                if len(raw) < 7 or raw[6] != 0:
                    continue
                text = raw[4].strip()
                if not text:
                    continue
                center_x = (raw[0] + raw[2]) / 2
                center_y = (raw[1] + raw[3]) / 2
                if any(
                    x0 <= center_x <= x1 and y0 <= center_y <= y1
                    for x0, y0, x1, y1 in table_boxes
                ):
                    continue
                has_text = True
                positioned_blocks.append(
                    (
                        float(raw[1]),
                        float(raw[0]),
                        {
                            "type": "paragraph",
                            "text": text,
                            "bbox": [round(float(value), 2) for value in raw[:4]],
                        },
                    )
                )
            has_text = has_text or bool(positioned_blocks)
            ordered_blocks = sorted(positioned_blocks, key=lambda item: (item[0], item[1]))
            page_blocks = []
            index = 0
            while index < len(ordered_blocks):
                _, _, block = ordered_blocks[index]
                if (
                    block["type"] == "paragraph"
                    and block["text"] in _BULLET_MARKERS
                    and index + 1 < len(ordered_blocks)
                ):
                    bullet_bbox = block["bbox"]
                    next_block = ordered_blocks[index + 1][2]
                    next_bbox = next_block.get("bbox", [])
                    line_height = max(1.0, bullet_bbox[3] - bullet_bbox[1])
                    horizontal_distance = (
                        abs(bullet_bbox[0] - next_bbox[0]) if len(next_bbox) == 4 else float("inf")
                    )
                    vertical_gap = (
                        next_bbox[1] - bullet_bbox[3] if len(next_bbox) == 4 else float("inf")
                    )
                    if (
                        next_block["type"] == "paragraph"
                        and horizontal_distance <= 48
                        and -line_height <= vertical_gap <= max(48, line_height * 3)
                    ):
                        page_blocks.append(
                            {
                                **next_block,
                                "type": "list_item",
                                "list_kind": "bullet",
                                "marker": block["text"],
                                "order": len(page_blocks),
                            }
                        )
                        index += 2
                        continue
                page_blocks.append({**block, "order": len(page_blocks)})
                index += 1
            pages.append({"page": page_number, "blocks": page_blocks})

    if not pages:
        raise DocumentExtractionError("The PDF contains no pages.")
    if not has_text:
        raise DocumentExtractionError(
            "No selectable text was found. This may be a scanned PDF; OCR is not enabled."
        )
    return {"blocks": pages, "page_count": len(pages)}


def extract_document(filename: str, data: bytes) -> dict[str, Any]:
    """Extract ordered document content into a stable, JSON-serializable shape."""
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise DocumentExtractionError("Only PDF and DOCX files are supported.")
    if not data:
        raise DocumentExtractionError("The uploaded file is empty.")

    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise DocumentExtractionError("The file extension is PDF, but its contents are not.")
        result = _extract_pdf(data)
        file_type = "pdf"
    else:
        if not data.startswith(b"PK"):
            raise DocumentExtractionError("The file extension is DOCX, but its contents are not.")
        result = _extract_docx(data)
        file_type = "docx"

    if file_type == "docx":
        full_text = "\n".join(
            "\t".join(row)
            for block in result["blocks"]
            for row in (
                block["rows"]
                if block["type"] == "table"
                else [[block["text"]]]
            )
        )
    else:
        full_text = "\n\n".join(
            "\n".join("\t".join(row) for row in block["rows"])
            if block["type"] == "table"
            else block["text"]
            for page in result["blocks"]
            for block in page["blocks"]
        )

    return {
        "schema_version": "1.0",
        "filename": PurePosixPath(filename.replace("\\", "/")).name,
        "file_type": file_type,
        "page_count": result["page_count"],
        "blocks": result["blocks"],
        "full_text": full_text,
    }
