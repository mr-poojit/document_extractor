from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.extractors import DocumentExtractionError, extract_document
from app.storage import (
    delete_document,
    get_document,
    initialize_database,
    list_documents,
    save_document,
)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await run_in_threadpool(initialize_database)
    yield


app = FastAPI(
    title="DocuLens",
    description="Extract readable content from PDF and DOCX files into JSON.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract", tags=["documents"])
async def extract(file: UploadFile = File(...)) -> dict:
    filename = file.filename or ""
    if Path(filename).suffix.lower() not in {".pdf", ".docx"}:
        raise HTTPException(status_code=415, detail="Only PDF and DOCX files are supported.")

    content = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File is too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
    finally:
        await file.close()

    try:
        extracted = await run_in_threadpool(extract_document, filename, bytes(content))
        return await run_in_threadpool(save_document, extracted)
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/documents", tags=["documents"])
async def documents(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await run_in_threadpool(list_documents, q, limit, offset)


@app.get("/api/documents/{document_id}", tags=["documents"])
async def document(document_id: str) -> dict:
    saved_document = await run_in_threadpool(get_document, document_id)
    if saved_document is None:
        raise HTTPException(status_code=404, detail="Saved document not found.")
    return saved_document


@app.delete(
    "/api/documents/{document_id}",
    status_code=204,
    response_class=Response,
    tags=["documents"],
)
async def remove_document(document_id: str) -> Response:
    deleted = await run_in_threadpool(delete_document, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved document not found.")
    return Response(status_code=204)


@app.get("/api")
async def api_root() -> dict[str, str]:
    return {"docs": "/docs", "health": "/healthz"}
