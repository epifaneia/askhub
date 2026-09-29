"""Almacén local: SQLite + vectores en numpy. Sin servidor, sin Docker."""

import pathlib
import sqlite3

import numpy as np

DB_PATH = pathlib.Path(__file__).parent / "askhub.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id      TEXT PRIMARY KEY,
                source  TEXT NOT NULL,
                title   TEXT,
                url     TEXT,
                content TEXT NOT NULL,
                hash    TEXT,
                emb     BLOB
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        c.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")


def get_state(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def existing_hashes(source: str) -> dict:
    with _conn() as c:
        rows = c.execute("SELECT id, hash FROM chunks WHERE source = ?", (source,)).fetchall()
    return {r["id"]: r["hash"] for r in rows}


def upsert(rows: list[dict], vectors: list[list[float]]) -> None:
    if not rows:
        return
    datos = [
        (
            r["id"],
            r["source"],
            r.get("title", ""),
            r.get("url", ""),
            r["content"],
            r.get("hash", ""),
            np.asarray(v, dtype=np.float32).tobytes(),
        )
        for r, v in zip(rows, vectors)
    ]
    with _conn() as c:
        c.executemany(
            """
            INSERT INTO chunks (id, source, title, url, content, hash, emb)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title, url = excluded.url,
                content = excluded.content, hash = excluded.hash, emb = excluded.emb
            """,
            datos,
        )


def prune(source: str, keep_ids: set) -> int:
    with _conn() as c:
        rows = c.execute("SELECT id FROM chunks WHERE source = ?", (source,)).fetchall()
        muertos = [r["id"] for r in rows if r["id"] not in keep_ids]
        if muertos:
            c.executemany("DELETE FROM chunks WHERE id = ?", [(i,) for i in muertos])
    return len(muertos)


def search(query_vec: list[float], k: int = 12, sources: list[str] | None = None) -> list[dict]:
    """Fuerza bruta con numpy. Con < 100k fragmentos es instantáneo y exacto."""
    sql = "SELECT id, source, title, url, content, emb FROM chunks"
    params: tuple = ()
    if sources:
        sql += f" WHERE source IN ({','.join('?' * len(sources))})"
        params = tuple(sources)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    if not rows:
        return []

    matriz = np.vstack([np.frombuffer(r["emb"], dtype=np.float32) for r in rows])
    q = np.asarray(query_vec, dtype=np.float32)
    q /= np.linalg.norm(q) or 1.0
    # Los vectores ya se guardan normalizados: el producto escalar ES el coseno.
    scores = matriz @ q
    mejores = np.argsort(-scores)[:k]
    return [
        {
            "source": rows[i]["source"],
            "title": rows[i]["title"],
            "url": rows[i]["url"],
            "content": rows[i]["content"],
            "score": float(scores[i]),
        }
        for i in mejores
    ]


def counts() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT source, count(*) n FROM chunks GROUP BY source").fetchall()
    return {r["source"]: r["n"] for r in rows}
