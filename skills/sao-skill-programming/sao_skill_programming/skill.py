"""Programming 技能 — 全周期开发：需求解析 → 编码 → 测试 → 上线。

SubAgent 循环调用本 Skill 的 tools 完成开发任务：
    init → write_file / read_file → run (test/build) → push
    遇到不确定的问题时，SubAgent 通过 ctx 向主 Agent 汇报。

工作区: ~/.sao/workspaces/{session_id}/
每次会话一个隔离目录，结束后可保留或清理。
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sao.skills import BaseSkill, SkillContext
from sao.utils.logger import logger

# 工作区根目录
_WORKSPACES_ROOT = Path.home() / ".sao" / "workspaces"

# 命令执行默认超时（秒）
_DEFAULT_TIMEOUT = 120

# 命令输出截断长度（字符）
_MAX_OUTPUT_LEN = 4000


class ProgrammingSkill(BaseSkill):
    """全周期编程技能 — SubAgent 通过 tools 驱动开发流程。"""

    name = "programming"
    description = "全周期开发：需求解析→编码→测试→上线，遇阻汇报"

    def __init__(self, **kwargs: Any) -> None:
        self._workspace: Path | None = None
        self._session_id: str = kwargs.get("session_id", "default")

    # ── 技能入口 ──────────────────────────────────────

    async def execute(self, tool: str, args: dict[str, Any], ctx: SkillContext) -> str | None:
        handlers = {
            "init": self._handle_init,
            "write_file": self._handle_write_file,
            "read_file": self._handle_read_file,
            "run": self._handle_run,
            "push": self._handle_push,
        }
        handler = handlers.get(tool)
        if not handler:
            return f"⚠️ 未知的 programming 工具: {tool}"
        return await handler(args, ctx)

    # ── init — 初始化工作区 ───────────────────────────

    async def _handle_init(self, args: dict, ctx: SkillContext) -> str:
        """初始化工作区：clone 仓库 或 创建空目录。"""
        repo_url = (args.get("repo_url") or "").strip()
        branch = (args.get("branch") or "main").strip()

        workspace = _WORKSPACES_ROOT / self._session_id
        workspace.mkdir(parents=True, exist_ok=True)
        self._workspace = workspace

        if repo_url:
            # clone 仓库
            result = await self._run_command(
                f"git clone --branch {branch} --depth 50 {repo_url} .",
                cwd=workspace,
                timeout=60,
            )
            if result["returncode"] != 0:
                return f"❌ Clone 失败:\n```\n{result['stderr']}\n```"

            # 列出文件结构帮助 SubAgent 理解项目
            tree = self._list_tree(workspace, max_depth=2)
            return (
                f"✅ 仓库已 clone 到工作区\n"
                f"📂 分支: {branch}\n"
                f"📁 目录结构:\n```\n{tree}\n```"
            )
        else:
            return f"✅ 空工作区已创建: {workspace.name}"

    # ── write_file — 写入文件 ─────────────────────────

    async def _handle_write_file(self, args: dict, ctx: SkillContext) -> str:
        """创建或覆盖工作区中的文件。"""
        self._ensure_workspace()
        rel_path = args.get("path", "").strip()
        content = args.get("content", "")

        if not rel_path:
            return "⚠️ 请提供文件路径"

        target = self._safe_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        is_new = not target.exists()
        target.write_text(content, encoding="utf-8")

        action = "创建" if is_new else "覆盖"
        lines = content.count("\n") + 1
        return f"✅ {action} {rel_path} ({lines} 行)"

    # ── read_file — 读取文件 ──────────────────────────

    async def _handle_read_file(self, args: dict, ctx: SkillContext) -> str:
        """读取工作区中的文件内容。"""
        self._ensure_workspace()
        rel_path = args.get("path", "").strip()

        if not rel_path:
            return "⚠️ 请提供文件路径"

        target = self._safe_path(rel_path)
        if not target.exists():
            return f"❌ 文件不存在: {rel_path}"
        if not target.is_file():
            return f"❌ 不是文件: {rel_path}"

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"⚠️ {rel_path} 不是文本文件，无法读取"

        # 大文件截断
        if len(content) > _MAX_OUTPUT_LEN:
            content = content[:_MAX_OUTPUT_LEN] + f"\n... (截断，共 {len(content)} 字符)"

        return f"📄 {rel_path}:\n```\n{content}\n```"

    # ── run — 执行命令 ────────────────────────────────

    async def _handle_run(self, args: dict, ctx: SkillContext) -> str:
        """在工作区执行 shell 命令。"""
        self._ensure_workspace()
        command = args.get("command", "").strip()
        timeout = args.get("timeout", _DEFAULT_TIMEOUT)

        if not command:
            return "⚠️ 请提供要执行的命令"

        # 安全检查：禁止危险命令
        danger = self._check_dangerous(command)
        if danger:
            return f"🚫 安全限制: {danger}"

        await ctx.channel.send(ctx.chat_id, f"⏳ 执行中: `{command}`")

        result = await self._run_command(command, cwd=self._workspace, timeout=timeout)

        output_parts = []
        if result["stdout"]:
            stdout = self._truncate(result["stdout"])
            output_parts.append(f"**stdout:**\n```\n{stdout}\n```")
        if result["stderr"]:
            stderr = self._truncate(result["stderr"])
            output_parts.append(f"**stderr:**\n```\n{stderr}\n```")

        status = "✅ 成功" if result["returncode"] == 0 else f"❌ 退出码 {result['returncode']}"
        output = "\n\n".join(output_parts) if output_parts else "(无输出)"

        return f"{status}\n\n{output}"

    # ── push — 提交并推送 ─────────────────────────────

    async def _handle_push(self, args: dict, ctx: SkillContext) -> str:
        """Git commit + push 到远程仓库。"""
        self._ensure_workspace()
        message = args.get("message", "").strip()
        branch = (args.get("branch") or "").strip()

        if not message:
            return "⚠️ 请提供 commit message"

        # git add -A
        result = await self._run_command("git add -A", cwd=self._workspace)
        if result["returncode"] != 0:
            return f"❌ git add 失败:\n```\n{result['stderr']}\n```"

        # 检查是否有变更
        result = await self._run_command("git diff --cached --quiet", cwd=self._workspace)
        if result["returncode"] == 0:
            return "ℹ️ 没有待提交的变更"

        # git commit
        result = await self._run_command(
            f'git commit -m "{message}"', cwd=self._workspace
        )
        if result["returncode"] != 0:
            return f"❌ git commit 失败:\n```\n{result['stderr']}\n```"

        # git push
        push_cmd = f"git push origin {branch}" if branch else "git push"
        result = await self._run_command(push_cmd, cwd=self._workspace, timeout=60)
        if result["returncode"] != 0:
            return f"❌ git push 失败:\n```\n{result['stderr']}\n```"

        return f"✅ 已提交并推送\n📝 {message}"

    # ── 内部工具方法 ──────────────────────────────────

    def _ensure_workspace(self):
        """确保工作区已初始化。"""
        if self._workspace is None or not self._workspace.exists():
            raise RuntimeError(
                "工作区未初始化，请先调用 init 工具"
            )

    def _safe_path(self, rel_path: str) -> Path:
        """解析相对路径，防止路径穿越。"""
        assert self._workspace is not None
        target = (self._workspace / rel_path).resolve()
        if not str(target).startswith(str(self._workspace.resolve())):
            raise ValueError(f"路径越界: {rel_path}")
        return target

    @staticmethod
    async def _run_command(
        command: str,
        cwd: Path,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """异步执行 shell 命令。"""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return {
                "returncode": proc.returncode,
                "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                "stderr": stderr_bytes.decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"命令超时 ({timeout}s)",
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
            }

    @staticmethod
    def _truncate(text: str, max_len: int = _MAX_OUTPUT_LEN) -> str:
        """截断过长输出。"""
        if len(text) <= max_len:
            return text
        return text[:max_len] + f"\n... (截断，共 {len(text)} 字符)"

    @staticmethod
    def _check_dangerous(command: str) -> str | None:
        """检查危险命令，返回原因或 None。"""
        cmd_lower = command.lower().strip()
        # 禁止的命令模式
        blocked = [
            ("rm -rf /", "禁止删除根目录"),
            ("rm -rf ~", "禁止删除 home 目录"),
            ("format ", "禁止格式化磁盘"),
            ("mkfs", "禁止格式化磁盘"),
            (":(){:|:&};:", "禁止 fork bomb"),
            ("dd if=", "禁止 dd 写入"),
        ]
        for pattern, reason in blocked:
            if pattern in cmd_lower:
                return reason
        return None

    @staticmethod
    def _list_tree(root: Path, max_depth: int = 2, prefix: str = "") -> str:
        """生成简化的目录树。"""
        lines: list[str] = []
        try:
            entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return f"{prefix}(权限不足)"

        # 跳过隐藏文件和常见噪音目录
        skip = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox"}
        entries = [e for e in entries if e.name not in skip]

        for i, entry in enumerate(entries[:30]):  # 最多显示 30 项
            connector = "└── " if i == len(entries) - 1 else "├── "
            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                if max_depth > 1:
                    sub = ProgrammingSkill._list_tree(
                        entry, max_depth - 1, prefix + ("    " if i == len(entries) - 1 else "│   ")
                    )
                    if sub:
                        lines.append(sub)
            else:
                lines.append(f"{prefix}{connector}{entry.name}")

        if len(entries) > 30:
            lines.append(f"{prefix}... ({len(entries) - 30} more)")

        return "\n".join(lines)
