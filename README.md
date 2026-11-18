# DocuLens

DocuLens is a small full-stack document extraction app. Upload a PDF or DOCX file to view its extracted content, search it, and save, reopen, search, download, or delete its structured JSON result. PDF page previews preserve the source document's exact layout, including embedded images, charts, vector diagrams, question numbers, and bullets.

## Run locally

Requires Python 3.10 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Interactive API documentation is at `/docs`.

By default, saved extraction results are stored in `data/doculens.sqlite3` (the `data` directory is created automatically). To use a different persistent location, set `DOCULENS_DB_PATH` before starting the server:

```powershell
$env:DOCULENS_DB_PATH = "C:\path\to\doculens.sqlite3"
python -m uvicorn app.main:app
```

The database contains extracted JSON, searchable text, and compressed JPEG previews of PDF pages, but not the original uploaded documents. Saved results and previews remain until explicitly deleted. The web UI provides a searchable saved-document list and delete actions.

PDFs uploaded before page-preview support will not have stored previews; upload those source PDFs again to create them.

Run tests with:

```powershell
python -m pytest
```

## JSON response

`POST /api/extract` accepts a multipart `file` field and returns:

```json
{
  "schema_version": "1.1",
  "id": "<saved-document-uuid>",
  "saved_at": "<ISO-8601 timestamp>",
  "page_previews": [
    { "page": 1, "url": "/api/documents/<saved-document-uuid>/pages/1" }
  ],
  "filename": "report.pdf",
  "file_type": "pdf",
  "page_count": 1,
  "blocks": [
    {
      "page": 1,
      "blocks": [
        { "type": "paragraph", "order": 0, "text": "Quarterly report", "bbox": [40, 50, 300, 75] },
        { "type": "table", "order": 1, "rows": [["Quarter", "Revenue"], ["Q1", "$10"]] }
      ]
    }
  ],
  "full_text": "Quarterly report\nQuarter\tRevenue\nQ1\t$10"
}
```

DOCX page count is `null` because the format does not encode stable rendered page boundaries; pagination depends on the word processor and layout. PDF output groups text blocks by page and includes their bounding boxes; tables detected by PyMuPDF are represented as row/cell arrays. Its `page_previews` point to stored JPEG renderings of the original pages, preserving diagrams, charts, numbering, and layout. The extracted-text and JSON views remain searchable, while Original pages shows the visual page.

## Saved document API

- `GET /api/documents?q=term&limit=50&offset=0` lists saved JSON, with optional case-insensitive search over filenames and extracted content.
- `GET /api/documents/{id}` retrieves the complete saved JSON.
- `GET /api/documents/{id}/pages/{page_number}` serves a rendered PDF page preview as JPEG.
- `DELETE /api/documents/{id}` permanently deletes a saved result.
- `POST /api/extract` extracts **and saves** the JSON, returning its `id` and `saved_at` along with the extraction fields.

## Reliability and limitations

- Uploads are limited to 20 MiB and checked by both extension and file signature. Malformed files and password-protected PDFs return actionable errors.
- Uploaded originals are not retained. Extracted JSON and rendered PDF page previews are stored in SQLite until deleted; protect and back up the database according to the sensitivity of the documents.
- A PDF with no selectable text is reported as likely scanned. OCR is deliberately not claimed or silently approximated; scanned-document OCR would need an explicitly provisioned OCR engine and language packs.
- PDF reading order and table detection in the extracted-text view depend on the source PDF's text layer and layout. Unruled or irregular tables may remain ordinary text blocks; use Original pages to see the source page layout and figures.
- This demo has no user authentication or per-user data isolation. Do not expose it to untrusted users as-is: add authentication/authorization and tenant-scoped document access, plus HTTPS, request timeouts/rate limits, and appropriate database protection. For larger-scale workloads, move parsing into a bounded worker queue and enforce per-user quotas.

## Technology choices

- **FastAPI** for typed, documented HTTP endpoints and straightforward deployment.
- **SQLite** for persistent, searchable JSON history without storing original uploads.
- **PyMuPDF** for PDF text blocks, page ordering, and geometry.
- **python-docx** for ordered DOCX paragraphs and tables.
- **Vanilla HTML/CSS/JavaScript** for a compact, dependency-free frontend with document preview, search, JSON inspection, copy, and download.
