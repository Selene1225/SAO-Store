"""Unit tests for IcmSkill."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock SAO SDK + playwright + aiohttp before importing
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

# Mock playwright
_pw_mock = MagicMock()
_pw_async_mock = MagicMock()
_pw_mock.async_api = _pw_async_mock
sys.modules.setdefault("playwright", _pw_mock)
sys.modules.setdefault("playwright.async_api", _pw_async_mock)

# Mock aiohttp
_aiohttp_mock = MagicMock()
sys.modules.setdefault("aiohttp", _aiohttp_mock)

from sao_skill_icm.skill import IcmSkill, _format_time, _SEVERITY_LABELS  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================


@pytest.fixture
def skill():
    return IcmSkill(team_id="131477")


def _make_incident(
    inc_id: int = 12345678,
    severity: int = 3,
    state: str = "Active",
    title: str = "Test incident",
    team_name: str = "Content Processing DRI",
    contact: str = "testuser",
    hits: int = 1,
    customer_impact: bool = False,
    noise: bool = False,
) -> dict:
    return {
        "Id": inc_id,
        "CreatedDate": "2026-03-19T08:30:00Z",
        "Severity": severity,
        "State": state,
        "Title": title,
        "OwningTenantName": "News Partner Hub",
        "OwningTeamName": team_name,
        "ContactAlias": contact,
        "HitCount": hits,
        "ChildCount": 0,
        "ParentId": None,
        "IsCustomerImpacting": customer_impact,
        "IsNoise": noise,
        "IsOutage": False,
        "ImpactStartTime": "2026-03-19T08:00:00Z",
        "AcknowledgeBy": "2026-03-19T09:30:00Z",
    }


# ===========================================================================
# Test: execute routing
# ===========================================================================


class TestExecuteRouting:
    async def test_unknown_tool(self, skill: IcmSkill):
        result = await skill.execute("unknown_tool", {})
        assert "⚠️" in result
        assert "未知工具" in result

    async def test_routes_to_query(self, skill: IcmSkill):
        with patch.object(skill, "_handle_query", new_callable=AsyncMock, return_value="ok"):
            result = await skill.execute("query", {})
            assert result == "ok"

    async def test_routes_to_get_incident(self, skill: IcmSkill):
        with patch.object(skill, "_handle_get_incident", new_callable=AsyncMock, return_value="ok"):
            result = await skill.execute("get_incident", {"incident_id": 123})
            assert result == "ok"

    async def test_routes_to_summary(self, skill: IcmSkill):
        with patch.object(skill, "_handle_summary", new_callable=AsyncMock, return_value="ok"):
            result = await skill.execute("summary", {})
            assert result == "ok"


# ===========================================================================
# Test: __init__ config
# ===========================================================================


class TestInit:
    def test_default_channel(self):
        s = IcmSkill()
        assert s._channel == "msedge"

    def test_custom_channel(self):
        s = IcmSkill(browser_channel="chrome")
        assert s._channel == "chrome"

    def test_invalid_channel_falls_back(self):
        s = IcmSkill(browser_channel="safari")
        assert s._channel == "msedge"

    def test_team_id_from_kwargs(self):
        s = IcmSkill(team_id="131477")
        assert s._default_team_id == 131477

    def test_team_id_from_env(self, monkeypatch):
        monkeypatch.setenv("SAO_ICM_TEAM_ID", "99999")
        s = IcmSkill()
        assert s._default_team_id == 99999

    def test_kwargs_team_id_over_env(self, monkeypatch):
        monkeypatch.setenv("SAO_ICM_TEAM_ID", "99999")
        s = IcmSkill(team_id="131477")
        assert s._default_team_id == 131477

    def test_invalid_team_id_ignored(self):
        s = IcmSkill(team_id="not_a_number")
        assert s._default_team_id is None

    def test_no_team_id(self):
        s = IcmSkill()
        assert s._default_team_id is None


# ===========================================================================
# Test: query
# ===========================================================================


class TestQuery:
    async def test_missing_team_id(self):
        s = IcmSkill()  # no team_id
        result = await s._handle_query({})
        assert "⚠️" in result
        assert "team_id" in result

    async def test_no_incidents(self, skill: IcmSkill):
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="fake_token"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={"value": []}),
        ):
            result = await skill._handle_query({})
            assert "没有新 incidents" in result

    async def test_with_incidents(self, skill: IcmSkill):
        incidents = [
            _make_incident(inc_id=1001, severity=2, title="Sev2 incident"),
            _make_incident(inc_id=1002, severity=3, title="Sev3 incident"),
        ]
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="fake_token"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={"value": incidents}),
        ):
            result = await skill._handle_query({})
            assert "1001" in result
            assert "1002" in result
            assert "Sev2" in result
            assert "共 2 条" in result

    async def test_customer_impact_flag(self, skill: IcmSkill):
        incidents = [_make_incident(customer_impact=True)]
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="fake_token"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={"value": incidents}),
        ):
            result = await skill._handle_query({})
            assert "客户影响" in result

    async def test_state_filter_passed_to_url(self, skill: IcmSkill):
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="t"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={"value": []}) as mock_get,
        ):
            await skill._handle_query({"state": "Active"})
            url_arg = mock_get.call_args[0][0]
            assert "Active" in url_arg

    async def test_severity_filter_passed_to_url(self, skill: IcmSkill):
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="t"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={"value": []}) as mock_get,
        ):
            await skill._handle_query({"severity": 1})
            url_arg = mock_get.call_args[0][0]
            assert "Severity" in url_arg

    async def test_auth_expired_propagates(self, skill: IcmSkill):
        with patch.object(
            skill, "_get_token", new_callable=AsyncMock,
            side_effect=PermissionError("登录态已过期"),
        ):
            with pytest.raises(PermissionError, match="过期"):
                await skill._handle_query({})


# ===========================================================================
# Test: get_incident
# ===========================================================================


class TestGetIncident:
    async def test_missing_incident_id(self, skill: IcmSkill):
        result = await skill._handle_get_incident({})
        assert "⚠️" in result
        assert "incident_id" in result

    async def test_incident_found(self, skill: IcmSkill):
        inc = _make_incident(inc_id=99999, severity=1, title="Major outage")
        inc["RootCause"] = {"Title": "Bad deploy", "Description": "Rolled back"}
        inc["CustomFields"] = [{"Name": "Impact", "Value": "High"}]
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="t"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value=inc),
        ):
            result = await skill._handle_get_incident({"incident_id": 99999})
            assert "99999" in result
            assert "Major outage" in result
            assert "Sev1" in result
            assert "Bad deploy" in result
            assert "Impact" in result

    async def test_incident_not_found(self, skill: IcmSkill):
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="t"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={}),
        ):
            result = await skill._handle_get_incident({"incident_id": 0})
            assert "未找到" in result


# ===========================================================================
# Test: summary
# ===========================================================================


class TestSummary:
    async def test_missing_team_id(self):
        s = IcmSkill()
        result = await s._handle_summary({})
        assert "⚠️" in result

    async def test_no_incidents(self, skill: IcmSkill):
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="t"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={"value": []}),
        ):
            result = await skill._handle_summary({})
            assert "没有 incidents" in result

    async def test_summary_counts(self, skill: IcmSkill):
        incidents = [
            _make_incident(severity=2, state="Active", customer_impact=True),
            _make_incident(severity=2, state="Active"),
            _make_incident(severity=3, state="Mitigated", noise=True),
            _make_incident(severity=4, state="Resolved"),
        ]
        with (
            patch.object(skill, "_get_token", new_callable=AsyncMock, return_value="t"),
            patch.object(skill, "_api_get", new_callable=AsyncMock, return_value={"value": incidents}),
        ):
            result = await skill._handle_summary({})
            assert "共 4 条" in result
            assert "Sev2" in result
            assert "Sev3" in result
            assert "Sev4" in result
            assert "客户影响: 1" in result
            assert "噪音: 1" in result


# ===========================================================================
# Test: _format_time
# ===========================================================================


class TestFormatTime:
    def test_none(self):
        assert _format_time(None) == "—"

    def test_empty_string(self):
        assert _format_time("") == "—"

    def test_valid_utc_time(self):
        result = _format_time("2026-03-19T08:30:00Z")
        assert "03-19" in result
        assert "16:30" in result  # UTC+8

    def test_invalid_string(self):
        result = _format_time("not-a-date")
        assert result == "not-a-date"


# ===========================================================================
# Test: severity labels
# ===========================================================================


class TestSeverityLabels:
    def test_all_levels(self):
        assert "Sev1" in _SEVERITY_LABELS[1]
        assert "Sev2" in _SEVERITY_LABELS[2]
        assert "Sev3" in _SEVERITY_LABELS[3]
        assert "Sev4" in _SEVERITY_LABELS[4]
