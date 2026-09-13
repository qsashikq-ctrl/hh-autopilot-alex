import sqlite3
from datetime import datetime
from config import DB_PATH

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS responses(
                vacancy_id TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS seen(
                vacancy_id TEXT PRIMARY KEY,
                seen_at TEXT NOT NULL
            )
        """)

def mark_seen(vacancy_id: str):
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen(vacancy_id, seen_at) VALUES(?, ?)",
            (vacancy_id, datetime.now().isoformat(timespec="seconds"))
        )

def was_seen(vacancy_id: str) -> bool:
    with conn() as c:
        row = c.execute("SELECT 1 FROM seen WHERE vacancy_id=?", (vacancy_id,)).fetchone()
        return bool(row)

def response_status(vacancy_id: str):
    with conn() as c:
        row = c.execute("SELECT status FROM responses WHERE vacancy_id=?", (vacancy_id,)).fetchone()
        return row["status"] if row else None

def save_response(vacancy_id: str, title: str, company: str, status: str):
    with conn() as c:
        c.execute("""
            INSERT INTO responses(vacancy_id,title,company,status,created_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(vacancy_id) DO UPDATE SET status=excluded.status
        """, (vacancy_id, title, company, status, datetime.now().isoformat(timespec="seconds")))

def stats():
    with conn() as c:
        total = c.execute("SELECT COUNT(*) n FROM responses").fetchone()["n"]
        sent = c.execute("SELECT COUNT(*) n FROM responses WHERE status='sent'").fetchone()["n"]
        failed = c.execute("SELECT COUNT(*) n FROM responses WHERE status='failed'").fetchone()["n"]
        return {"total": total, "sent": sent, "failed": failed}
