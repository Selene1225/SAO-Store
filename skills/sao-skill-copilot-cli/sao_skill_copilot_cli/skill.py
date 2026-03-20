"""sao-skill-copilot-cli — 委派任务给本地 AI CLI 代理执行。

通过 subprocess 调用本地 CLI（gh copilot / claude 等），
将任务 prompt 作为参数传给 CLI，捕获输出返回。

环境变量:
  SAO_COPILOT_CLI_PRESET — 默认预设名 (copilot / claude)
  SAO_COPILOT_CLI_CMD   — 自定义 CLI 命令（空格分隔，覆盖预设）
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from typing import Any

# ── 外部依赖 mock ────────────────────────────────────────────
if "sao" not in sys.modules:
    import types

    _sao = types.ModuleType("sao")
    _sao_skills = types.ModuleType("sao.skills")

    class _BaseSkillStub:
        pass

    _sao_skills.BaseSkill = _BaseSkillStub  # type: ignore[attr-defined]
    _sao.skills = _sao_skills  # type: ignore[attr-defined]
    sys.modules.setdefault("sao", _sao)
    sys.modules.setdefault("sao.skills", _sao_skills)

from sao.skills import BaseSkill  # type: ignore[import-untyped]

# ── CLI 预设 ─────────────────────────────────────────────────

CLI_PRESETS: dict[str, list[str]] = {
    "copilot": ["gh", "copilot", "suggest", "-t", "shell"],
    "claude": ["claude", "-p"],
}

_DEFAULT_PRESET = "copilot"
_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 600
_MAX_OUTPUT = 8000


class CopilotCliSkill(BaseSkill):
    """委派任务给本地 AI CLI 代理执行。"""

    def __init__(self, **kwargs: Any) -> None:
        custom = os.environ.get("SAO_COPILOT_CLI_CMD", "")
        self._custom_cmd: list[str] | None = shlex.split(custom) if custom else None
        self._default_preset: str = os.environ.get(
            "SAO_COPILOT_CLI_PRESET", _DEFAULT_PRESET
        )

    async def execute(self, tool: str, args: dict[str, Any], ctx: Any) -> str:
        handlers: dict[str, Any] = {
            "run": self._handle_run,
        }
        handler = handlers.get(tool)
        if not handler:
            return f"⚠️ 未知 tool: {tool}"
        return await handler(args)

    # ------------------------------------------------------------------
    # run — 委派任务
    # ------------------------------------------------------------------

    async def _handle_run(self, args: dict[str, Any]) -> str:
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return "⚠️ 缺少参数 `prompt`"

        timeout = max(10, min(int(args.get("timeout") or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))

        # ── 确定 CLI 命令 ────────────────────────────────────
        cmd_parts = self._resolve_cli(args.get("cli"))
        if isinstance(cmd_parts, str):
            return cmd_parts  # error message

        # prompt 作为最后一个参数，create_subprocess_exec 不经过 shell，防注入
        full_cmd = [*cmd_parts, prompt]

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return f"⚠️ 执行超时（{timeout}s），已终止进程"
        except FileNotFoundError:
            return f"⚠️ 未找到命令 `{cmd_parts[0]}`，请确认已安装并在 PATH 中"
        except OSError as e:
            return f"⚠️ 启动进程失败: {e}"

        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()

        if proc.returncode != 0 and not stdout:
            msg = stderr[:2000] if stderr else f"退出码 {proc.returncode}"
            return f"⚠️ CLI 执行失败:\n{msg}"

        if len(stdout) > _MAX_OUTPUT:
            stdout = stdout[:_MAX_OUTPUT] + "\n\n… (输出已截断)"

        result = f"📋 执行结果:\n\n{stdout}"
        if stderr and proc.returncode != 0:
            result += f"\n\n⚠️ 错误:\n{stderr[:1000]}"

        return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_cli(self, cli_arg: str | None) -> list[str] | str:
        """根据参数/环境变量/预设确定 CLI 命令列表。返回 str 表示错误。"""
        cli_key = (cli_arg or "").strip()
        if cli_key:
            preset = CLI_PRESETS.get(cli_key)
            if not preset:
                available = ", ".join(sorted(CLI_PRESETS.keys()))
                return f"⚠️ 未知 CLI 预设: {cli_key}\n可用预设: {available}"
            return list(preset)

        if self._custom_cmd:
            return list(self._custom_cmd)

        return list(CLI_PRESETS.get(self._default_preset, CLI_PRESETS[_DEFAULT_PRESET]))
