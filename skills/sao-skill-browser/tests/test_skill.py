"""Unit tests for BrowserSkill."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Mock SAO SDK + playwright before importing the skill
# ---------------------------------------------------------------------------
_sao_mod = types.ModuleType("sao")
_skills_mod = types.ModuleType("sao.skills")


class _BaseSkill:
    def __init__(self, **kwargs):
        pass


_skills_mod.BaseSkill = _BaseSkill  # type: ignore[attr-defined]
_sao_mod.skills = _skills_mod  # type: ignore[attr-defined]

sys.modules.setdefault("sao", _sao_mod)
sys.modules.setdefault("sao.skills", _skills_mod)

# Mock playwright modules
_pw_mock = MagicMock()
_pw_async_mock = MagicMock()
_pw_mock.async_api = _pw_async_mock
sys.modules.setdefault("playwright", _pw_mock)
sys.modules.setdefault("playwright.async_api", _pw_async_mock)

from sao_skill_browser.skill import BrowserSkill  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================


@pytest.fixture
def skill():
    s = BrowserSkill()
    return s


@pytest.fixture
def mock_page():
    """Create a mock Page object.

    Playwright's Page has both sync methods (is_closed, url) and async methods
    (goto, title, inner_text, etc). We use MagicMock as the base so sync
    methods return plain values, and explicitly set async methods to AsyncMock.
    """
    page = MagicMock()
    page.is_closed.return_value = False
    page.url = "https://example.com"
    # Async methods
    page.title = AsyncMock(return_value="Test Page")
    page.goto = AsyncMock()
    page.inner_text = AsyncMock(return_value="Hello World")
    page.query_selector = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.screenshot = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    return page


@pytest.fixture
def skill_with_page(skill, mock_page):
    """BrowserSkill with an active mock page."""
    skill._page = mock_page
    skill._context = MagicMock()
    return skill


# ===========================================================================
# Test: execute routing
# ===========================================================================


class TestExecuteRouting:
    async def test_unknown_tool(self, skill: BrowserSkill):
        result = await skill.execute("unknown_tool", {})
        assert "⚠️" in result
        assert "未知工具" in result

    async def test_routes_to_navigate(self, skill_with_page, mock_page):
        result = await skill_with_page.execute("navigate", {"url": "https://example.com"})
        assert "✅" in result or "❌" in result

    async def test_routes_to_get_content(self, skill_with_page):
        result = await skill_with_page.execute("get_content", {})
        assert "📄" in result or "⚠️" in result

    async def test_routes_to_close(self, skill):
        result = await skill.execute("close", {})
        assert "✅" in result


# ===========================================================================
# Test: navigate
# ===========================================================================


class TestNavigate:
    async def test_missing_url(self, skill: BrowserSkill):
        result = await skill.execute("navigate", {})
        assert "⚠️" in result
        assert "url" in result

    async def test_empty_url(self, skill: BrowserSkill):
        result = await skill.execute("navigate", {"url": ""})
        assert "⚠️" in result

    async def test_invalid_scheme(self, skill: BrowserSkill):
        result = await skill.execute("navigate", {"url": "ftp://example.com"})
        assert "⚠️" in result
        assert "http" in result

    async def test_javascript_scheme_blocked(self, skill: BrowserSkill):
        result = await skill.execute("navigate", {"url": "javascript:alert(1)"})
        assert "⚠️" in result

    async def test_successful_navigate(self, skill_with_page, mock_page):
        mock_page.title = AsyncMock(return_value="Example Page")
        mock_page.url = "https://example.com"
        result = await skill_with_page.execute("navigate", {"url": "https://example.com"})
        assert "✅" in result
        assert "Example Page" in result

    async def test_navigate_with_wait(self, skill_with_page, mock_page):
        mock_page.title = AsyncMock(return_value="Loaded")
        result = await skill_with_page.execute(
            "navigate", {"url": "https://example.com", "wait": 1}
        )
        assert "✅" in result

    async def test_navigate_caps_wait_at_30s(self, skill_with_page, mock_page):
        """wait 参数最多 30 秒。"""
        mock_page.title = AsyncMock(return_value="Loaded")
        with patch("sao_skill_browser.skill.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await skill_with_page.execute(
                "navigate", {"url": "https://example.com", "wait": 999}
            )
            sleep_mock.assert_called_once_with(30)

    async def test_navigate_failure(self, skill_with_page, mock_page):
        mock_page.goto = AsyncMock(side_effect=Exception("Timeout"))
        result = await skill_with_page.execute("navigate", {"url": "https://example.com"})
        assert "❌" in result
        assert "Timeout" in result


# ===========================================================================
# Test: get_content
# ===========================================================================


class TestGetContent:
    async def test_no_page_open(self, skill: BrowserSkill):
        result = await skill.execute("get_content", {})
        assert "⚠️" in result
        assert "navigate" in result

    async def test_closed_page(self, skill: BrowserSkill):
        page = MagicMock()
        page.is_closed.return_value = True
        skill._page = page
        result = await skill.execute("get_content", {})
        assert "⚠️" in result

    async def test_full_page_content(self, skill_with_page, mock_page):
        mock_page.inner_text = AsyncMock(return_value="Page text content here")
        result = await skill_with_page.execute("get_content", {})
        assert "📄" in result
        assert "Page text content here" in result

    async def test_with_selector(self, skill_with_page, mock_page):
        element = AsyncMock()
        element.inner_text = AsyncMock(return_value="Selected text")
        mock_page.query_selector = AsyncMock(return_value=element)
        result = await skill_with_page.execute("get_content", {"selector": ".main"})
        assert "Selected text" in result

    async def test_selector_not_found(self, skill_with_page, mock_page):
        mock_page.query_selector = AsyncMock(return_value=None)
        result = await skill_with_page.execute("get_content", {"selector": ".nonexistent"})
        assert "⚠️" in result
        assert "未找到" in result

    async def test_empty_content(self, skill_with_page, mock_page):
        mock_page.inner_text = AsyncMock(return_value="   ")
        result = await skill_with_page.execute("get_content", {})
        assert "为空" in result

    async def test_content_truncation(self, skill_with_page, mock_page):
        long_text = "x" * 10000
        mock_page.inner_text = AsyncMock(return_value=long_text)
        result = await skill_with_page.execute("get_content", {})
        assert "截断" in result
        assert "10000" in result

    async def test_content_failure(self, skill_with_page, mock_page):
        mock_page.inner_text = AsyncMock(side_effect=Exception("DOM error"))
        result = await skill_with_page.execute("get_content", {})
        assert "❌" in result


# ===========================================================================
# Test: screenshot
# ===========================================================================


class TestScreenshot:
    async def test_no_page_open(self, skill: BrowserSkill):
        result = await skill.execute("screenshot", {})
        assert "⚠️" in result

    async def test_successful_screenshot(self, skill_with_page, mock_page, tmp_path):
        with patch("sao_skill_browser.skill._SCREENSHOT_DIR", tmp_path):
            result = await skill_with_page.execute("screenshot", {})
            assert "📸" in result
            assert "截图已保存" in result
            mock_page.screenshot.assert_called_once()

    async def test_full_page_screenshot(self, skill_with_page, mock_page, tmp_path):
        with patch("sao_skill_browser.skill._SCREENSHOT_DIR", tmp_path):
            await skill_with_page.execute("screenshot", {"full_page": True})
            call_kwargs = mock_page.screenshot.call_args[1]
            assert call_kwargs["full_page"] is True

    async def test_screenshot_failure(self, skill_with_page, mock_page):
        mock_page.screenshot = AsyncMock(side_effect=Exception("Render error"))
        result = await skill_with_page.execute("screenshot", {})
        assert "❌" in result


# ===========================================================================
# Test: click
# ===========================================================================


class TestClick:
    async def test_no_page_open(self, skill: BrowserSkill):
        result = await skill.execute("click", {"selector": ".btn"})
        assert "⚠️" in result

    async def test_missing_selector(self, skill_with_page):
        result = await skill_with_page.execute("click", {})
        assert "⚠️" in result
        assert "selector" in result

    async def test_empty_selector(self, skill_with_page):
        result = await skill_with_page.execute("click", {"selector": ""})
        assert "⚠️" in result

    async def test_successful_click(self, skill_with_page, mock_page):
        result = await skill_with_page.execute("click", {"selector": ".submit-btn"})
        assert "✅" in result
        assert "已点击" in result
        mock_page.click.assert_called_once()

    async def test_click_failure(self, skill_with_page, mock_page):
        mock_page.click = AsyncMock(side_effect=Exception("Element not visible"))
        result = await skill_with_page.execute("click", {"selector": ".hidden"})
        assert "❌" in result
        assert "Element not visible" in result


# ===========================================================================
# Test: fill
# ===========================================================================


class TestFill:
    async def test_no_page_open(self, skill: BrowserSkill):
        result = await skill.execute("fill", {"selector": "input", "value": "text"})
        assert "⚠️" in result

    async def test_missing_selector(self, skill_with_page):
        result = await skill_with_page.execute("fill", {"value": "text"})
        assert "⚠️" in result
        assert "selector" in result

    async def test_successful_fill(self, skill_with_page, mock_page):
        result = await skill_with_page.execute(
            "fill", {"selector": "#search", "value": "hello"}
        )
        assert "✅" in result
        assert "已填入" in result
        mock_page.fill.assert_called_once_with("#search", "hello", timeout=30000)

    async def test_fill_long_value_truncated_in_display(self, skill_with_page, mock_page):
        long_val = "x" * 100
        result = await skill_with_page.execute(
            "fill", {"selector": "input", "value": long_val}
        )
        assert "..." in result

    async def test_fill_failure(self, skill_with_page, mock_page):
        mock_page.fill = AsyncMock(side_effect=Exception("Not an input"))
        result = await skill_with_page.execute(
            "fill", {"selector": "div", "value": "text"}
        )
        assert "❌" in result


# ===========================================================================
# Test: close
# ===========================================================================


class TestClose:
    async def test_close_no_browser(self, skill: BrowserSkill):
        """Close without any browser open should succeed gracefully."""
        result = await skill.execute("close", {})
        assert "✅" in result
        assert "已关闭" in result

    async def test_close_with_browser(self, skill_with_page):
        context = skill_with_page._context
        result = await skill_with_page.execute("close", {})
        assert "✅" in result
        assert skill_with_page._page is None
        assert skill_with_page._context is None

    async def test_close_handles_errors(self, skill: BrowserSkill):
        """Close should not raise even if context.close() fails."""
        skill._context = MagicMock()
        skill._context.close = AsyncMock(side_effect=Exception("Already closed"))
        skill._playwright_instance = MagicMock()
        skill._playwright_instance.stop = AsyncMock()

        result = await skill.execute("close", {})
        assert "✅" in result


# ===========================================================================
# Test: browser channel configuration
# ===========================================================================


class TestBrowserChannel:
    def test_default_channel_is_msedge(self):
        s = BrowserSkill()
        assert s._channel == "msedge"

    def test_kwargs_override(self):
        s = BrowserSkill(browser_channel="chrome")
        assert s._channel == "chrome"

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("SAO_BROWSER_CHANNEL", "firefox")
        s = BrowserSkill()
        assert s._channel == "firefox"

    def test_kwargs_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("SAO_BROWSER_CHANNEL", "firefox")
        s = BrowserSkill(browser_channel="chrome")
        assert s._channel == "chrome"

    def test_invalid_channel_falls_back_to_default(self):
        s = BrowserSkill(browser_channel="safari")
        assert s._channel == "msedge"

    def test_channel_case_insensitive(self):
        s = BrowserSkill(browser_channel="CHROME")
        assert s._channel == "chrome"

    def test_chromium_channel(self):
        s = BrowserSkill(browser_channel="chromium")
        assert s._channel == "chromium"
