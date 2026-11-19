"""只追加审计。

约束：audit 表禁止 UPDATE / DELETE，用 SQLite 触发器硬拦。
这样即便将来代码有 bug，历史记录也改不掉。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    actor       TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    target      TEXT,
    outcome     TEXT    NOT NULL,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        yield conn
    finally:
        conn.close()


def record(
    db_path: Path,
    *,
    actor: str,
    action: str,
    outcome: str,
    target: str | None = None,
    detail: dict[str, Any] | str | None = None,
) -> int:
    """写一条审计记录，返回行 id。"""
    if isinstance(detail, dict):
        detail_text = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    else:
        detail_text = detail

    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO audit_log (ts, actor, action, target, outcome, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), actor, action, target, outcome, detail_text),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def tail(db_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    """读最近记录，仅供排查用。"""
    if limit < 1 or limit > 500:
        raise ValueError("limit 必须在 1..500 之间")
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
