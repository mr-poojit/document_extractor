# DocuLens

DocuLens is a small full-stack document extraction app. Upload a PDF or DOCX file to view its extracted content, search it, and save, reopen, search, download, or delete its structured JSON result.

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

The database contains extracted JSON and searchable text, but not the original uploaded documents. Saved results remain until explicitly deleted. The web UI provides a searchable saved-document list and delete actions.

Run tests with:

```powershell
python -m pytest
```

## JSON response

`POST /api/extract` accepts a multipart `file` field and returns:

```json
{
  "schema_version": "1.0",
  "id": "<saved-document-uuid>",
  "saved_at": "<ISO-8601 timestamp>",
  "filename": "report.docx",
  "file_type": "docx",
  "page_count": null,
  "blocks": [
    { "type": "paragraph", "order": 0, "text": "Quarterly report", "style": "Title" },
    { "type": "table", "order": 1, "rows": [["Quarter", "Revenue"], ["Q1", "$10"]] }
  ],
  "full_text": "Quarterly report\nQuarter\tRevenue\nQ1\t$10"
}
```

DOCX page count is `null` because the format does not encode stable rendered page boundaries; pagination depends on the word processor and layout. PDF output groups text blocks by page and includes their bounding boxes; tables detected by PyMuPDF are represented as row/cell arrays. DOCX paragraphs and tables remain in document order. The first table row is rendered as a header in the UI for readability; the JSON retains all rows as extracted.

## Saved document API

- `GET /api/documents?q=term&limit=50&offset=0` lists saved JSON, with optional case-insensitive search over filenames and extracted content.
- `GET /api/documents/{id}` retrieves the complete saved JSON.
- `DELETE /api/documents/{id}` permanently deletes a saved result.
- `POST /api/extract` extracts **and saves** the JSON, returning its `id` and `saved_at` along with the extraction fields.

## Reliability and limitations

- Uploads are limited to 20 MiB and checked by both extension and file signature. Malformed files and password-protected PDFs return actionable errors.
- Uploaded originals are not retained. Extracted JSON is stored in SQLite until deleted; protect and back up the database according to the sensitivity of the documents.
- A PDF with no selectable text is reported as likely scanned. OCR is deliberately not claimed or silently approximated; scanned-document OCR would need an explicitly provisioned OCR engine and language packs.
- PDF reading order and table detection depend on the source PDF's text layer and layout. Unruled or irregular tables may remain ordinary text blocks; visual formatting is not reproduced.
- This demo has no user authentication or per-user data isolation. Do not expose it to untrusted users as-is: add authentication/authorization and tenant-scoped document access, plus HTTPS, request timeouts/rate limits, and appropriate database protection. For larger-scale workloads, move parsing into a bounded worker queue and enforce per-user quotas.

## Technology choices

- **FastAPI** for typed, documented HTTP endpoints and straightforward deployment.
- **SQLite** for persistent, searchable JSON history without storing original uploads.
- **PyMuPDF** for PDF text blocks, page ordering, and geometry.
- **python-docx** for ordered DOCX paragraphs and tables.
- **Vanilla HTML/CSS/JavaScript** for a compact, dependency-free frontend with document preview, search, JSON inspection, copy, and download.
