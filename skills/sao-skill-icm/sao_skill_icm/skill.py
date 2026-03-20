"""SAO ICM Skill — 查询 Microsoft ICM incidents.

认证流程:
    1. Playwright (Edge persistent context) 复用 SSO 登录态
    2. POST /sso2/token (grant_type=cookie) → Bearer token
    3. 用 token 调 ICM OData API

首次使用需在 Edge 中手动登录 https://portal.microsofticm.com
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover
    async_playwright = None  # type: ignore[assignment,misc]

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore[assignment]

try:
    from sao.skills import BaseSkill
except ImportError:  # pragma: no cover
    class BaseSkill:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            pass


# ─────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────

_BROWSER_DATA_DIR = Path.home() / ".sao" / "browser-data"
_TOKEN_URL = "https://portal.microsofticm.com/sso2/token"
_API_BASE = "https://prod.microsofticm.com/api2/incidentapi"
_AUTH_EXPIRED_MSG = (
    "⚠️ ICM 认证失败：登录态已过期，"
    "请在 Edge 浏览器中重新登录 https://portal.microsofticm.com 后重试"
)

_DEFAULT_SELECT = (
    "Id,CreatedDate,Severity,State,Title,OwningTenantName,"
    "OwningTeamName,ContactAlias,HitCount,ChildCount,"
    "IsCustomerImpacting,IsNoise,IsOutage,ImpactStartTime,"
    "AcknowledgeBy,ParentId"
)

_DETAIL_SELECT = (
    "Id,CreatedDate,Severity,State,Title,OwningTenantName,"
    "OwningTeamName,ContactAlias,HitCount,ChildCount,OwningServiceId,"
    "OwningTeamId,AcknowledgeBy,ParentId,IsCustomerImpacting,"
    "IsNoise,IsOutage,ExternalLinksCount,CustomerName,"
    "ImpactStartTime,MitigateData,ServiceCategoryId"
)

_SEVERITY_LABELS = {1: "Sev1🔴", 2: "Sev2🟠", 3: "Sev3🟡", 4: "Sev4🔵"}

# 支持的浏览器 channel
_SUPPORTED_CHANNELS = {"msedge", "chrome", "chromium"}
_DEFAULT_CHANNEL = "msedge"


class IcmSkill(BaseSkill):
    """ICM 查询技能 — 通过 SSO cookie 获取 token 后调 ICM API."""

    name = "icm"
    description = "查询 ICM incidents：按队列/日期/状态筛选"

    def __init__(self, **kwargs: Any) -> None:
        channel = (
            kwargs.get("browser_channel")
            or os.environ.get("SAO_BROWSER_CHANNEL")
            or _DEFAULT_CHANNEL
        ).lower().strip()
        if channel not in _SUPPORTED_CHANNELS:
            channel = _DEFAULT_CHANNEL
        self._channel: str = channel
        self._default_team_id: int | None = None
        raw = kwargs.get("team_id") or os.environ.get("SAO_ICM_TEAM_ID")
        if raw is not None:
            try:
                self._default_team_id = int(raw)
            except (ValueError, TypeError):
                pass

    # ------------------------------------------------------------------
    # execute 入口
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool: str,
        args: dict[str, Any],
        ctx: Any = None,
    ) -> str:
        handler = {
            "query": self._handle_query,
            "get_incident": self._handle_get_incident,
            "summary": self._handle_summary,
        }.get(tool)
        if handler is None:
            return f"⚠️ 未知工具: {tool}，可用: query / get_incident / summary"
        return await handler(args)

    # ------------------------------------------------------------------
    # query — 查询 incidents
    # ------------------------------------------------------------------

    async def _handle_query(self, args: dict[str, Any]) -> str:
        team_id = args.get("team_id") or self._default_team_id
        if not team_id:
            return "⚠️ 缺少 team_id，请提供或设置环境变量 SAO_ICM_TEAM_ID"

        days = int(args.get("days") or 1)
        state = (args.get("state") or "").strip()
        severity = args.get("severity")
        top = int(args.get("top") or 50)

        # 构建 OData filter
        since = datetime.now(timezone.utc) - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT00:00:00Z")

        filters = [
            f"(OwningTeamId eq {int(team_id)})",
            "ParentId eq null",
            f"CreatedDate ge {since_str}",
        ]
        if state:
            filters.append(f"State eq '{state}'")
        if severity:
            filters.append(f"Severity eq {int(severity)}")

        filter_str = " and ".join(filters)
        url = (
            f"{_API_BASE}/incidents"
            f"?$select={_DEFAULT_SELECT}"
            f"&$filter={quote(filter_str, safe='()')}"
            f"&$orderby=CreatedDate desc"
            f"&$top={top}"
        )

        token = await self._get_token()
        data = await self._api_get(url, token)
        incidents = data.get("value", [])

        if not incidents:
            return f"✅ 最近 {days} 天没有新 incidents"

        lines = [f"📋 最近 {days} 天的 ICM incidents（共 {len(incidents)} 条）：\n"]
        for inc in incidents:
            sev = _SEVERITY_LABELS.get(inc.get("Severity", 0), f"Sev{inc.get('Severity')}")
            state_val = inc.get("State", "?")
            title = inc.get("Title", "(无标题)")
            inc_id = inc.get("Id", "?")
            created = _format_time(inc.get("CreatedDate"))
            contact = inc.get("ContactAlias", "?")
            hits = inc.get("HitCount", 0)

            icm_url = f"https://portal.microsofticm.com/imp/v3/incidents/details/{inc_id}/home"
            line = f"  **{inc_id}** | {sev} | {state_val} | {title}"
            team_name = inc.get("OwningTeamName", "?")
            line += f"\n    📂 {team_name} | 👤 {contact} | 🕐 {created} | 命中 {hits} 次"
            line += f"\n    🔗 {icm_url}"
            if inc.get("IsCustomerImpacting"):
                line += " | ⚠️客户影响"
            lines.append(line)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # get_incident — 查单个 incident
    # ------------------------------------------------------------------

    async def _handle_get_incident(self, args: dict[str, Any]) -> str:
        incident_id = args.get("incident_id")
        if incident_id is None:
            return "⚠️ 缺少参数 `incident_id`"

        url = (
            f"{_API_BASE}/incidents({int(incident_id)})"
            f"?$select={_DETAIL_SELECT}"
            f"&$expand=RootCause,CustomFields"
        )

        token = await self._get_token()
        inc = await self._api_get(url, token)

        if not inc.get("Id"):
            return f"⚠️ 未找到 incident {incident_id}"

        sev = _SEVERITY_LABELS.get(inc.get("Severity", 0), f"Sev{inc.get('Severity')}")
        icm_url = f"https://portal.microsofticm.com/imp/v3/incidents/details/{inc['Id']}/home"
        lines = [
            f"🔍 ICM {inc['Id']} 详情\n",
            f"**链接**: {icm_url}",
            f"**标题**: {inc.get('Title', '?')}",
            f"**严重级别**: {sev}",
            f"**状态**: {inc.get('State', '?')}",
            f"**团队**: {inc.get('OwningTenantName', '?')} / {inc.get('OwningTeamName', '?')}",
            f"**联系人**: {inc.get('ContactAlias', '?')}",
            f"**创建时间**: {_format_time(inc.get('CreatedDate'))}",
            f"**影响开始**: {_format_time(inc.get('ImpactStartTime'))}",
            f"**命中次数**: {inc.get('HitCount', 0)}",
            f"**子 incident**: {inc.get('ChildCount', 0)}",
            f"**客户影响**: {'是' if inc.get('IsCustomerImpacting') else '否'}",
            f"**噪音**: {'是' if inc.get('IsNoise') else '否'}",
            f"**故障**: {'是' if inc.get('IsOutage') else '否'}",
        ]

        # Root cause
        rc = inc.get("RootCause")
        if rc and rc.get("Title"):
            lines.append(f"\n**根因**: {rc['Title']}")
            if rc.get("Description"):
                lines.append(f"  {rc['Description'][:200]}")

        # Custom fields
        cfs = inc.get("CustomFields", [])
        if cfs:
            lines.append("\n**自定义字段**:")
            for cf in cfs[:10]:
                lines.append(f"  - {cf.get('Name', '?')}: {cf.get('Value', '?')}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # summary — 统计摘要
    # ------------------------------------------------------------------

    async def _handle_summary(self, args: dict[str, Any]) -> str:
        team_id = args.get("team_id") or self._default_team_id
        if not team_id:
            return "⚠️ 缺少 team_id，请提供或设置环境变量 SAO_ICM_TEAM_ID"

        days = int(args.get("days") or 1)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT00:00:00Z")

        filter_str = (
            f"(OwningTeamId eq {int(team_id)}) and "
            f"ParentId eq null and "
            f"CreatedDate ge {since_str}"
        )
        url = (
            f"{_API_BASE}/incidents"
            f"?$select=Id,Severity,State,IsCustomerImpacting,IsNoise"
            f"&$filter={quote(filter_str, safe='()')}"
            f"&$top=500"
        )

        token = await self._get_token()
        data = await self._api_get(url, token)
        incidents = data.get("value", [])

        total = len(incidents)
        if total == 0:
            return f"📊 最近 {days} 天没有 incidents"

        # 按 severity 分组
        by_sev: dict[int, int] = {}
        by_state: dict[str, int] = {}
        customer_impact = 0
        noise = 0

        for inc in incidents:
            sev = inc.get("Severity", 0)
            by_sev[sev] = by_sev.get(sev, 0) + 1
            st = inc.get("State", "Unknown")
            by_state[st] = by_state.get(st, 0) + 1
            if inc.get("IsCustomerImpacting"):
                customer_impact += 1
            if inc.get("IsNoise"):
                noise += 1

        lines = [f"📊 最近 {days} 天 ICM 统计（共 {total} 条）\n"]

        lines.append("**按严重级别**:")
        for sev in sorted(by_sev):
            label = _SEVERITY_LABELS.get(sev, f"Sev{sev}")
            lines.append(f"  {label}: {by_sev[sev]} 条")

        lines.append("\n**按状态**:")
        for st, cnt in sorted(by_state.items()):
            lines.append(f"  {st}: {cnt} 条")

        lines.append(f"\n⚠️ 客户影响: {customer_impact} 条")
        lines.append(f"🔇 噪音: {noise} 条")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 认证：通过 Playwright 获取 SSO token
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        """通过 Playwright 复用 Edge SSO cookie 获取 Bearer token."""
        if async_playwright is None:
            raise RuntimeError(
                "playwright 未安装，请运行: pip install playwright && playwright install chromium"
            )

        channel = self._channel
        user_data_dir = str(_BROWSER_DATA_DIR / channel)
        _BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        pw = await async_playwright().start()
        try:
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": user_data_dir,
                "headless": True,  # token 获取不需要显示浏览器
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if channel != "chromium":
                launch_kwargs["channel"] = channel

            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # 在浏览器上下文中 fetch token（自动带 cookie）
                token_data = await page.evaluate("""
                    async () => {
                        const resp = await fetch(
                            "https://portal.microsofticm.com/sso2/token",
                            {
                                method: "POST",
                                headers: {"Content-Type": "application/x-www-form-urlencoded"},
                                body: "grant_type=cookie",
                                credentials: "include"
                            }
                        );
                        if (!resp.ok) {
                            return { error: resp.status };
                        }
                        return await resp.json();
                    }
                """)

                if isinstance(token_data, dict) and "error" in token_data:
                    raise PermissionError(f"HTTP {token_data['error']}")

                access_token = token_data.get("access_token")
                if not access_token:
                    raise PermissionError("响应中无 access_token")

                return access_token
            finally:
                await context.close()
        except PermissionError:
            raise
        except Exception as e:
            raise PermissionError(str(e)) from e
        finally:
            await pw.stop()

    # ------------------------------------------------------------------
    # HTTP API 调用
    # ------------------------------------------------------------------

    async def _api_get(self, url: str, token: str) -> dict:
        """带 Bearer token 的 GET 请求."""
        if aiohttp is None:
            raise RuntimeError("aiohttp 未安装，请运行: pip install aiohttp")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 401:
                        raise PermissionError(_AUTH_EXPIRED_MSG)
                    resp.raise_for_status()
                    return await resp.json()
        except PermissionError:
            raise
        except aiohttp.ClientResponseError as e:
            raise RuntimeError(f"ICM API 错误: HTTP {e.status} {e.message}") from e


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────

def _format_time(ts: str | None) -> str:
    """ISO 时间字符串 → 可读格式 (UTC+8)."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt_local = dt.astimezone(timezone(timedelta(hours=8)))
        return dt_local.strftime("%m-%d %H:%M")
    except (ValueError, AttributeError):
        return str(ts)
