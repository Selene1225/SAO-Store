"""Programming Skill 单元测试。

测试覆盖:
- _safe_path: 路径穿越防护
- _check_dangerous: 危险命令拦截
- _truncate: 输出截断
- _list_tree: 目录树生成
- _handle_write_file / _handle_read_file: 文件读写（用临时目录）
- _handle_init: 空工作区初始化
- execute: 未知 tool 处理
- _ensure_workspace: 工作区未初始化检查
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 在顶层 mock 掉 sao 依赖，避免 import 失败 ──
# Programming Skill 依赖 sao.skills.BaseSkill / sao.utils.logger，
# 这些在 SAO-Store 单独测试时不存在。

_base_skill_mock = MagicMock()
_base_skill_mock.BaseSkill = object  # 让继承生效
_base_skill_mock.SkillContext = MagicMock

sys.modules.setdefault("sao", MagicMock())
sys.modules.setdefault("sao.skills", _base_skill_mock)
sys.modules.setdefault("sao.utils", MagicMock())
sys.modules.setdefault("sao.utils.logger", MagicMock())

from sao_skill_programming.skill import ProgrammingSkill  # noqa: E402


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """创建临时工作区目录。"""
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def skill(tmp_workspace: Path) -> ProgrammingSkill:
    """创建带有已初始化工作区的 ProgrammingSkill 实例。"""
    ctx = MagicMock()
    ctx.session_id = "test-session"
    s = ProgrammingSkill(ctx)
    s._workspace = tmp_workspace
    return s


@pytest.fixture
def mock_ctx() -> MagicMock:
    """创建 mock SkillContext。"""
    ctx = MagicMock()
    ctx.chat_id = "test-chat"
    ctx.channel = MagicMock()
    ctx.channel.send = AsyncMock()
    return ctx


# ── _safe_path 测试 ──────────────────────────────────


class TestSafePath:
    """路径穿越防护测试。"""

    def test_normal_path(self, skill: ProgrammingSkill, tmp_workspace: Path):
        """正常相对路径应该解析到工作区内。"""
        result = skill._safe_path("src/main.py")
        assert str(result).startswith(str(tmp_workspace.resolve()))

    def test_nested_path(self, skill: ProgrammingSkill, tmp_workspace: Path):
        """多层嵌套路径应该解析到工作区内。"""
        result = skill._safe_path("a/b/c/d.txt")
        assert str(result).startswith(str(tmp_workspace.resolve()))

    def test_traversal_attack(self, skill: ProgrammingSkill):
        """../../../ 路径穿越应该抛出 ValueError。"""
        with pytest.raises(ValueError, match="路径越界"):
            skill._safe_path("../../../etc/passwd")

    def test_traversal_with_dots(self, skill: ProgrammingSkill):
        """复杂路径穿越应该被拦截。"""
        with pytest.raises(ValueError, match="路径越界"):
            skill._safe_path("foo/../../../../../../tmp/evil")

    def test_absolute_path_outside(self, skill: ProgrammingSkill):
        """绝对路径指向工作区外应该被拦截。"""
        if os.name == "nt":
            evil = "C:\\Windows\\System32\\cmd.exe"
        else:
            evil = "/etc/passwd"
        with pytest.raises((ValueError, AssertionError)):
            skill._safe_path(evil)


# ── _check_dangerous 测试 ────────────────────────────


class TestCheckDangerous:
    """危险命令检测测试。"""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf ~",
            "RM -RF /",  # 大小写
            "format C:",
            "mkfs.ext4 /dev/sda",
            ":(){:|:&};:",
            "dd if=/dev/zero of=/dev/sda",
        ],
    )
    def test_blocked_commands(self, command: str):
        """已知危险命令应该被拦截。"""
        result = ProgrammingSkill._check_dangerous(command)
        assert result is not None, f"应该拦截: {command}"

    @pytest.mark.parametrize(
        "command",
        [
            "pytest -v",
            "python main.py",
            "npm test",
            "git status",
            "ls -la",
            "cat README.md",
            "pip install flask",
            "rm -rf node_modules",  # 这是安全的
        ],
    )
    def test_safe_commands(self, command: str):
        """正常命令不应该被拦截。"""
        result = ProgrammingSkill._check_dangerous(command)
        assert result is None, f"不应该拦截: {command}"


# ── _truncate 测试 ───────────────────────────────────


class TestTruncate:
    """输出截断测试。"""

    def test_short_text_unchanged(self):
        """短文本原样返回。"""
        text = "hello world"
        assert ProgrammingSkill._truncate(text) == text

    def test_exact_limit_unchanged(self):
        """恰好等于限制长度时不截断。"""
        text = "x" * 4000
        assert ProgrammingSkill._truncate(text, max_len=4000) == text

    def test_over_limit_truncated(self):
        """超过限制时截断并附加提示。"""
        text = "x" * 5000
        result = ProgrammingSkill._truncate(text, max_len=100)
        assert len(result) < 5000
        assert result.startswith("x" * 100)
        assert "截断" in result
        assert "5000" in result

    def test_empty_text(self):
        """空字符串原样返回。"""
        assert ProgrammingSkill._truncate("") == ""


# ── _list_tree 测试 ──────────────────────────────────


class TestListTree:
    """目录树生成测试。"""

    def test_empty_dir(self, tmp_path: Path):
        """空目录返回空字符串。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = ProgrammingSkill._list_tree(empty)
        assert result == ""

    def test_flat_files(self, tmp_path: Path):
        """只有文件的目录。"""
        d = tmp_path / "flat"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "b.py").write_text("b")

        result = ProgrammingSkill._list_tree(d)
        assert "a.txt" in result
        assert "b.py" in result

    def test_nested_dirs(self, tmp_path: Path):
        """嵌套目录显示层级。"""
        d = tmp_path / "nested"
        d.mkdir()
        (d / "src").mkdir()
        (d / "src" / "main.py").write_text("code")
        (d / "README.md").write_text("readme")

        result = ProgrammingSkill._list_tree(d, max_depth=2)
        assert "src/" in result
        assert "main.py" in result
        assert "README.md" in result

    def test_skips_noise_dirs(self, tmp_path: Path):
        """应跳过 .git / __pycache__ / node_modules 等。"""
        d = tmp_path / "proj"
        d.mkdir()
        (d / ".git").mkdir()
        (d / "__pycache__").mkdir()
        (d / "node_modules").mkdir()
        (d / "src").mkdir()
        (d / "src" / "app.py").write_text("code")

        result = ProgrammingSkill._list_tree(d)
        assert ".git" not in result
        assert "__pycache__" not in result
        assert "node_modules" not in result
        assert "src/" in result

    def test_max_depth_respected(self, tmp_path: Path):
        """max_depth=1 时不展开子目录内容。"""
        d = tmp_path / "deep"
        d.mkdir()
        (d / "a").mkdir()
        (d / "a" / "b").mkdir()
        (d / "a" / "b" / "c.txt").write_text("deep")

        result = ProgrammingSkill._list_tree(d, max_depth=1)
        assert "a/" in result
        assert "c.txt" not in result  # 深层文件不显示


# ── execute 路由测试 ─────────────────────────────────


class TestExecute:
    """execute() 路由分发测试。"""

    @pytest.mark.asyncio
    async def test_unknown_tool(self, skill: ProgrammingSkill, mock_ctx: MagicMock):
        """未知 tool 应返回警告。"""
        result = await skill.execute("nonexistent", {}, mock_ctx)
        assert "未知" in result
        assert "nonexistent" in result

    @pytest.mark.asyncio
    async def test_all_tools_routable(self, skill: ProgrammingSkill):
        """5 个 tool 名都应该有对应 handler。"""
        tools = ["init", "write_file", "read_file", "run", "push"]
        handlers = {
            "init": skill._handle_init,
            "write_file": skill._handle_write_file,
            "read_file": skill._handle_read_file,
            "run": skill._handle_run,
            "push": skill._handle_push,
        }
        for t in tools:
            assert t in handlers, f"tool '{t}' 没有 handler"


# ── _ensure_workspace 测试 ───────────────────────────


class TestEnsureWorkspace:
    """工作区初始化检查测试。"""

    def test_raises_when_no_workspace(self):
        """工作区为 None 时应抛出 RuntimeError。"""
        ctx = MagicMock()
        ctx.session_id = "test"
        s = ProgrammingSkill(ctx)
        s._workspace = None
        with pytest.raises(RuntimeError, match="工作区未初始化"):
            s._ensure_workspace()

    def test_raises_when_workspace_missing(self, tmp_path: Path):
        """工作区目录不存在时应抛出 RuntimeError。"""
        ctx = MagicMock()
        ctx.session_id = "test"
        s = ProgrammingSkill(ctx)
        s._workspace = tmp_path / "nonexistent"
        with pytest.raises(RuntimeError, match="工作区未初始化"):
            s._ensure_workspace()


# ── write_file / read_file 集成测试 ──────────────────


class TestFileOperations:
    """文件读写集成测试（使用临时目录）。"""

    @pytest.mark.asyncio
    async def test_write_new_file(self, skill: ProgrammingSkill, mock_ctx: MagicMock, tmp_workspace: Path):
        """写入新文件应创建文件并返回确认。"""
        result = await skill._handle_write_file(
            {"path": "hello.py", "content": "print('hello')\n"},
            mock_ctx,
        )
        assert "创建" in result
        assert "hello.py" in result
        assert (tmp_workspace / "hello.py").read_text() == "print('hello')\n"

    @pytest.mark.asyncio
    async def test_write_overwrite(self, skill: ProgrammingSkill, mock_ctx: MagicMock, tmp_workspace: Path):
        """覆盖已有文件应返回"覆盖"。"""
        (tmp_workspace / "x.txt").write_text("old")
        result = await skill._handle_write_file(
            {"path": "x.txt", "content": "new"},
            mock_ctx,
        )
        assert "覆盖" in result
        assert (tmp_workspace / "x.txt").read_text() == "new"

    @pytest.mark.asyncio
    async def test_write_nested_path(self, skill: ProgrammingSkill, mock_ctx: MagicMock, tmp_workspace: Path):
        """自动创建中间目录。"""
        result = await skill._handle_write_file(
            {"path": "src/pkg/main.py", "content": "code"},
            mock_ctx,
        )
        assert "创建" in result
        assert (tmp_workspace / "src" / "pkg" / "main.py").exists()

    @pytest.mark.asyncio
    async def test_write_empty_path(self, skill: ProgrammingSkill, mock_ctx: MagicMock):
        """空路径应返回警告。"""
        result = await skill._handle_write_file({"path": "", "content": "x"}, mock_ctx)
        assert "请提供文件路径" in result

    @pytest.mark.asyncio
    async def test_read_existing_file(self, skill: ProgrammingSkill, mock_ctx: MagicMock, tmp_workspace: Path):
        """读取已有文件应返回内容。"""
        (tmp_workspace / "data.txt").write_text("hello world")
        result = await skill._handle_read_file({"path": "data.txt"}, mock_ctx)
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, skill: ProgrammingSkill, mock_ctx: MagicMock):
        """读取不存在的文件应返回错误。"""
        result = await skill._handle_read_file({"path": "nope.txt"}, mock_ctx)
        assert "不存在" in result

    @pytest.mark.asyncio
    async def test_read_large_file_truncated(self, skill: ProgrammingSkill, mock_ctx: MagicMock, tmp_workspace: Path):
        """大文件应截断。"""
        (tmp_workspace / "big.txt").write_text("x" * 10000)
        result = await skill._handle_read_file({"path": "big.txt"}, mock_ctx)
        assert "截断" in result

    @pytest.mark.asyncio
    async def test_read_empty_path(self, skill: ProgrammingSkill, mock_ctx: MagicMock):
        """空路径应返回警告。"""
        result = await skill._handle_read_file({"path": ""}, mock_ctx)
        assert "请提供文件路径" in result


# ── init 测试 ────────────────────────────────────────


class TestInit:
    """init tool 测试。"""

    @pytest.mark.asyncio
    async def test_empty_workspace(self, mock_ctx: MagicMock, tmp_path: Path):
        """无 repo_url 时创建空工作区。"""
        ctx = MagicMock()
        ctx.session_id = "init-test"
        s = ProgrammingSkill(ctx)

        from sao_skill_programming import skill as skill_mod
        original = skill_mod._WORKSPACES_ROOT
        skill_mod._WORKSPACES_ROOT = tmp_path
        try:
            result = await s._handle_init({"repo_url": ""}, mock_ctx)
            assert "空工作区已创建" in result
            assert s._workspace is not None
            assert s._workspace.exists()
        finally:
            skill_mod._WORKSPACES_ROOT = original


# ── run 测试 ─────────────────────────────────────────


class TestRun:
    """run tool 测试。"""

    @pytest.mark.asyncio
    async def test_empty_command(self, skill: ProgrammingSkill, mock_ctx: MagicMock):
        """空命令应返回警告。"""
        result = await skill._handle_run({"command": ""}, mock_ctx)
        assert "请提供" in result

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self, skill: ProgrammingSkill, mock_ctx: MagicMock):
        """危险命令应被拦截。"""
        result = await skill._handle_run({"command": "rm -rf /"}, mock_ctx)
        assert "安全限制" in result

    @pytest.mark.asyncio
    async def test_echo_command(self, skill: ProgrammingSkill, mock_ctx: MagicMock):
        """简单 echo 命令应成功执行。"""
        result = await skill._handle_run({"command": "echo hello"}, mock_ctx)
        assert "成功" in result
        assert "hello" in result
