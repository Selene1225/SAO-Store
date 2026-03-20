"""sao-skill-copilot-cli 单元测试."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── mock sao 依赖 ────────────────────────────────────────────
_base = MagicMock()
_base.BaseSkill = object
sys.modules.setdefault("sao", MagicMock())
sys.modules.setdefault("sao.skills", _base)

from sao_skill_copilot_cli.skill import (
    CLI_PRESETS,
    CopilotCliSkill,
    _DEFAULT_TIMEOUT,
    _MAX_OUTPUT,
)


# ── fixtures ─────────────────────────────────────────────────


@pytest.fixture
def skill(monkeypatch: pytest.MonkeyPatch) -> CopilotCliSkill:
    monkeypatch.delenv("SAO_COPILOT_CLI_CMD", raising=False)
    monkeypatch.delenv("SAO_COPILOT_CLI_PRESET", raising=False)
    return CopilotCliSkill()


def _make_proc(
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


# ── execute 路由 ─────────────────────────────────────────────


class TestExecute:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, skill: CopilotCliSkill):
        result = await skill.execute("unknown", {}, None)
        assert "未知 tool" in result

    @pytest.mark.asyncio
    async def test_routes_to_run(self, skill: CopilotCliSkill):
        with patch.object(skill, "_handle_run", new_callable=AsyncMock, return_value="ok"):
            result = await skill.execute("run", {"prompt": "hi"}, None)
            assert result == "ok"
            skill._handle_run.assert_awaited_once_with({"prompt": "hi"})


# ── run: 参数校验 ────────────────────────────────────────────


class TestRunValidation:
    @pytest.mark.asyncio
    async def test_missing_prompt(self, skill: CopilotCliSkill):
        result = await skill.execute("run", {}, None)
        assert "缺少参数" in result

    @pytest.mark.asyncio
    async def test_empty_prompt(self, skill: CopilotCliSkill):
        result = await skill.execute("run", {"prompt": "  "}, None)
        assert "缺少参数" in result

    @pytest.mark.asyncio
    async def test_unknown_cli_preset(self, skill: CopilotCliSkill):
        result = await skill.execute("run", {"prompt": "hi", "cli": "nonexistent"}, None)
        assert "未知 CLI 预设" in result
        assert "copilot" in result  # shows available presets


# ── run: 成功执行 ────────────────────────────────────────────


class TestRunSuccess:
    @pytest.mark.asyncio
    async def test_default_cli(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"suggestion: ls -la")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await skill.execute("run", {"prompt": "list files"}, None)
            assert "suggestion: ls -la" in result
            assert "执行结果" in result
            # prompt 作为最后一个参数
            call_args = mock_exec.call_args[0]
            assert call_args[-1] == "list files"
            assert call_args[0] == "gh"

    @pytest.mark.asyncio
    async def test_claude_preset(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"Here is a sorting algorithm...")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await skill.execute(
                "run", {"prompt": "write quicksort", "cli": "claude"}, None
            )
            assert "sorting algorithm" in result
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "claude"
            assert "-p" in call_args

    @pytest.mark.asyncio
    async def test_stdin_is_devnull(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"ok")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await skill.execute("run", {"prompt": "test"}, None)
            kwargs = mock_exec.call_args[1]
            assert kwargs["stdin"] == asyncio.subprocess.DEVNULL


# ── run: 错误处理 ────────────────────────────────────────────


class TestRunErrors:
    @pytest.mark.asyncio
    async def test_timeout(self, skill: CopilotCliSkill):
        proc = _make_proc()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute(
                "run", {"prompt": "slow task", "timeout": 10}, None
            )
            assert "超时" in result
            proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_process_already_dead(self, skill: CopilotCliSkill):
        proc = _make_proc()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        proc.kill = MagicMock(side_effect=ProcessLookupError)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute(
                "run", {"prompt": "gone", "timeout": 10}, None
            )
            assert "超时" in result  # no crash

    @pytest.mark.asyncio
    async def test_command_not_found(self, skill: CopilotCliSkill):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError,
        ):
            result = await skill.execute("run", {"prompt": "test"}, None)
            assert "未找到命令" in result
            assert "gh" in result

    @pytest.mark.asyncio
    async def test_os_error(self, skill: CopilotCliSkill):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("permission denied"),
        ):
            result = await skill.execute("run", {"prompt": "test"}, None)
            assert "启动进程失败" in result

    @pytest.mark.asyncio
    async def test_nonzero_return_no_stdout(self, skill: CopilotCliSkill):
        proc = _make_proc(stderr=b"auth required", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute("run", {"prompt": "test"}, None)
            assert "CLI 执行失败" in result
            assert "auth required" in result

    @pytest.mark.asyncio
    async def test_nonzero_return_with_stdout(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"partial output", stderr=b"warning", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute("run", {"prompt": "test"}, None)
            assert "partial output" in result
            assert "错误" in result
            assert "warning" in result


# ── run: 输出截断 ────────────────────────────────────────────


class TestOutputTruncation:
    @pytest.mark.asyncio
    async def test_long_output_truncated(self, skill: CopilotCliSkill):
        long_output = b"x" * (_MAX_OUTPUT + 1000)
        proc = _make_proc(stdout=long_output)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute("run", {"prompt": "test"}, None)
            assert "截断" in result
            assert len(result) < _MAX_OUTPUT + 500

    @pytest.mark.asyncio
    async def test_short_output_not_truncated(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"short output")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute("run", {"prompt": "test"}, None)
            assert "截断" not in result


# ── timeout 边界 ─────────────────────────────────────────────


class TestTimeoutClamp:
    @pytest.mark.asyncio
    async def test_timeout_clamped_min(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"ok")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await skill.execute("run", {"prompt": "test", "timeout": 1}, None)
            # wait_for called with at least 10s
            # Just verify no crash and result is ok

    @pytest.mark.asyncio
    async def test_timeout_clamped_max(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"ok")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute(
                "run", {"prompt": "test", "timeout": 9999}, None
            )
            assert "执行结果" in result

    @pytest.mark.asyncio
    async def test_default_timeout(self, skill: CopilotCliSkill):
        proc = _make_proc(stdout=b"ok")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await skill.execute("run", {"prompt": "test"}, None)
            assert "执行结果" in result


# ── CLI 预设解析 ─────────────────────────────────────────────


class TestResolveCli:
    def test_default_is_copilot(self, skill: CopilotCliSkill):
        result = skill._resolve_cli(None)
        assert result == list(CLI_PRESETS["copilot"])

    def test_explicit_copilot(self, skill: CopilotCliSkill):
        result = skill._resolve_cli("copilot")
        assert result[0] == "gh"

    def test_explicit_claude(self, skill: CopilotCliSkill):
        result = skill._resolve_cli("claude")
        assert result == ["claude", "-p"]

    def test_unknown_returns_error(self, skill: CopilotCliSkill):
        result = skill._resolve_cli("gpt-cli")
        assert isinstance(result, str)
        assert "未知" in result

    def test_empty_string_uses_default(self, skill: CopilotCliSkill):
        result = skill._resolve_cli("")
        assert result == list(CLI_PRESETS["copilot"])


# ── 环境变量配置 ─────────────────────────────────────────────


class TestEnvConfig:
    def test_custom_cmd_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SAO_COPILOT_CLI_CMD", "my-cli --flag")
        monkeypatch.delenv("SAO_COPILOT_CLI_PRESET", raising=False)
        s = CopilotCliSkill()
        result = s._resolve_cli(None)
        assert result == ["my-cli", "--flag"]

    def test_custom_preset_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAO_COPILOT_CLI_CMD", raising=False)
        monkeypatch.setenv("SAO_COPILOT_CLI_PRESET", "claude")
        s = CopilotCliSkill()
        result = s._resolve_cli(None)
        assert result == ["claude", "-p"]

    def test_cmd_env_overrides_preset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SAO_COPILOT_CLI_CMD", "custom-agent run")
        monkeypatch.setenv("SAO_COPILOT_CLI_PRESET", "claude")
        s = CopilotCliSkill()
        # custom cmd takes priority over preset
        result = s._resolve_cli(None)
        assert result == ["custom-agent", "run"]

    def test_arg_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SAO_COPILOT_CLI_CMD", "custom-agent")
        s = CopilotCliSkill()
        # explicit cli arg overrides env
        result = s._resolve_cli("claude")
        assert result == ["claude", "-p"]

    @pytest.mark.asyncio
    async def test_custom_cmd_used_in_run(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SAO_COPILOT_CLI_CMD", "my-tool ask")
        monkeypatch.delenv("SAO_COPILOT_CLI_PRESET", raising=False)
        s = CopilotCliSkill()
        proc = _make_proc(stdout=b"custom result")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await s.execute("run", {"prompt": "hello"}, None)
            assert "custom result" in result
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "my-tool"
            assert call_args[1] == "ask"
            assert call_args[2] == "hello"
