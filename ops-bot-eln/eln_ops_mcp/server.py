"""MCP Server 入口。

工具命名约定：注册时用短名（eln_status），DeerFlow 侧加 elnops_ 前缀。
模型看到的是 elnops_eln_status。
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from . import audit, plans
from .config import DEFAULT_LOG_LINES, Settings
from .ssh import SshError, container_logs, container_status, cron_list, disk_usage

mcp = FastMCP("eln-ops")
_settings = Settings.load()


def _settings_or_reload() -> Settings:
    global _settings
    if not _settings.approval_secret:
        _settings = Settings.load()
    return _settings


# ── 只读工具 ───────────────────────────────────────────────


@mcp.tool()
def eln_status(container: str) -> str:
    """查询 ELN 某个容器的运行状态。

    Args:
        container: 容器名，必须是 xdraw-api / xdraw-worker / xdraw-scheduler / xdraw-web 之一
    """
    s = _settings_or_reload()
    try:
        res = container_status(s, container)
    except SshError as exc:
        audit.record(s.db_path, actor="agent", action="eln_status", target=container,
                     outcome="error", detail=str(exc))
        return f"查询失败：{exc}"

    audit.record(s.db_path, actor="agent", action="eln_status", target=container,
                 outcome="ok" if res.ok else "fail",
                 detail={"exit": res.exit_code})
    return res.to_text()


@mcp.tool()
def eln_logs(container: str, lines: int = DEFAULT_LOG_LINES) -> str:
    """拉取 ELN 某个容器最近的日志。

    Args:
        container: 容器名，必须是 xdraw-api / xdraw-worker / xdraw-scheduler / xdraw-web 之一
        lines: 行数，1..2000，默认 200
    """
    s = _settings_or_reload()
    try:
        res = container_logs(s, container, lines)
    except SshError as exc:
        audit.record(s.db_path, actor="agent", action="eln_logs", target=container,
                     outcome="error", detail=str(exc))
        return f"查询失败：{exc}"

    audit.record(s.db_path, actor="agent", action="eln_logs", target=container,
                 outcome="ok" if res.ok else "fail",
                 detail={"lines": lines, "exit": res.exit_code})
    return res.to_text()


@mcp.tool()
def eln_cron_check() -> str:
    """查看生产机当前 crontab 内容，用于与仓库配置比对。"""
    s = _settings_or_reload()
    try:
        res = cron_list(s)
    except SshError as exc:
        return f"查询失败：{exc}"
    audit.record(s.db_path, actor="agent", action="eln_cron_check",
                 outcome="ok" if res.ok else "fail")
    return res.to_text()


@mcp.tool()
def eln_disk() -> str:
    """查看生产机磁盘使用情况。"""
    s = _settings_or_reload()
    try:
        res = disk_usage(s)
    except SshError as exc:
        return f"查询失败：{exc}"
    audit.record(s.db_path, actor="agent", action="eln_disk",
                 outcome="ok" if res.ok else "fail")
    return res.to_text()


# ── 方案类工具 ─────────────────────────────────────────────


@mcp.tool()
def propose_remediation(
    summary: str,
    steps_json: str,
    impact: str,
    rollback: str,
    risk_level: str,
    ticket_id: str = "",
) -> str:
    """提出一个修复方案。只落库并返回方案号，不执行任何操作。

    提交后会由外部程序发飞书审批卡给负责人，负责人点批准才会执行。

    Args:
        summary: 一句话说明要做什么，用人话，不用术语
        steps_json: JSON 数组，每项形如 {"template": "container_status", "args": ["xdraw-worker"], "note": "为什么做这步"}
        impact: 影响范围，哪些服务会中断、大概多久
        rollback: 回退办法，必须写具体命令
        risk_level: low / medium / high
        ticket_id: 关联的工单号，可空
    """
    s = _settings_or_reload()
    try:
        steps = json.loads(steps_json)
    except json.JSONDecodeError as exc:
        return f"步骤 JSON 解析失败：{exc}"
    if not isinstance(steps, list):
        return "steps_json 必须是数组"

    try:
        plan = plans.create(
            s.db_path,
            summary=summary,
            steps=steps,
            impact=impact,
            rollback=rollback,
            risk_level=risk_level,
            ttl_hours=s.plan_ttl_hours,
            ticket_id=ticket_id or None,
        )
    except plans.PlanError as exc:
        return f"方案不成立：{exc}"

    token = plans.make_token(s.require_approval_secret(), plan.plan_id, plan.expires_at)

    audit.record(s.db_path, actor="agent", action="propose_remediation",
                 target=plan.plan_id, outcome="ok",
                 detail={"summary": summary, "risk": risk_level})

    return json.dumps(
        {
            "plan_id": plan.plan_id,
            "expires_at": plan.expires_at,
            "approval_token": token,
            "status": plan.status,
            "next": "方案已存库，需要调用 send_approval_card 通知负责人",
        },
        ensure_ascii=False,
    )


@mcp.tool()
def read_plan(plan_id: str) -> str:
    """读取一个方案的完整内容。

    Args:
        plan_id: 方案号，形如 P-20261119-ABC123
    """
    s = _settings_or_reload()
    plan = plans.get(s.db_path, plan_id)
    if plan is None:
        return f"方案 {plan_id} 不存在"
    return json.dumps(
        {
            "plan_id": plan.plan_id,
            "created_at": plan.created_at,
            "expires_at": plan.expires_at,
            "summary": plan.summary,
            "steps": plan.steps,
            "impact": plan.impact,
            "rollback": plan.rollback,
            "risk_level": plan.risk_level,
            "status": plan.status,
            "decided_by": plan.decided_by,
            "executed_at": plan.executed_at,
            "result": plan.result,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def list_plans(limit: int = 10) -> str:
    """列出最近的方案。

    Args:
        limit: 条数，1..100，默认 10
    """
    s = _settings_or_reload()
    try:
        items = plans.list_recent(s.db_path, limit)
    except ValueError as exc:
        return str(exc)
    if not items:
        return "暂无方案记录"
    return "\n".join(
        f"{p.plan_id}  [{p.status}]  {p.risk_level:<6}  {p.summary}" for p in items
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
