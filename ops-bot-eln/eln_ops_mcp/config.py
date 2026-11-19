"""配置加载与全局约束。

所有白名单都在这里，代码里不接受来自外部（模型/用户）的任意值。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ── 硬编码白名单：容器名 ────────────────────────────────────
# 只有这些容器能被查询。新增容器需要改代码并重新部署，这是刻意的。
ALLOWED_CONTAINERS: frozenset[str] = frozenset(
    {
        "xdraw-api",
        "xdraw-worker",
        "xdraw-scheduler",
        "xdraw-web",
    }
)

# ── 硬编码白名单：允许执行的模板 ID ─────────────────────────
# 对应生产机 /opt/opsbot/run.sh 里的 case 分支。两边必须一致。
ALLOWED_TEMPLATES: frozenset[str] = frozenset(
    {
        "container_status",
        "container_logs",
        "cron_list",
        "disk_usage",
    }
)

# 日志行数上限
MAX_LOG_LINES = 2000
DEFAULT_LOG_LINES = 200


@dataclass(frozen=True)
class Settings:
    """运行时配置。来自环境变量 + 可选 yaml。"""

    ssh_alias: str = "xdraw"
    ssh_script: str = "/opt/opsbot/run.sh"
    operator_open_id: str = ""
    approval_secret: str = ""
    plan_ttl_hours: int = 2
    db_path: Path = field(default_factory=lambda: Path("./audit.db"))
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    allowed_chat_ids: frozenset[str] = frozenset()

    @classmethod
    def load(cls, config_path: str | None = None) -> "Settings":
        raw: dict = {}
        path = config_path or os.environ.get("ELN_OPS_CONFIG", "")
        if path and Path(path).is_file():
            with open(path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}

        chats = raw.get("allowed_chat_ids") or []
        if isinstance(chats, str):
            chats = [chats]

        return cls(
            ssh_alias=raw.get("ssh_alias") or os.environ.get("ELN_SSH_ALIAS", "xdraw"),
            ssh_script=raw.get("ssh_script")
            or os.environ.get("ELN_SSH_SCRIPT", "/opt/opsbot/run.sh"),
            operator_open_id=os.environ.get("OPS_OPERATOR_OPEN_ID", "")
            or raw.get("operator_open_id", ""),
            approval_secret=os.environ.get("OPS_APPROVAL_SECRET", "") or raw.get("approval_secret", ""),
            plan_ttl_hours=int(raw.get("plan_ttl_hours", 2)),
            db_path=Path(os.environ.get("OPS_DB_PATH", "") or raw.get("db_path", "./audit.db")),
            feishu_app_id=os.environ.get("FEISHU_APP_ID", ""),
            feishu_app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
            allowed_chat_ids=frozenset(str(c) for c in chats),
        )

    def require_approval_secret(self) -> str:
        if not self.approval_secret:
            raise RuntimeError(
                "OPS_APPROVAL_SECRET 未设置。审批功能不可用，拒绝继续以免产生无法验签的方案。"
            )
        return self.approval_secret
