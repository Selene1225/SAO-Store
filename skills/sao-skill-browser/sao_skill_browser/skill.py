"""SAO Browser Skill — 基于 Playwright 的浏览器自动化.

通过 persistent context 保持登录状态，支持导航、读取页面、截图、点击交互。
浏览器 profile 存储在 ~/.sao/browser-data/，关闭后再次打开仍保留 cookies。

支持的浏览器（通过环境变量 SAO_BROWSER_CHANNEL 配置）:
  - msedge   — Microsoft Edge（默认）
  - chrome   — Google Chrome
  - chromium — Playwright 内置 Chromium
  - firefox  — Mozilla Firefox
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
except ImportError:  # pragma: no cover
    async_playwright = None  # type: ignore[assignment,misc]
    Page = Any  # type: ignore[assignment,misc]
    BrowserContext = Any  # type: ignore[assignment,misc]

try:
    from sao.skills import BaseSkill
except ImportError:  # pragma: no cover
    class BaseSkill:  # type: ignore[no-redef]
        """Minimal stub for testing without SAO SDK."""
        def __init__(self, **kwargs: Any) -> None:
            pass


# ─────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────

_USER_DATA_DIR = Path.home() / ".sao" / "browser-data"
_SCREENSHOT_DIR = Path.home() / ".sao" / "screenshots"
_MAX_CONTENT_LEN = 8000
_DEFAULT_TIMEOUT = 30_000  # 30s
_NAVIGATE_TIMEOUT = 60_000  # 60s

# 支持的浏览器 channel
_SUPPORTED_CHANNELS = {"msedge", "chrome", "chromium", "firefox"}
_DEFAULT_CHANNEL = "msedge"


class BrowserSkill(BaseSkill):
    """浏览器自动化技能 — 基于 Playwright persistent context."""

    name = "browser"
    description = "浏览器自动化：导航、读取页面、截图、点击交互"

    def __init__(self, **kwargs: Any) -> None:
        self._playwright_instance: Any = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # 浏览器选择：优先 kwargs > 环境变量 > 默认 msedge
        channel = (
            kwargs.get("browser_channel")
            or os.environ.get("SAO_BROWSER_CHANNEL")
            or _DEFAULT_CHANNEL
        ).lower().strip()
        if channel not in _SUPPORTED_CHANNELS:
            channel = _DEFAULT_CHANNEL
        self._channel: str = channel

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
            "navigate": self._handle_navigate,
            "get_content": self._handle_get_content,
            "screenshot": self._handle_screenshot,
            "click": self._handle_click,
            "fill": self._handle_fill,
            "close": self._handle_close,
        }.get(tool)
        if handler is None:
            return f"⚠️ 未知工具: {tool}，可用: navigate / get_content / screenshot / click / fill / close"
        return await handler(args)

    # ------------------------------------------------------------------
    # navigate — 导航到 URL
    # ------------------------------------------------------------------

    async def _handle_navigate(self, args: dict[str, Any]) -> str:
        url = (args.get("url") or "").strip()
        if not url:
            return "⚠️ 缺少参数 `url`"

        # 基本 URL 格式校验
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "⚠️ 仅支持 http/https 协议"

        wait_sec = int(args.get("wait") or 0)

        try:
            page = await self._ensure_page()
            await page.goto(url, timeout=_NAVIGATE_TIMEOUT, wait_until="domcontentloaded")

            if wait_sec > 0:
                await asyncio.sleep(min(wait_sec, 30))  # 最多额外等 30s

            title = await page.title()
            current_url = page.url
            return f"✅ 已导航到: {current_url}\n📄 标题: {title}"
        except Exception as e:
            return f"❌ 导航失败: {e}"

    # ------------------------------------------------------------------
    # get_content — 获取页面文本内容
    # ------------------------------------------------------------------

    async def _handle_get_content(self, args: dict[str, Any]) -> str:
        page = self._page
        if page is None or page.is_closed():
            return "⚠️ 没有打开的页面，请先使用 navigate"

        selector = (args.get("selector") or "").strip()

        try:
            if selector:
                element = await page.query_selector(selector)
                if element is None:
                    return f"⚠️ 未找到匹配 `{selector}` 的元素"
                text = (await element.inner_text()).strip()
            else:
                text = (await page.inner_text("body")).strip()

            if not text:
                return "ℹ️ 页面内容为空"

            if len(text) > _MAX_CONTENT_LEN:
                text = text[:_MAX_CONTENT_LEN] + f"\n\n... (截断，共 {len(text)} 字符)"

            title = await page.title()
            return f"📄 {title} ({page.url})\n\n{text}"
        except Exception as e:
            return f"❌ 获取内容失败: {e}"

    # ------------------------------------------------------------------
    # screenshot — 截图
    # ------------------------------------------------------------------

    async def _handle_screenshot(self, args: dict[str, Any]) -> str:
        page = self._page
        if page is None or page.is_closed():
            return "⚠️ 没有打开的页面，请先使用 navigate"

        full_page = bool(args.get("full_page", False))

        try:
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = _SCREENSHOT_DIR / f"screenshot_{timestamp}.png"

            await page.screenshot(path=str(filepath), full_page=full_page)

            title = await page.title()
            return (
                f"📸 截图已保存\n"
                f"📄 页面: {title}\n"
                f"📁 路径: {filepath}"
            )
        except Exception as e:
            return f"❌ 截图失败: {e}"

    # ------------------------------------------------------------------
    # click — 点击元素
    # ------------------------------------------------------------------

    async def _handle_click(self, args: dict[str, Any]) -> str:
        page = self._page
        if page is None or page.is_closed():
            return "⚠️ 没有打开的页面，请先使用 navigate"

        selector = (args.get("selector") or "").strip()
        if not selector:
            return "⚠️ 缺少参数 `selector`"

        try:
            await page.click(selector, timeout=_DEFAULT_TIMEOUT)

            # 等待可能触发的导航
            await page.wait_for_load_state("domcontentloaded", timeout=5000)

            title = await page.title()
            return f"✅ 已点击 `{selector}`\n📄 当前页面: {title} ({page.url})"
        except Exception as e:
            return f"❌ 点击失败: {e}"

    # ------------------------------------------------------------------
    # fill — 填写输入框
    # ------------------------------------------------------------------

    async def _handle_fill(self, args: dict[str, Any]) -> str:
        page = self._page
        if page is None or page.is_closed():
            return "⚠️ 没有打开的页面，请先使用 navigate"

        selector = (args.get("selector") or "").strip()
        value = args.get("value", "")

        if not selector:
            return "⚠️ 缺少参数 `selector`"

        try:
            await page.fill(selector, value, timeout=_DEFAULT_TIMEOUT)
            display_val = value[:50] + "..." if len(value) > 50 else value
            return f"✅ 已填入 `{selector}`: {display_val}"
        except Exception as e:
            return f"❌ 填写失败: {e}"

    # ------------------------------------------------------------------
    # close — 关闭浏览器
    # ------------------------------------------------------------------

    async def _handle_close(self, args: dict[str, Any]) -> str:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None

        if self._playwright_instance is not None:
            try:
                await self._playwright_instance.stop()
            except Exception:
                pass
            self._playwright_instance = None

        return "✅ 浏览器已关闭"

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _ensure_page(self) -> Page:
        """确保浏览器和页面已启动，返回 Page 实例."""
        if self._page is not None and not self._page.is_closed():
            return self._page

        if async_playwright is None:
            raise RuntimeError(
                "playwright 未安装，请运行: pip install playwright && playwright install chromium"
            )

        _USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        if self._playwright_instance is None:
            self._playwright_instance = await async_playwright().start()

        if self._context is None:
            channel = self._channel

            if channel == "firefox":
                # Firefox 使用单独的浏览器类型
                self._context = await self._playwright_instance.firefox.launch_persistent_context(
                    user_data_dir=str(_USER_DATA_DIR / "firefox"),
                    headless=False,
                )
            else:
                # Chromium 系：msedge / chrome / chromium
                launch_kwargs: dict[str, Any] = {
                    "user_data_dir": str(_USER_DATA_DIR / channel),
                    "headless": False,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if channel != "chromium":
                    launch_kwargs["channel"] = channel  # msedge / chrome
                self._context = await self._playwright_instance.chromium.launch_persistent_context(
                    **launch_kwargs
                )

        pages = self._context.pages
        if pages:
            self._page = pages[0]
        else:
            self._page = await self._context.new_page()

        return self._page
