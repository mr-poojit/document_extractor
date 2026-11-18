from io import BytesIO

import fitz
import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.extractors import DocumentExtractionError, extract_document
from app import storage
from app.main import MAX_UPLOAD_BYTES, app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "doculens.sqlite3")
    with TestClient(app) as test_client:
        yield test_client


def make_docx() -> bytes:
    document = Document()
    document.add_paragraph("Quarterly report", style="Title")
    document.add_paragraph("Revenue increased.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Quarter"
    table.cell(0, 1).text = "Revenue"
    table.cell(1, 0).text = "Q1"
    table.cell(1, 1).text = "$10"
    document.add_paragraph("First list item", style="List Bullet")
    document.add_paragraph("Second list item", style="List Bullet")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def make_pdf(text: str = "Invoice 1042\nAmount due: $25.00") -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    output = document.tobytes()
    document.close()
    return output


def make_visual_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "A chart and embedded image")
    page.draw_line((72, 120), (180, 120), width=2)
    page.draw_line((72, 120), (72, 190), width=2)
    page.draw_line((72, 190), (180, 135), color=(0, 0, 1), width=2)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24), False)
    pixmap.clear_with(0xCC3333)
    page.insert_image(fitz.Rect(220, 100, 280, 160), pixmap=pixmap)
    output = document.tobytes()
    document.close()
    return output


def make_split_bullet_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "*", fontsize=12)
    page.insert_text((72, 121), "First list item wraps naturally.", fontsize=12)
    page.insert_text((72, 155), "*", fontsize=12)
    page.insert_text((72, 176), "Second list item stays separate.", fontsize=12)
    output = document.tobytes()
    document.close()
    return output


def make_table_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    for x in (72, 220, 360):
        page.draw_line((x, 72), (x, 150))
    for y in (72, 110, 150):
        page.draw_line((72, y), (360, y))
    page.insert_text((80, 96), "Quarter")
    page.insert_text((228, 96), "Revenue")
    page.insert_text((80, 136), "Q1")
    page.insert_text((228, 136), "$10")
    output = document.tobytes()
    document.close()
    return output


def test_docx_preserves_paragraph_and_table_content() -> None:
    result = extract_document("report.docx", make_docx())

    assert result["file_type"] == "docx"
    assert result["page_count"] is None
    assert result["blocks"][0]["text"] == "Quarterly report"
    assert result["blocks"][2]["type"] == "table"
    assert result["blocks"][2]["rows"][1] == ["Q1", "$10"]
    assert [block["type"] for block in result["blocks"][3:]] == ["list_item", "list_item"]
    assert "Revenue increased." in result["full_text"]
    assert "Quarter\tRevenue\nQ1\t$10" in result["full_text"]


def test_pdf_returns_text_in_page_order() -> None:
    result = extract_document("invoice.pdf", make_pdf())

    assert result["file_type"] == "pdf"
    assert result["page_count"] == 1
    assert "Invoice 1042" in result["full_text"]
    assert "Amount due: $25.00" in result["full_text"]


def test_pdf_attaches_separate_bullet_markers_to_their_text() -> None:
    result = extract_document("bullets.pdf", make_split_bullet_pdf())
    blocks = result["blocks"][0]["blocks"]

    assert [block["type"] for block in blocks] == ["list_item", "list_item"]
    assert [block["text"] for block in blocks] == [
        "First list item wraps naturally.",
        "Second list item stays separate.",
    ]
    assert all(block["marker"] == "*" for block in blocks)


def test_pdf_detects_tabular_content() -> None:
    result = extract_document("table.pdf", make_table_pdf())
    table_blocks = [
        block
        for page in result["blocks"]
        for block in page["blocks"]
        if block["type"] == "table"
    ]

    assert len(table_blocks) == 1
    assert table_blocks[0]["rows"] == [["Quarter", "Revenue"], ["Q1", "$10"]]
    assert "Q1\t$10" in result["full_text"]


def test_pdf_without_text_layer_reports_ocr_limitation() -> None:
    document = fitz.open()
    document.new_page()
    content = document.tobytes()
    document.close()

    with pytest.raises(DocumentExtractionError, match="scanned PDF"):
        extract_document("scan.pdf", content)


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("notes.txt", b"some text", "Only PDF and DOCX"),
        ("wrong.pdf", b"not a pdf", "contents are not"),
        ("empty.docx", b"", "empty"),
        ("broken.docx", b"PK-not-a-zip", "valid DOCX"),
    ],
)
def test_rejects_unsupported_or_malformed_uploads(
    filename: str, content: bytes, message: str
) -> None:
    with pytest.raises(DocumentExtractionError, match=message):
        extract_document(filename, content)


def test_api_serves_ui_and_health(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}


def test_api_extracts_docx_upload(client: TestClient) -> None:
    response = client.post(
        "/api/extract",
        files={
            "file": (
                "report.docx",
                make_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.1"
    assert response.json()["id"]
    assert response.json()["saved_at"]
    assert response.json()["filename"] == "report.docx"
    assert response.json()["blocks"][2]["type"] == "table"
    assert response.json()["page_previews"] == []


def test_pdf_page_preview_is_saved_and_served(client: TestClient) -> None:
    source_pdf = make_visual_pdf()
    with fitz.open(stream=source_pdf, filetype="pdf") as source:
        assert len(source[0].get_images()) == 1
        assert len(source[0].get_drawings()) >= 3
    response = client.post(
        "/api/extract",
        files={"file": ("paper.pdf", source_pdf, "application/pdf")},
    )

    assert response.status_code == 200
    saved = response.json()
    assert saved["page_count"] == 1
    assert saved["page_previews"] == [
        {"page": 1, "url": f"/api/documents/{saved['id']}/pages/1"}
    ]

    preview = client.get(saved["page_previews"][0]["url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    assert preview.content.startswith(b"\xff\xd8")

    assert client.delete(f"/api/documents/{saved['id']}").status_code == 204
    assert client.get(saved["page_previews"][0]["url"]).status_code == 404


def test_saved_json_can_be_searched_retrieved_and_deleted(client: TestClient) -> None:
    uploaded = client.post(
        "/api/extract",
        files={"file": ("report.docx", make_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    saved = uploaded.json()

    storage.initialize_database()
    all_documents = client.get("/api/documents")
    assert all_documents.status_code == 200
    assert all_documents.json()["total"] == 1
    assert all_documents.json()["items"][0]["id"] == saved["id"]

    search = client.get("/api/documents", params={"q": "revenue increased"})
    assert search.json()["total"] == 1
    assert client.get(f"/api/documents/{saved['id']}").json() == saved

    deleted = client.delete(f"/api/documents/{saved['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/documents/{saved['id']}").status_code == 404
    assert client.get("/api/documents").json()["total"] == 0


def test_api_rejects_wrong_extension(client: TestClient) -> None:
    response = client.post("/api/extract", files={"file": ("notes.txt", b"hello", "text/plain")})

    assert response.status_code == 415


def test_api_rejects_oversized_upload(client: TestClient) -> None:
    response = client.post(
        "/api/extract",
        files={"file": ("large.pdf", b"x" * (MAX_UPLOAD_BYTES + 1), "application/pdf")},
    )

    assert response.status_code == 413
