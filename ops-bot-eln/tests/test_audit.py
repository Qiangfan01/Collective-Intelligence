"""审计表的只追加约束测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eln_ops_mcp import audit


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "audit.db"


def test_record_and_tail(db: Path) -> None:
    audit.record(db, actor="agent", action="eln_status", outcome="ok", target="xdraw-api")
    audit.record(db, actor="owner", action="approve", outcome="ok", target="P-1")
    rows = audit.tail(db, 10)
    assert len(rows) == 2
    assert rows[0]["action"] == "approve"  # 倒序
    assert rows[0]["ts"].endswith("+00:00")


def test_update_is_blocked(db: Path) -> None:
    audit.record(db, actor="agent", action="eln_status", outcome="ok")
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET outcome = 'fail'")
    conn.close()


def test_delete_is_blocked(db: Path) -> None:
    audit.record(db, actor="agent", action="eln_status", outcome="ok")
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log")
    conn.close()


def test_detail_dict_is_serialized(db: Path) -> None:
    audit.record(
        db, actor="agent", action="eln_logs", outcome="ok", detail={"lines": 200, "容器": "xdraw-api"}
    )
    row = audit.tail(db, 1)[0]
    assert '"lines": 200' in row["detail"]
    assert "xdraw-api" in row["detail"]


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_tail_limit_bounds(db: Path, limit: int) -> None:
    with pytest.raises(ValueError, match="1..500"):
        audit.tail(db, limit)
