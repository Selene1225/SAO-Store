"""Unit tests for DiceSkill."""

from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Mock SAO SDK before importing the skill
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

from sao_skill_dice.skill import DiceSkill, _DICE_RE  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

@pytest.fixture
def skill():
    return DiceSkill()


# ===========================================================================
# Test: execute routing
# ===========================================================================

class TestExecuteRouting:
    async def test_unknown_tool(self, skill: DiceSkill):
        result = await skill.execute("unknown_tool", {})
        assert "⚠️" in result
        assert "未知工具" in result

    async def test_routes_to_roll(self, skill: DiceSkill):
        result = await skill.execute("roll", {"notation": "1d6"})
        assert "🎲" in result

    async def test_routes_to_flip(self, skill: DiceSkill):
        result = await skill.execute("flip", {})
        assert "🪙" in result

    async def test_routes_to_pick(self, skill: DiceSkill):
        result = await skill.execute("pick", {"items": "A,B,C"})
        assert "🎯" in result


# ===========================================================================
# Test: roll
# ===========================================================================

class TestRoll:
    async def test_default_1d6(self, skill: DiceSkill):
        result = await skill.execute("roll", {})
        assert "🎲" in result
        assert "1d6" in result

    async def test_valid_notation_2d20(self, skill: DiceSkill):
        result = await skill.execute("roll", {"notation": "2d20"})
        assert "🎲" in result
        assert "2d20" in result

    async def test_notation_with_modifier(self, skill: DiceSkill):
        with patch("sao_skill_dice.skill.random") as mock_random:
            mock_random.randint.return_value = 3
            result = await skill.execute("roll", {"notation": "2d6+5"})
            assert "**11**" in result  # 3 + 3 + 5

    async def test_notation_with_negative_modifier(self, skill: DiceSkill):
        with patch("sao_skill_dice.skill.random") as mock_random:
            mock_random.randint.return_value = 4
            result = await skill.execute("roll", {"notation": "1d6-2"})
            assert "**2**" in result  # 4 - 2

    async def test_invalid_notation(self, skill: DiceSkill):
        result = await skill.execute("roll", {"notation": "abc"})
        assert "⚠️" in result
        assert "无效" in result

    async def test_zero_dice(self, skill: DiceSkill):
        result = await skill.execute("roll", {"notation": "0d6"})
        assert "⚠️" in result

    async def test_too_many_dice(self, skill: DiceSkill):
        result = await skill.execute("roll", {"notation": "101d6"})
        assert "⚠️" in result
        assert "1~100" in result

    async def test_one_face(self, skill: DiceSkill):
        result = await skill.execute("roll", {"notation": "1d1"})
        assert "⚠️" in result
        assert "面数" in result

    async def test_too_many_faces(self, skill: DiceSkill):
        result = await skill.execute("roll", {"notation": "1d1001"})
        assert "⚠️" in result

    async def test_dice_regex_matches(self):
        assert _DICE_RE.match("1d6")
        assert _DICE_RE.match("2D20")
        assert _DICE_RE.match("3d8+5")
        assert _DICE_RE.match("1d20-3")
        assert not _DICE_RE.match("d6")
        assert not _DICE_RE.match("abc")


# ===========================================================================
# Test: flip
# ===========================================================================

class TestFlip:
    async def test_single_flip(self, skill: DiceSkill):
        result = await skill.execute("flip", {})
        assert "🪙" in result
        assert ("正面" in result or "反面" in result)

    async def test_multiple_flips(self, skill: DiceSkill):
        result = await skill.execute("flip", {"count": 5})
        assert "🪙" in result
        assert "抛 5 次" in result
        assert "正面" in result  # summary always mentions counts

    async def test_flip_zero(self, skill: DiceSkill):
        result = await skill.execute("flip", {"count": 0})
        assert "⚠️" in result

    async def test_flip_too_many(self, skill: DiceSkill):
        result = await skill.execute("flip", {"count": 101})
        assert "⚠️" in result

    async def test_flip_deterministic(self, skill: DiceSkill):
        with patch("sao_skill_dice.skill.random") as mock_random:
            mock_random.choice.return_value = "正面"
            result = await skill.execute("flip", {})
            assert "**正面**" in result


# ===========================================================================
# Test: pick
# ===========================================================================

class TestPick:
    async def test_pick_one(self, skill: DiceSkill):
        result = await skill.execute("pick", {"items": "A,B,C"})
        assert "🎯" in result
        # picked item should be one of the options
        assert any(x in result for x in ["A", "B", "C"])

    async def test_pick_multiple(self, skill: DiceSkill):
        result = await skill.execute("pick", {"items": "A,B,C,D", "count": 2})
        assert "🎯" in result
        assert "随机抽选 2 个" in result

    async def test_pick_missing_items(self, skill: DiceSkill):
        result = await skill.execute("pick", {})
        assert "⚠️" in result
        assert "items" in result

    async def test_pick_empty_items(self, skill: DiceSkill):
        result = await skill.execute("pick", {"items": ""})
        assert "⚠️" in result

    async def test_pick_single_item(self, skill: DiceSkill):
        result = await skill.execute("pick", {"items": "只有一个"})
        assert "⚠️" in result
        assert "至少需要 2 个" in result

    async def test_pick_count_exceeds_items(self, skill: DiceSkill):
        result = await skill.execute("pick", {"items": "A,B", "count": 3})
        assert "⚠️" in result
        assert "不能超过" in result

    async def test_pick_zero_count(self, skill: DiceSkill):
        result = await skill.execute("pick", {"items": "A,B,C", "count": 0})
        assert "⚠️" in result

    async def test_pick_strips_whitespace(self, skill: DiceSkill):
        with patch("sao_skill_dice.skill.random") as mock_random:
            mock_random.sample.return_value = ["火锅"]
            result = await skill.execute("pick", {"items": " 火锅 , 烧烤 , 麻辣烫 "})
            assert "**火锅**" in result

    async def test_pick_deterministic(self, skill: DiceSkill):
        with patch("sao_skill_dice.skill.random") as mock_random:
            mock_random.sample.return_value = ["烧烤"]
            result = await skill.execute("pick", {"items": "火锅,烧烤,麻辣烫"})
            assert "**烧烤**" in result
