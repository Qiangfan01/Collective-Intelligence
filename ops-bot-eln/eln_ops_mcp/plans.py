"""方案账本。

方案一旦创建即不可修改。状态流转只允许：
    pending -> approved / rejected / expired
approve 之后 create 的内容不能变（用触发器拦 UPDATE 关键字段）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    plan_id      TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    ticket_id    TEXT,
    summary      TEXT NOT NULL,
    steps        TEXT NOT NULL,
    impact       TEXT NOT NULL,
    rollback     TEXT NOT NULL,
    risk_level   TEXT NOT NULL,
    status       TEXT NOT NULL,
    decided_at   TEXT,
    decided_by   TEXT,
    executed_at  TEXT,
    result       TEXT
);

CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);

-- 方案正文不可变：只有状态相关字段允许更新
CREATE TRIGGER IF NOT EXISTS plans_immutable
BEFORE UPDATE ON plans
WHEN OLD.summary <> NEW.summary
  OR OLD.steps   <> NEW.steps
  OR OLD.impact  <> NEW.impact
  OR OLD.rollback <> NEW.rollback
  OR OLD.risk_level <> NEW.risk_level
  OR OLD.expires_at <> NEW.expires_at
BEGIN
    SELECT RAISE(ABORT, 'plan body is immutable');
END;
"""

VALID_RISK = {"low", "medium", "high"}
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"


class PlanError(RuntimeError):
    """方案操作非法。"""


@dataclass(frozen=True)
class Plan:
    plan_id: str
    created_at: str
    expires_at: str
    summary: str
    steps: list[dict[str, Any]]
    impact: str
    rollback: str
    risk_level: str
    status: str
    ticket_id: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    executed_at: str | None = None
    result: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        yield conn
    finally:
        conn.close()


def make_token(secret: str, plan_id: str, expires_at: str) -> str:
    """方案签名。绑定 plan_id 与过期时间，防止换绑。"""
    msg = f"{plan_id}|{expires_at}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


def verify_token(secret: str, plan_id: str, expires_at: str, token: str) -> bool:
    expected = make_token(secret, plan_id, expires_at)
    return hmac.compare_digest(expected, token)


def create(
    db_path: Path,
    *,
    summary: str,
    steps: list[dict[str, Any]],
    impact: str,
    rollback: str,
    risk_level: str,
    ttl_hours: int = 2,
    ticket_id: str | None = None,
) -> Plan:
    if risk_level not in VALID_RISK:
        raise PlanError(f"risk_level 必须是 {sorted(VALID_RISK)} 之一")
    if not summary.strip():
        raise PlanError("summary 不能为空")
    if not steps:
        raise PlanError("steps 不能为空")
    if not impact.strip():
        raise PlanError("impact 不能为空")
    if not rollback.strip():
        raise PlanError("rollback 不能为空")

    now = _now()
    plan_id = f"P-{now:%Y%m%d}-{secrets.token_hex(3).upper()}"
    expires_at = _iso(now + timedelta(hours=ttl_hours))

    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO plans (plan_id, created_at, expires_at, ticket_id, summary,"
            " steps, impact, rollback, risk_level, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan_id,
                _iso(now),
                expires_at,
                ticket_id,
                summary.strip(),
                json.dumps(steps, ensure_ascii=False),
                impact.strip(),
                rollback.strip(),
                risk_level,
                STATUS_PENDING,
            ),
        )
        conn.commit()

    return Plan(
        plan_id=plan_id,
        created_at=_iso(now),
        expires_at=expires_at,
        summary=summary.strip(),
        steps=steps,
        impact=impact.strip(),
        rollback=rollback.strip(),
        risk_level=risk_level,
        status=STATUS_PENDING,
        ticket_id=ticket_id,
    )


def get(db_path: Path, plan_id: str) -> Plan | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
    if row is None:
        return None
    return Plan(
        plan_id=row["plan_id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        summary=row["summary"],
        steps=json.loads(row["steps"]),
        impact=row["impact"],
        rollback=row["rollback"],
        risk_level=row["risk_level"],
        status=row["status"],
        ticket_id=row["ticket_id"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        executed_at=row["executed_at"],
        result=row["result"],
    )


def is_expired(plan: Plan) -> bool:
    return _now() >= datetime.fromisoformat(plan.expires_at)


def decide(
    db_path: Path, plan_id: str, *, approved: bool, decided_by: str
) -> Plan:
    """裁决方案。过期或重复裁决都会报错。"""
    plan = get(db_path, plan_id)
    if plan is None:
        raise PlanError(f"方案 {plan_id} 不存在")
    if plan.status != STATUS_PENDING:
        raise PlanError(f"方案 {plan_id} 状态为 {plan.status}，不能再次裁决")
    if is_expired(plan):
        with _connect(db_path) as conn:
            conn.execute(
                "UPDATE plans SET status = ?, decided_at = ? WHERE plan_id = ?",
                (STATUS_EXPIRED, _iso(_now()), plan_id),
            )
            conn.commit()
        raise PlanError(f"方案 {plan_id} 已过期，请重新发起")

    new_status = STATUS_APPROVED if approved else STATUS_REJECTED
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE plans SET status = ?, decided_at = ?, decided_by = ? WHERE plan_id = ?",
            (new_status, _iso(_now()), decided_by, plan_id),
        )
        conn.commit()

    updated = get(db_path, plan_id)
    assert updated is not None
    return updated


def mark_executed(db_path: Path, plan_id: str, result: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE plans SET executed_at = ?, result = ? WHERE plan_id = ?",
            (_iso(_now()), result, plan_id),
        )
        conn.commit()


def list_recent(db_path: Path, limit: int = 10) -> list[Plan]:
    if limit < 1 or limit > 100:
        raise ValueError("limit 必须在 1..100 之间")
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT plan_id FROM plans ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        p = get(db_path, r["plan_id"])
        if p:
            out.append(p)
    return out
