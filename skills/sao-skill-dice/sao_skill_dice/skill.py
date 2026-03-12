"""SAO Dice Skill — 掷骰子、抛硬币、随机抽选."""

from __future__ import annotations

import random
import re
from typing import Any

# ---------------------------------------------------------------------------
# Mock-safe imports: SAO SDK 在单元测试中可能不存在
# ---------------------------------------------------------------------------
try:
    from sao.skills import BaseSkill
except ImportError:  # pragma: no cover
    class BaseSkill:  # type: ignore[no-redef]
        """Minimal stub so the module can be imported without sao installed."""
        def __init__(self, ctx: Any = None) -> None:
            self.ctx = ctx


# ---------------------------------------------------------------------------
# Dice notation regex:  NdM  or  NdM+K / NdM-K
# ---------------------------------------------------------------------------
_DICE_RE = re.compile(
    r"^(?P<num>\d+)[dD](?P<faces>\d+)(?P<mod>[+-]\d+)?$",
)

_MAX_DICE = 100
_MAX_FACES = 1000
_MAX_FLIP = 100
_MAX_PICK = 50


class DiceSkill(BaseSkill):
    """轻量级随机工具，用于测试 SAO 技能安装链路."""

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
            "roll": self._handle_roll,
            "flip": self._handle_flip,
            "pick": self._handle_pick,
        }.get(tool)
        if handler is None:
            return f"⚠️ 未知工具: {tool}，可用: roll / flip / pick"
        return await handler(args)

    # ------------------------------------------------------------------
    # roll — 掷骰子
    # ------------------------------------------------------------------
    async def _handle_roll(self, args: dict[str, Any]) -> str:
        notation: str = str(args.get("notation", "1d6")).strip()
        m = _DICE_RE.match(notation)
        if not m:
            return f"⚠️ 无效的骰子表达式: '{notation}'，示例: 1d6, 2d20, 3d8+5"

        num = int(m.group("num"))
        faces = int(m.group("faces"))
        mod = int(m.group("mod")) if m.group("mod") else 0

        if num < 1 or num > _MAX_DICE:
            return f"⚠️ 骰子数量须在 1~{_MAX_DICE} 之间"
        if faces < 2 or faces > _MAX_FACES:
            return f"⚠️ 面数须在 2~{_MAX_FACES} 之间"

        rolls = [random.randint(1, faces) for _ in range(num)]
        total = sum(rolls) + mod

        parts = " + ".join(str(r) for r in rolls)
        mod_str = f" {'+' if mod >= 0 else '-'} {abs(mod)}" if mod else ""
        return f"🎲 {notation} → [{parts}]{mod_str} = **{total}**"

    # ------------------------------------------------------------------
    # flip — 抛硬币
    # ------------------------------------------------------------------
    async def _handle_flip(self, args: dict[str, Any]) -> str:
        count = int(args.get("count", 1))
        if count < 1 or count > _MAX_FLIP:
            return f"⚠️ 次数须在 1~{_MAX_FLIP} 之间"

        results = [random.choice(["正面", "反面"]) for _ in range(count)]
        if count == 1:
            return f"🪙 抛硬币 → **{results[0]}**"

        summary = ", ".join(results)
        heads = results.count("正面")
        tails = count - heads
        return f"🪙 抛 {count} 次 → {summary}\n（正面 {heads} 次，反面 {tails} 次）"

    # ------------------------------------------------------------------
    # pick — 随机抽选
    # ------------------------------------------------------------------
    async def _handle_pick(self, args: dict[str, Any]) -> str:
        raw: str = args.get("items", "")
        if not raw or not raw.strip():
            return "⚠️ 缺少参数 `items`，请提供逗号分隔的选项列表"

        items = [s.strip() for s in raw.split(",") if s.strip()]
        if len(items) < 2:
            return "⚠️ 至少需要 2 个选项才能抽选"
        if len(items) > _MAX_PICK:
            return f"⚠️ 选项数量不能超过 {_MAX_PICK} 个"

        count = int(args.get("count", 1))
        if count < 1:
            return "⚠️ 抽选个数至少为 1"
        if count > len(items):
            return f"⚠️ 抽选个数 ({count}) 不能超过选项总数 ({len(items)})"

        picked = random.sample(items, count)
        if count == 1:
            return f"🎯 随机抽选 → **{picked[0]}**"
        return f"🎯 随机抽选 {count} 个 → **{'、'.join(picked)}**"
