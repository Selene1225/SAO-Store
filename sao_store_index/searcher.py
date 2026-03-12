"""SAO-Store 组件搜索引擎 — 关键词 + 模糊 + 别名匹配."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .indexer import ComponentInfo, StoreIndexer


@dataclass
class SearchResult:
    """搜索结果."""

    name: str
    type: str                   # "skill" or "expert"
    version: str
    description: str
    path: str
    score: int                  # 0-100，越高越相关
    match_reason: str           # 人类可读的匹配原因
    weight: int | None = None
    tools: list[str] = field(default_factory=list)


class StoreSearcher:
    """基于 index.toml 的组件搜索引擎.

    搜索策略（按优先级）:
        1. 名称完全匹配  (100)
        2. 名称包含匹配  (90)
        3. 关键词完全匹配 (80)
        4. 别名完全匹配  (75)
        5. 关键词包含匹配 (60)  — query⊂keyword 或 keyword⊂query
        6. 别名包含匹配  (55)
        7. 描述包含匹配  (40)
        8. 字符重叠模糊  (≤30) — 中文字符级匹配
    """

    def __init__(self, store_path: str | Path) -> None:
        self.store_path = Path(store_path)
        self._components: list[ComponentInfo] = []
        self._loaded = False

    def load(self) -> None:
        """加载索引。优先读 index.toml，不存在则实时扫描."""
        index_path = self.store_path / "index.toml"
        if index_path.exists():
            self._components = self._load_from_index(index_path)
        else:
            indexer = StoreIndexer(self.store_path)
            self._components = indexer.scan()
        self._loaded = True

    def search(
        self,
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[SearchResult]:
        """搜索组件.

        Args:
            query: 搜索关键词（中文/英文均可）
            limit: 最大返回数量
            type_filter: "skill" 或 "expert"，None 不过滤
        """
        if not self._loaded:
            self.load()

        query = query.strip()
        if not query:
            return []

        q = query.lower()
        results: list[SearchResult] = []

        for comp in self._components:
            if type_filter and comp.type != type_filter:
                continue

            score, reason = self._score(q, comp)
            if score > 0:
                results.append(SearchResult(
                    name=comp.name,
                    type=comp.type,
                    version=comp.version,
                    description=comp.description,
                    path=comp.path,
                    score=score,
                    match_reason=reason,
                    weight=comp.weight,
                    tools=comp.tools or [],
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def list_all(self, type_filter: str | None = None) -> list[ComponentInfo]:
        """列出所有组件."""
        if not self._loaded:
            self.load()
        if type_filter:
            return [c for c in self._components if c.type == type_filter]
        return list(self._components)

    # ── 评分逻辑 ──────────────────────────────────────────────

    @staticmethod
    def _score(query: str, comp: ComponentInfo) -> tuple[int, str]:
        """计算查询与组件的匹配分数.

        Returns:
            (score, match_reason) — score=0 表示无匹配
        """
        best = 0
        reason = ""

        # ── 1. 名称完全匹配 (100) ──
        if query == comp.name.lower():
            return 100, f"名称完全匹配: {comp.name}"

        # ── 2. 名称包含匹配 (90) ──
        name_l = comp.name.lower()
        if len(query) >= 2 and (query in name_l or name_l in query):
            best, reason = 90, f"名称包含: {comp.name}"

        # ── 3. 关键词完全匹配 (80) ──
        for kw in comp.keywords:
            if query == kw.lower():
                return 80, f"关键词匹配: {kw}"

        # ── 4. 别名完全匹配 (75) ──
        for alias in comp.aliases:
            if query == alias.lower():
                if 75 > best:
                    best, reason = 75, f"别名匹配: {alias}"

        # ── 5. 关键词包含匹配 (60) ──
        for kw in comp.keywords:
            kw_l = kw.lower()
            if len(kw_l) >= 2 and (kw_l in query or query in kw_l):
                if 60 > best:
                    best, reason = 60, f"关键词部分匹配: {kw}"

        # ── 6. 别名包含匹配 (55) ──
        for alias in comp.aliases:
            alias_l = alias.lower()
            if len(alias_l) >= 2 and (alias_l in query or query in alias_l):
                if 55 > best:
                    best, reason = 55, f"别名部分匹配: {alias}"

        # ── 7. 描述包含匹配 (40) ──
        if len(query) >= 2 and query in comp.description.lower():
            if 40 > best:
                best, reason = 40, "描述匹配"

        # ── 8. 字符重叠模糊匹配 (≤30) ──
        if best == 0 and len(query) >= 2:
            haystack = (
                comp.name.lower() + " "
                + comp.description.lower() + " "
                + " ".join(kw.lower() for kw in comp.keywords) + " "
                + " ".join(a.lower() for a in comp.aliases)
            )
            matched = sum(1 for c in query if c in haystack)
            ratio = matched / len(query)
            if ratio >= 0.6:
                fuzzy = int(30 * ratio)
                if fuzzy > best:
                    best = fuzzy
                    reason = f"模糊匹配 ({ratio:.0%})"

        return best, reason

    # ── 加载 index.toml ──────────────────────────────────────

    @staticmethod
    def _load_from_index(index_path: Path) -> list[ComponentInfo]:
        """从 index.toml 加载组件列表."""
        data = tomllib.loads(index_path.read_text(encoding="utf-8"))
        components: list[ComponentInfo] = []

        for skill in data.get("skills", []):
            components.append(ComponentInfo(
                name=skill.get("name", ""),
                type="skill",
                version=skill.get("version", ""),
                description=skill.get("description", ""),
                keywords=skill.get("keywords", []),
                aliases=skill.get("aliases", []),
                path=skill.get("path", ""),
                weight=skill.get("weight"),
                tools=skill.get("tools", []),
            ))

        for expert in data.get("experts", []):
            components.append(ComponentInfo(
                name=expert.get("name", ""),
                type="expert",
                version=expert.get("version", ""),
                description=expert.get("description", ""),
                keywords=expert.get("keywords", []),
                aliases=expert.get("aliases", []),
                path=expert.get("path", ""),
            ))

        return components
