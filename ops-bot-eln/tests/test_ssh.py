"""SSH 参数校验的测试。重点是"任何自由字符串都进不去"。"""

from __future__ import annotations

from pathlib import Path

import pytest

from eln_ops_mcp import ssh
from eln_ops_mcp.config import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(ssh_alias="xdraw", db_path=tmp_path / "audit.db")


def test_rejects_unknown_template(settings: Settings) -> None:
    with pytest.raises(ssh.SshError, match="不在白名单"):
        ssh.run_template(settings, "rm_rf")


def test_rejects_unknown_container(settings: Settings) -> None:
    with pytest.raises(ssh.SshError, match="不在白名单"):
        ssh.container_status(settings, "xdraw-api; rm -rf /")


def test_rejects_unknown_container_in_logs(settings: Settings) -> None:
    with pytest.raises(ssh.SshError, match="不在白名单"):
        ssh.container_logs(settings, "../../etc/passwd", 100)


@pytest.mark.parametrize("lines", [0, -1, 2001, 99999])
def test_rejects_out_of_range_lines(settings: Settings, lines: int) -> None:
    with pytest.raises(ssh.SshError, match="1..2000"):
        ssh.container_logs(settings, "xdraw-api", lines)


@pytest.mark.parametrize("lines", ["100; whoami", "100 | cat", "$(id)", "`id`"])
def test_rejects_shell_metachars_in_lines(settings: Settings, lines: object) -> None:
    with pytest.raises(ssh.SshError):
        ssh.container_logs(settings, "xdraw-api", lines)  # type: ignore[arg-type]


def test_metachar_guard_catches_any_template_arg(settings: Settings) -> None:
    # 直连 run_template 也拦得住
    with pytest.raises(ssh.SshError, match="非法字符"):
        ssh.run_template(settings, "container_status", "xdraw-api; whoami")
    with pytest.raises(ssh.SshError, match="非法字符"):
        ssh.run_template(settings, "container_status", "xdraw-api && rm -rf /")
    with pytest.raises(ssh.SshError, match="非法字符"):
        ssh.run_template(settings, "container_status", "xdraw-api\nreboot")


def test_whitelisted_value_passes_validation(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """校验通过后应该真的调用 ssh，且 argv 里没有 shell。"""
    captured: dict = {}

    class FakeProc:
        returncode = 0
        stdout = "xdraw-api\tUp 3 hours"
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(ssh.subprocess, "run", fake_run)
    res = ssh.container_status(settings, "xdraw-api")

    assert res.ok
    assert "xdraw-api" in res.stdout
    argv = captured["argv"]
    assert argv[0] == "ssh"
    assert argv[-2] == "xdraw"
    assert argv[-1] == "/opt/opsbot/run.sh container_status xdraw-api"
    assert captured["kwargs"]["shell"] is False
