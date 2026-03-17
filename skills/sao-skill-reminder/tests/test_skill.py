"""Reminder Skill 单元测试。

测试覆盖:
- _parse_datetime: 多格式时间解析
- _ts_to_str: Bitable timestamp → 可读字符串
- execute: 路由分发 + 未知 tool
- _handle_set: 参数校验
- _handle_list: 空列表 / 有记录
- _handle_update: 参数校验
- _handle_cancel: 参数校验
- _find_record_by_keyword: 关键词匹配
"""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── mock sao 依赖 ──

_base_skill_mock = MagicMock()
_base_skill_mock.BaseSkill = object
_base_skill_mock.SkillContext = MagicMock

sys.modules.setdefault("sao", MagicMock())
sys.modules.setdefault("sao.skills", _base_skill_mock)
sys.modules.setdefault("sao.utils", MagicMock())
sys.modules.setdefault("sao.utils.config", MagicMock())
sys.modules.setdefault("sao.utils.logger", MagicMock())
sys.modules.setdefault("lark_oapi", MagicMock())
sys.modules.setdefault("lark_oapi.api", MagicMock())
sys.modules.setdefault("lark_oapi.api.bitable", MagicMock())
sys.modules.setdefault("lark_oapi.api.bitable.v1", MagicMock())

from sao_skill_reminder.skill import _parse_datetime, _ts_to_str, ReminderSkill  # noqa: E402


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def skill() -> ReminderSkill:
    """创建 ReminderSkill 实例，mock 外部依赖。"""
    lark_client = MagicMock()

    with patch("sao_skill_reminder.skill.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            feishu_bitable_app_token="test_app_token",
            feishu_bitable_reminder_table_id="test_table_id",
        )
        s = ReminderSkill(lark_client=lark_client)
    return s


@pytest.fixture
def mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.chat_id = "test-chat"
    ctx.sender_id = "user_123"
    ctx.channel = MagicMock()
    ctx.channel.send = AsyncMock()
    return ctx


# ── _parse_datetime 测试 ─────────────────────────────


class TestParseDatetime:
    """多格式时间解析测试。"""

    def test_standard_format(self):
        dt = _parse_datetime("2026-03-10 15:00")
        assert dt == datetime(2026, 3, 10, 15, 0)

    def test_slash_format(self):
        dt = _parse_datetime("2026/03/10 15:00")
        assert dt == datetime(2026, 3, 10, 15, 0)

    def test_with_seconds(self):
        dt = _parse_datetime("2026-03-10 15:00:30")
        assert dt == datetime(2026, 3, 10, 15, 0, 30)

    def test_chinese_format(self):
        dt = _parse_datetime("2026年03月10日 15:00")
        assert dt == datetime(2026, 3, 10, 15, 0)

    def test_chinese_format_dian(self):
        dt = _parse_datetime("2026年03月10日 15点00分")
        assert dt == datetime(2026, 3, 10, 15, 0)

    def test_strips_whitespace(self):
        dt = _parse_datetime("  2026-03-10 15:00  ")
        assert dt == datetime(2026, 3, 10, 15, 0)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="无法解析时间"):
            _parse_datetime("not a date")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="无法解析时间"):
            _parse_datetime("")


# ── _ts_to_str 测试 ──────────────────────────────────


class TestTsToStr:
    """Bitable timestamp 转换测试。"""

    def test_none_returns_unknown(self):
        assert _ts_to_str(None) == "未知"

    def test_valid_ms_timestamp(self):
        # 2026-03-10 15:00 UTC+8
        ts = datetime(2026, 3, 10, 15, 0).timestamp() * 1000
        result = _ts_to_str(ts)
        assert "2026-03-10" in result
        assert "15:00" in result

    def test_float_timestamp(self):
        ts = datetime(2026, 1, 1, 0, 0).timestamp() * 1000
        result = _ts_to_str(float(ts))
        assert "2026-01-01" in result

    def test_string_fallback(self):
        """字符串输入直接返回。"""
        assert _ts_to_str("some string") == "some string"

    def test_zero_timestamp(self):
        """0 应返回有效的时间字符串（1970-01-01）。"""
        result = _ts_to_str(0)
        assert "1970" in result or "1969" in result  # 取决于时区


# ── execute 路由测试 ──────────────────────────────────


class TestExecute:
    """execute() 路由分发测试。"""

    @pytest.mark.asyncio
    async def test_unknown_tool(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute("nonexistent", {}, mock_ctx)
        assert "未知" in result
        assert "nonexistent" in result

    @pytest.mark.asyncio
    async def test_all_tools_routable(self, skill: ReminderSkill):
        """4 个 tool 名都应该有对应 handler。"""
        tools = ["set", "list", "update", "cancel"]
        for t in tools:
            handler = getattr(skill, f"_handle_{t}", None)
            assert handler is not None, f"tool '{t}' 没有 handler"


# ── _handle_set 参数校验 ─────────────────────────────


class TestHandleSet:
    """set tool 参数校验测试。"""

    @pytest.mark.asyncio
    async def test_missing_content(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute("set", {"remind_time": "2026-03-10 15:00"}, mock_ctx)
        assert "请提供" in result

    @pytest.mark.asyncio
    async def test_missing_time(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute("set", {"content": "开会"}, mock_ctx)
        assert "请提供" in result

    @pytest.mark.asyncio
    async def test_both_empty(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute("set", {}, mock_ctx)
        assert "请提供" in result

    @pytest.mark.asyncio
    async def test_invalid_time_format(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute(
            "set",
            {"content": "测试", "remind_time": "not a date"},
            mock_ctx,
        )
        assert "无法解析" in result

    @pytest.mark.asyncio
    async def test_successful_set(self, skill: ReminderSkill, mock_ctx: MagicMock):
        """成功创建提醒。"""
        skill._create_record = AsyncMock(return_value={"record_id": "r1", "fields": {}})
        result = await skill.execute(
            "set",
            {"content": "开会", "remind_time": "2026-03-10 15:00"},
            mock_ctx,
        )
        assert "提醒已创建" in result
        assert "开会" in result
        assert "15:00" in result


# ── _handle_list 测试 ────────────────────────────────


class TestHandleList:
    """list tool 测试。"""

    @pytest.mark.asyncio
    async def test_empty_list(self, skill: ReminderSkill, mock_ctx: MagicMock):
        skill._list_active_records = AsyncMock(return_value=[])
        result = await skill.execute("list", {}, mock_ctx)
        assert "没有待执行" in result

    @pytest.mark.asyncio
    async def test_with_records(self, skill: ReminderSkill, mock_ctx: MagicMock):
        ts = datetime(2026, 3, 10, 15, 0).timestamp() * 1000
        skill._list_active_records = AsyncMock(
            return_value=[
                {"record_id": "r1", "fields": {"提醒内容": "开会", "提醒时间": ts}},
                {"record_id": "r2", "fields": {"提醒内容": "买菜", "提醒时间": ts}},
            ]
        )
        result = await skill.execute("list", {}, mock_ctx)
        assert "开会" in result
        assert "买菜" in result
        assert "1." in result
        assert "2." in result


# ── _handle_update 参数校验 ──────────────────────────


class TestHandleUpdate:
    """update tool 测试。"""

    @pytest.mark.asyncio
    async def test_missing_keyword(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute("update", {"new_content": "新内容"}, mock_ctx)
        assert "关键词" in result

    @pytest.mark.asyncio
    async def test_no_changes(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute("update", {"keyword": "开会"}, mock_ctx)
        assert "内容或时间" in result

    @pytest.mark.asyncio
    async def test_not_found(self, skill: ReminderSkill, mock_ctx: MagicMock):
        skill._find_record_by_keyword = AsyncMock(return_value=None)
        result = await skill.execute(
            "update",
            {"keyword": "不存在", "new_content": "新"},
            mock_ctx,
        )
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_successful_update(self, skill: ReminderSkill, mock_ctx: MagicMock):
        skill._find_record_by_keyword = AsyncMock(
            return_value={
                "record_id": "r1",
                "fields": {"提醒内容": "开会", "提醒时间": 1741593600000},
            }
        )
        skill._update_record = AsyncMock()
        result = await skill.execute(
            "update",
            {"keyword": "开会", "new_content": "改为下午开会"},
            mock_ctx,
        )
        assert "已更新" in result
        assert "改为下午开会" in result


# ── _handle_cancel 测试 ──────────────────────────────


class TestHandleCancel:
    """cancel tool 测试。"""

    @pytest.mark.asyncio
    async def test_missing_keyword(self, skill: ReminderSkill, mock_ctx: MagicMock):
        result = await skill.execute("cancel", {}, mock_ctx)
        assert "关键词" in result

    @pytest.mark.asyncio
    async def test_not_found(self, skill: ReminderSkill, mock_ctx: MagicMock):
        skill._find_record_by_keyword = AsyncMock(return_value=None)
        result = await skill.execute("cancel", {"keyword": "不存在"}, mock_ctx)
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_successful_cancel(self, skill: ReminderSkill, mock_ctx: MagicMock):
        skill._find_record_by_keyword = AsyncMock(
            return_value={
                "record_id": "r1",
                "fields": {"提醒内容": "开会"},
            }
        )
        skill._update_record = AsyncMock()
        result = await skill.execute("cancel", {"keyword": "开会"}, mock_ctx)
        assert "已取消" in result
        assert "开会" in result


# ── _find_record_by_keyword 测试 ─────────────────────


class TestFindRecordByKeyword:
    """关键词匹配测试。"""

    @pytest.mark.asyncio
    async def test_exact_match(self, skill: ReminderSkill):
        skill._list_active_records = AsyncMock(
            return_value=[
                {"record_id": "r1", "fields": {"提醒内容": "下午开会"}},
                {"record_id": "r2", "fields": {"提醒内容": "买菜"}},
            ]
        )
        result = await skill._find_record_by_keyword("开会")
        assert result is not None
        assert result["record_id"] == "r1"

    @pytest.mark.asyncio
    async def test_case_insensitive(self, skill: ReminderSkill):
        skill._list_active_records = AsyncMock(
            return_value=[
                {"record_id": "r1", "fields": {"提醒内容": "Review PR"}},
            ]
        )
        result = await skill._find_record_by_keyword("review")
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_match(self, skill: ReminderSkill):
        skill._list_active_records = AsyncMock(
            return_value=[
                {"record_id": "r1", "fields": {"提醒内容": "开会"}},
            ]
        )
        result = await skill._find_record_by_keyword("不存在的关键词")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_records(self, skill: ReminderSkill):
        skill._list_active_records = AsyncMock(return_value=[])
        result = await skill._find_record_by_keyword("开会")
        assert result is None
