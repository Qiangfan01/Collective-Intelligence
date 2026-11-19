"""SSH 执行器。

设计要点：
1. 只接受模板 ID + 白名单内的枚举/数字参数，绝不拼接自由字符串。
2. 用参数列表调用 ssh（shell=False），不接受管道、重定向、分号。
3. 服务端 run.sh 会再次校验，双层防护。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .config import ALLOWED_CONTAINERS, ALLOWED_TEMPLATES, MAX_LOG_LINES, Settings


class SshError(RuntimeError):
    """SSH 调用失败或参数不合法。"""


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int

    def to_text(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.rstrip()}")
        if not self.ok:
            parts.append(f"[exit={self.exit_code}]")
        return "\n".join(parts) if parts else "(无输出)"


def _validate_template(template: str) -> str:
    if template not in ALLOWED_TEMPLATES:
        raise SshError(
            f"模板 {template!r} 不在白名单内。允许的模板：{sorted(ALLOWED_TEMPLATES)}"
        )
    return template


def _validate_container(name: str) -> str:
    if name not in ALLOWED_CONTAINERS:
        raise SshError(f"容器 {name!r} 不在白名单内。允许的容器：{sorted(ALLOWED_CONTAINERS)}")
    return name


def _validate_lines(lines: int) -> str:
    if not isinstance(lines, int) or isinstance(lines, bool):
        raise SshError("lines 必须是整数")
    if lines < 1 or lines > MAX_LOG_LINES:
        raise SshError(f"lines 必须在 1..{MAX_LOG_LINES} 之间")
    return str(lines)


def run_template(settings: Settings, template: str, *args: str, timeout: int = 60) -> CommandResult:
    """执行一个固定模板。

    args 必须是已经过校验的字符串。调用方负责用 _validate_* 处理。
    """
    _validate_template(template)

    # 最后一道：任何参数里出现 shell 元字符都拒绝。即便是数字校验过的，
    # 这里再兜一次底，防止将来新增模板时漏校验。
    for arg in args:
        if any(ch in arg for ch in ";|&$`<>\n\r\\\"'"):
            raise SshError(f"参数 {arg!r} 含非法字符")

    # 远程命令：只有 run.sh + 模板 ID + 参数，没有别的
    remote_cmd = " ".join([settings.ssh_script, template, *args])

    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        settings.ssh_alias,
        remote_cmd,
    ]

    try:
        proc = subprocess.run(  # noqa: S603 - argv 已逐项校验
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise SshError(f"命令超时（{timeout}s）：{template}") from exc
    except FileNotFoundError as exc:
        raise SshError("找不到 ssh 可执行文件，请确认容器内已安装 openssh-client") from exc

    return CommandResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
    )


# ── 对外暴露的窄接口 ────────────────────────────────────────


def container_status(settings: Settings, container: str) -> CommandResult:
    return run_template(settings, "container_status", _validate_container(container))


def container_logs(settings: Settings, container: str, lines: int = 200) -> CommandResult:
    return run_template(
        settings,
        "container_logs",
        _validate_container(container),
        _validate_lines(lines),
    )


def cron_list(settings: Settings) -> CommandResult:
    return run_template(settings, "cron_list")


def disk_usage(settings: Settings) -> CommandResult:
    return run_template(settings, "disk_usage")
