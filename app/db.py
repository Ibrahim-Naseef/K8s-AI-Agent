import json
import os
import sqlite3
import time

from . import config
from .knowledge import normalize


def _conn():
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS investigations(
                 id TEXT PRIMARY KEY, created_at REAL, namespace TEXT, question TEXT,
                 status TEXT, result TEXT, error TEXT, events TEXT)"""
        )


def upsert(id, namespace, question, status, result=None, error=None, events=None):
    with _conn() as c:
        c.execute(
            """INSERT INTO investigations(id,created_at,namespace,question,status,result,error,events)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, result=excluded.result,
                 error=excluded.error, events=excluded.events""",
            (id, time.time(), namespace, question, status,
             json.dumps(result) if result else None, error,
             json.dumps(events, default=str) if events else None),
        )


def _row(r, full=True):
    d = {k: r[k] for k in ("id", "created_at", "namespace", "question", "status", "error")}
    result = normalize(json.loads(r["result"]), r["namespace"]) if r["result"] else None
    d["headline"] = (result or {}).get("root_cause", "")[:140]
    if full:
        d["result"] = result
        d["events"] = json.loads(r["events"]) if r["events"] else []
    return d


def list_recent(limit=30):
    with _conn() as c:
        rows = c.execute("SELECT * FROM investigations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r, full=False) for r in rows]


def get(id):
    with _conn() as c:
        r = c.execute("SELECT * FROM investigations WHERE id=?", (id,)).fetchone()
    return _row(r) if r else None
