from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "doculens.sqlite3"
DB_PATH = Path(os.environ.get("DOCULENS_DB_PATH", DEFAULT_DB_PATH)).expanduser()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with _connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'docx')),
                saved_at TEXT NOT NULL,
                full_text TEXT NOT NULL,
                json_data TEXT NOT NULL CHECK (json_valid(json_data))
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_saved_at ON documents(saved_at DESC)"
        )


def save_document(document: dict[str, Any]) -> dict[str, Any]:
    saved_document = {
        **document,
        "id": str(uuid.uuid4()),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO documents (id, filename, file_type, saved_at, full_text, json_data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                saved_document["id"],
                saved_document["filename"],
                saved_document["file_type"],
                saved_document["saved_at"],
                saved_document["full_text"],
                json.dumps(saved_document, ensure_ascii=False, separators=(",", ":")),
            ),
        )
    return saved_document


def list_documents(query: str, limit: int, offset: int) -> dict[str, Any]:
    escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped_query}%"
    where_clause = """
        (? = '' OR filename LIKE ? ESCAPE '\\' COLLATE NOCASE
        OR full_text LIKE ? ESCAPE '\\' COLLATE NOCASE)
    """
    with _connection() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM documents WHERE {where_clause}",
            (query, pattern, pattern),
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT id, filename, file_type, saved_at, full_text
            FROM documents
            WHERE {where_clause}
            ORDER BY saved_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (query, pattern, pattern, limit, offset),
        ).fetchall()

    return {
        "items": [
            {
                "id": row["id"],
                "filename": row["filename"],
                "file_type": row["file_type"],
                "saved_at": row["saved_at"],
                "preview": row["full_text"][:180],
            }
            for row in rows
        ],
        "total": total,
    }


def get_document(document_id: str) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT json_data FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    return json.loads(row["json_data"]) if row else None


def delete_document(document_id: str) -> bool:
    with _connection() as connection:
        cursor = connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cursor.rowcount > 0
