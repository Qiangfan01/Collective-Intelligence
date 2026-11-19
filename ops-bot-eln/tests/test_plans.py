"""方案账本与签名的测试。这些是安全核心，必须先过。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from eln_ops_mcp import plans


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "audit.db"


def _make(db: Path, **kw):
    params = dict(
        summary="重启 xdraw-worker",
        steps=[{"template": "container_status", "args": ["xdraw-worker"], "note": "确认状态"}],
        impact="生成任务暂停约 30 秒",
        rollback="docker start xdraw-worker",
        risk_level="medium",
    )
    params.update(kw)
    return plans.create(db, **params)


def test_create_and_get(db: Path) -> None:
    p = _make(db)
    assert p.plan_id.startswith("P-")
    assert p.status == plans.STATUS_PENDING
    loaded = plans.get(db, p.plan_id)
    assert loaded is not None
    assert loaded.summary == p.summary
    assert loaded.steps == p.steps


@pytest.mark.parametrize(
    "field,value",
    [
        ("summary", ""),
        ("impact", ""),
        ("rollback", ""),
        ("steps", []),
        ("risk_level", "critical"),
    ],
)
def test_create_rejects_incomplete_plan(db: Path, field: str, value: object) -> None:
    with pytest.raises(plans.PlanError):
        _make(db, **{field: value})


def test_plan_body_is_immutable(db: Path) -> None:
    p = _make(db)
    import sqlite3

    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE plans SET summary = '被改了' WHERE plan_id = ?", (p.plan_id,))
    conn.close()


def test_approve_once(db: Path) -> None:
    p = _make(db)
    approved = plans.decide(db, p.plan_id, approved=True, decided_by="ou_owner")
    assert approved.status == plans.STATUS_APPROVED
    assert approved.decided_by == "ou_owner"

    with pytest.raises(plans.PlanError, match="不能再次裁决"):
        plans.decide(db, p.plan_id, approved=True, decided_by="ou_owner")


def test_reject(db: Path) -> None:
    p = _make(db)
    rejected = plans.decide(db, p.plan_id, approved=False, decided_by="ou_owner")
    assert rejected.status == plans.STATUS_REJECTED


def test_expired_plan_cannot_be_approved(db: Path) -> None:
    p = _make(db)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    import sqlite3

    conn = sqlite3.connect(str(db))
    # expires_at 受触发器保护，模拟过期只能绕过触发器——这里用测试专用手段
    conn.execute("DROP TRIGGER plans_immutable")
    conn.execute("UPDATE plans SET expires_at = ? WHERE plan_id = ?", (past, p.plan_id))
    conn.commit()
    conn.close()

    with pytest.raises(plans.PlanError, match="已过期"):
        plans.decide(db, p.plan_id, approved=True, decided_by="ou_owner")

    assert plans.get(db, p.plan_id).status == plans.STATUS_EXPIRED  # type: ignore[union-attr]


def test_token_binding(db: Path) -> None:
    secret = "s3cret"
    token = plans.make_token(secret, "P-1", "2026-11-19T10:00:00+00:00")
    assert plans.verify_token(secret, "P-1", "2026-11-19T10:00:00+00:00", token)
    # 换绑 plan_id
    assert not plans.verify_token(secret, "P-2", "2026-11-19T10:00:00+00:00", token)
    # 换绑过期时间
    assert not plans.verify_token(secret, "P-1", "2026-11-19T11:00:00+00:00", token)
    # 换密钥
    assert not plans.verify_token("other", "P-1", "2026-11-19T10:00:00+00:00", token)
