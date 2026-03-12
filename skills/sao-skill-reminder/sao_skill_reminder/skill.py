"""Reminder 技能 — 通过飞书多维表格管理提醒/闹钟。

支持操作: set / list / update / cancel
底层存储: 飞书 Bitable（多维表格）
表结构: 提醒内容(text), 提醒时间(datetime), 状态(select), 创建人(person)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    AppTableRecord,
    CreateAppTableRecordRequest,
    ListAppTableRecordRequest,
    UpdateAppTableRecordRequest,
)

from sao.skills import BaseSkill, SkillContext
from sao.utils.config import get_settings
from sao.utils.logger import logger

# 多种时间格式兼容
_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日 %H点%M分",
]


def _parse_datetime(s: str) -> datetime:
    """尝试多种格式解析时间字符串。"""
    s = s.strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {s}，请使用 YYYY-MM-DD HH:mm 格式")


def _ts_to_str(ts: Any) -> str:
    """Bitable timestamp (ms) → 可读时间字符串。"""
    if ts is None:
        return "未知"
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000)
            return dt.strftime("%Y-%m-%d %H:%M")
        return str(ts)
    except Exception:
        return str(ts)


class ReminderSkill(BaseSkill):
    """提醒技能 — 飞书多维表格 CRUD。"""

    name = "reminder"
    description = "管理提醒/闹钟：创建、查看、更新、取消提醒，数据存储在飞书多维表格"

    def __init__(self, ctx: SkillContext) -> None:
        """统一构造函数：所有 Skill 接收 SkillContext，从中获取所需资源。"""
        settings = get_settings()
        self._client = ctx.lark_client
        self._app_token = settings.feishu_bitable_app_token
        self._table_id = settings.feishu_bitable_reminder_table_id

    # ── 技能入口 ───────────────────────────────────────
    # Tools 定义已移至 SKILL.toml，SAO 读取 TOML 注入 Router prompt。
    # Skill 只需实现 execute()。

    async def execute(self, tool: str, args: dict[str, Any], ctx: SkillContext) -> str | None:
        handlers = {
            "set": self._handle_set,
            "list": self._handle_list,
            "update": self._handle_update,
            "cancel": self._handle_cancel,
        }
        handler = handlers.get(tool)
        if not handler:
            return f"⚠️ 未知的 reminder 工具: {tool}"
        return await handler(args, ctx)

    # ── set — 创建提醒 ────────────────────────────────

    async def _handle_set(self, args: dict, ctx: SkillContext) -> str | None:
        content = args.get("content", "").strip()
        remind_time_str = args.get("remind_time", "").strip()

        if not content or not remind_time_str:
            return "⚠️ 请提供提醒内容和时间"

        # 立即应答
        await ctx.channel.send(ctx.chat_id, "⏳ 收到，正在创建提醒…")

        try:
            dt = _parse_datetime(remind_time_str)
            ts_ms = int(dt.timestamp() * 1000)

            fields: dict[str, Any] = {
                "提醒内容": content,
                "提醒时间": ts_ms,
                "状态": "待执行",
            }
            # 尝试设置创建人（人员字段格式）
            if ctx.sender_id:
                fields["创建人"] = [{"id": ctx.sender_id}]

            try:
                await self._create_record(fields)
            except RuntimeError:
                # 如果人员字段格式不对，去掉创建人重试
                fields.pop("创建人", None)
                await self._create_record(fields)

            time_display = dt.strftime("%Y-%m-%d %H:%M")
            return (
                f"✅ 提醒已创建\n"
                f"📝 内容: {content}\n"
                f"⏰ 时间: {time_display}\n"
                f"🔖 状态: 待执行"
            )
        except ValueError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logger.error(f"Reminder set failed: {e}", exc_info=True)
            return f"❌ 创建提醒失败: {e}"

    # ── list — 查看提醒 ───────────────────────────────

    async def _handle_list(self, args: dict, ctx: SkillContext) -> str:
        try:
            records = await self._list_active_records()
            if not records:
                return "📋 当前没有待执行的提醒"

            lines = ["📋 待执行的提醒:"]
            for i, r in enumerate(records, 1):
                fields = r.get("fields", {})
                content = fields.get("提醒内容", "?")
                ts = fields.get("提醒时间")
                time_str = _ts_to_str(ts) if ts else "未知"
                lines.append(f"  {i}. {content} — {time_str}")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Reminder list failed: {e}", exc_info=True)
            return f"❌ 查询提醒失败: {e}"

    # ── update — 更新提醒 ─────────────────────────────

    async def _handle_update(self, args: dict, ctx: SkillContext) -> str:
        keyword = args.get("keyword", "").strip()
        new_content = args.get("new_content", "").strip()
        new_time = args.get("new_time", "").strip()

        if not keyword:
            return "⚠️ 请提供要更新的提醒关键词"
        if not new_content and not new_time:
            return "⚠️ 请提供需要更新的内容或时间"

        try:
            record = await self._find_record_by_keyword(keyword)
            if not record:
                return f'⚠️ 未找到包含"{keyword}"的待执行提醒'

            update_fields: dict[str, Any] = {}
            if new_content:
                update_fields["提醒内容"] = new_content
            if new_time:
                dt = _parse_datetime(new_time)
                update_fields["提醒时间"] = int(dt.timestamp() * 1000)

            record_id = record["record_id"]
            await self._update_record(record_id, update_fields)

            # 获取更新后的展示信息
            final_content = new_content or record.get("fields", {}).get("提醒内容", "")
            final_time = new_time or _ts_to_str(record.get("fields", {}).get("提醒时间"))
            return (
                f"✅ 提醒已更新\n"
                f"📝 内容: {final_content}\n"
                f"⏰ 时间: {final_time}"
            )
        except ValueError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logger.error(f"Reminder update failed: {e}", exc_info=True)
            return f"❌ 更新提醒失败: {e}"

    # ── cancel — 取消提醒 ─────────────────────────────

    async def _handle_cancel(self, args: dict, ctx: SkillContext) -> str:
        keyword = args.get("keyword", "").strip()
        if not keyword:
            return "⚠️ 请提供要取消的提醒关键词"

        try:
            record = await self._find_record_by_keyword(keyword)
            if not record:
                return f'⚠️ 未找到包含"{keyword}"的待执行提醒'

            record_id = record["record_id"]
            await self._update_record(record_id, {"状态": "已取消"})

            content = record.get("fields", {}).get("提醒内容", "")
            return f"✅ 已取消提醒: {content}"
        except Exception as e:
            logger.error(f"Reminder cancel failed: {e}", exc_info=True)
            return f"❌ 取消提醒失败: {e}"

    # ── Bitable CRUD helpers ──────────────────────────

    async def _create_record(self, fields: dict) -> dict:
        """创建 Bitable 记录。"""
        req = (
            CreateAppTableRecordRequest.builder()
            .app_token(self._app_token)
            .table_id(self._table_id)
            .request_body(
                AppTableRecord.builder().fields(fields).build()
            )
            .build()
        )

        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, self._client.bitable.v1.app_table_record.create, req
        )

        if not resp.success():
            raise RuntimeError(
                f"Bitable create failed: code={resp.code} msg={resp.msg}"
            )

        record = resp.data.record
        return {"record_id": record.record_id, "fields": record.fields}

    async def _list_all_records(self, page_size: int = 100) -> list[dict]:
        """列出表中所有记录（自动分页）。"""
        all_records: list[dict] = []
        page_token: str | None = None

        while True:
            builder = (
                ListAppTableRecordRequest.builder()
                .app_token(self._app_token)
                .table_id(self._table_id)
                .page_size(page_size)
            )
            if page_token:
                builder = builder.page_token(page_token)

            req = builder.build()
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None, self._client.bitable.v1.app_table_record.list, req
            )

            if not resp.success():
                raise RuntimeError(
                    f"Bitable list failed: code={resp.code} msg={resp.msg}"
                )

            items = resp.data.items or []
            for r in items:
                all_records.append({"record_id": r.record_id, "fields": r.fields})

            if not resp.data.has_more:
                break
            page_token = resp.data.page_token

        return all_records

    async def _list_active_records(self) -> list[dict]:
        """列出所有"待执行"的提醒记录。"""
        all_records = await self._list_all_records()
        active = []
        for r in all_records:
            status = r.get("fields", {}).get("状态")
            # 状态字段可能是字符串或 dict（取决于 Bitable 单选返回格式）
            if isinstance(status, dict):
                status = status.get("text", "")
            if status == "待执行":
                active.append(r)
        return active

    async def _update_record(self, record_id: str, fields: dict) -> None:
        """更新 Bitable 记录。"""
        req = (
            UpdateAppTableRecordRequest.builder()
            .app_token(self._app_token)
            .table_id(self._table_id)
            .record_id(record_id)
            .request_body(
                AppTableRecord.builder().fields(fields).build()
            )
            .build()
        )

        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, self._client.bitable.v1.app_table_record.update, req
        )

        if not resp.success():
            raise RuntimeError(
                f"Bitable update failed: code={resp.code} msg={resp.msg}"
            )

    async def _find_record_by_keyword(self, keyword: str) -> dict | None:
        """在待执行提醒中模糊匹配关键词。"""
        records = await self._list_active_records()
        for r in records:
            content = r.get("fields", {}).get("提醒内容", "")
            if isinstance(content, list):
                # 富文本字段可能返回 list
                content = "".join(
                    seg.get("text", "") if isinstance(seg, dict) else str(seg)
                    for seg in content
                )
            if keyword.lower() in str(content).lower():
                return r
        return None
