"""Unit tests for SAO-Store LocalIndex system.

覆盖:
  - TestParseKeywords:  _parse_keywords 各种输入格式
  - TestIndexer:        scan / build_index / 边界条件
  - TestSearcherScore:  _score 静态方法 8 级评分
  - TestSearcher:       search / list_all / type_filter / 降级扫描
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from sao_store_index.indexer import ComponentInfo, StoreIndexer
from sao_store_index.searcher import SearchResult, StoreSearcher


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

def _write_skill(
    base: Path,
    name: str,
    *,
    description: str = "",
    keywords: str = "",
    aliases: str = "",
    weight: int = 1,
    tools: list[str] | None = None,
    keyword_format: str = "string",  # "string" or "array"
) -> Path:
    """在 tmp_path 中写入一个 SKILL.toml，返回技能目录."""
    skill_dir = base / "skills" / f"sao-skill-{name}"
    pkg_dir = skill_dir / f"sao_skill_{name}"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # 构造 keywords / aliases 行
    if keyword_format == "array" and keywords:
        kw_items = [k.strip() for k in keywords.split(",") if k.strip()]
        kw_line = "keywords = [" + ", ".join(f'"{k}"' for k in kw_items) + "]"
    else:
        kw_line = f'keywords = "{keywords}"'

    if keyword_format == "array" and aliases:
        al_items = [a.strip() for a in aliases.split(",") if a.strip()]
        al_line = "aliases = [" + ", ".join(f'"{a}"' for a in al_items) + "]"
    else:
        al_line = f'aliases = "{aliases}"' if aliases else ""

    tools_block = ""
    for t in (tools or []):
        tools_block += f'\n[[tools]]\nname = "{t}"\ndescription = "tool {t}"\n'

    content = f"""[skill]
name = "{name}"
version = "1.0.0"
description = "{description}"
{kw_line}
{al_line}
weight = {weight}
{tools_block}
"""
    (pkg_dir / "SKILL.toml").write_text(content, encoding="utf-8")
    return skill_dir


def _write_expert(
    base: Path,
    name: str,
    *,
    description: str = "",
    keywords: str = "",
    aliases: str = "",
) -> Path:
    """在 tmp_path 中写入一个 Expert TOML，返回文件路径."""
    experts_dir = base / "experts"
    experts_dir.mkdir(parents=True, exist_ok=True)
    toml_path = experts_dir / f"{name}.toml"

    al_line = f'aliases = "{aliases}"' if aliases else ""

    content = f"""[expert]
name = "{name}"
version = "1.0.0"
description = "{description}"
keywords = "{keywords}"
{al_line}
search = false
temperature = 0.5
"""
    toml_path.write_text(content, encoding="utf-8")
    return toml_path


@pytest.fixture
def tmp_store(tmp_path: Path) -> Path:
    """创建一个包含 2 技能 + 2 专家的临时 Store."""
    _write_skill(
        tmp_path, "dice",
        description="掷骰子、抛硬币、随机抽选",
        keywords="骰子,掷骰,抛硬币,随机选择,dice,roll,flip",
        aliases="色子,扊骰",
        weight=1,
        tools=["roll", "flip", "pick"],
    )
    _write_skill(
        tmp_path, "reminder",
        description="管理提醒/闹钟：创建、查看、更新、取消",
        keywords="提醒,闹钟,定时,reminder,alarm,提醒我,别忘了",
        weight=1,
        tools=["set", "list"],
    )
    _write_expert(
        tmp_path, "weather",
        description="天气查询专家",
        keywords="天气,气温,降雨,weather",
    )
    _write_expert(
        tmp_path, "general",
        description="通用助理",
        keywords="聊天,问答,chat",
    )
    return tmp_path


# ═══════════════════════════════════════════════════════════════
# _parse_keywords
# ═══════════════════════════════════════════════════════════════

class TestParseKeywords:
    """StoreIndexer._parse_keywords 各格式解析."""

    def test_comma_string(self):
        assert StoreIndexer._parse_keywords("骰子,掷骰,dice") == ["骰子", "掷骰", "dice"]

    def test_comma_string_with_spaces(self):
        assert StoreIndexer._parse_keywords(" 骰子 , 掷骰 , dice ") == ["骰子", "掷骰", "dice"]

    def test_list_input(self):
        assert StoreIndexer._parse_keywords(["骰子", "掷骰"]) == ["骰子", "掷骰"]

    def test_list_with_empty_items(self):
        assert StoreIndexer._parse_keywords(["骰子", "", "  ", "dice"]) == ["骰子", "dice"]

    def test_list_with_non_string(self):
        assert StoreIndexer._parse_keywords(["ok", 42, None]) == ["ok"]  # type: ignore[arg-type]

    def test_empty_string(self):
        assert StoreIndexer._parse_keywords("") == []

    def test_whitespace_only_string(self):
        assert StoreIndexer._parse_keywords("   ") == []

    def test_empty_list(self):
        assert StoreIndexer._parse_keywords([]) == []

    def test_single_keyword(self):
        assert StoreIndexer._parse_keywords("骰子") == ["骰子"]


# ═══════════════════════════════════════════════════════════════
# Indexer
# ═══════════════════════════════════════════════════════════════

class TestIndexer:

    # ── scan ──────────────────────────────────────────────────

    def test_scan_finds_all(self, tmp_store: Path):
        components = StoreIndexer(tmp_store).scan()
        assert len(components) == 4  # 2 skills + 2 experts

    def test_scan_skill_fields(self, tmp_store: Path):
        comps = StoreIndexer(tmp_store).scan()
        dice = next(c for c in comps if c.name == "dice")
        assert dice.type == "skill"
        assert dice.version == "1.0.0"
        assert dice.weight == 1
        assert "骰子" in dice.keywords
        assert "dice" in dice.keywords
        assert "roll" in dice.tools
        assert dice.path == "skills/sao-skill-dice"

    def test_scan_skill_aliases(self, tmp_store: Path):
        comps = StoreIndexer(tmp_store).scan()
        dice = next(c for c in comps if c.name == "dice")
        assert "色子" in dice.aliases
        assert "扊骰" in dice.aliases

    def test_scan_expert_fields(self, tmp_store: Path):
        comps = StoreIndexer(tmp_store).scan()
        weather = next(c for c in comps if c.name == "weather")
        assert weather.type == "expert"
        assert "天气" in weather.keywords
        assert weather.weight is None
        assert weather.tools == []
        assert weather.path == "experts/weather.toml"

    def test_scan_ignores_non_skill_dir(self, tmp_store: Path):
        (tmp_store / "skills" / "not-a-skill").mkdir()
        comps = [c for c in StoreIndexer(tmp_store).scan() if c.type == "skill"]
        assert len(comps) == 2

    def test_scan_ignores_missing_toml(self, tmp_store: Path):
        (tmp_store / "skills" / "sao-skill-broken").mkdir()
        comps = [c for c in StoreIndexer(tmp_store).scan() if c.type == "skill"]
        assert len(comps) == 2

    def test_scan_ignores_invalid_toml(self, tmp_store: Path):
        bad = tmp_store / "skills" / "sao-skill-bad"
        bad_pkg = bad / "sao_skill_bad"
        bad_pkg.mkdir(parents=True)
        (bad_pkg / "SKILL.toml").write_text("{{{invalid toml", encoding="utf-8")
        comps = [c for c in StoreIndexer(tmp_store).scan() if c.type == "skill"]
        assert len(comps) == 2

    def test_scan_handles_missing_name(self, tmp_store: Path):
        noname = tmp_store / "skills" / "sao-skill-noname"
        noname_pkg = noname / "sao_skill_noname"
        noname_pkg.mkdir(parents=True)
        (noname_pkg / "SKILL.toml").write_text('[skill]\nversion = "1.0.0"', encoding="utf-8")
        comps = [c for c in StoreIndexer(tmp_store).scan() if c.type == "skill"]
        assert len(comps) == 2

    def test_scan_empty_store(self, tmp_path: Path):
        (tmp_path / "skills").mkdir()
        (tmp_path / "experts").mkdir()
        assert StoreIndexer(tmp_path).scan() == []

    def test_scan_no_dirs_at_all(self, tmp_path: Path):
        """skills/ 和 experts/ 都不存在."""
        assert StoreIndexer(tmp_path).scan() == []

    def test_scan_array_keywords_format(self, tmp_path: Path):
        """SKILL.toml 中 keywords 用数组格式."""
        _write_skill(
            tmp_path, "arr",
            description="array kw test",
            keywords="a,b,c",
            keyword_format="array",
            tools=["t1"],
        )
        (tmp_path / "experts").mkdir(exist_ok=True)
        comps = StoreIndexer(tmp_path).scan()
        assert comps[0].keywords == ["a", "b", "c"]

    # ── build_index ───────────────────────────────────────────

    def test_build_index_creates_file(self, tmp_store: Path):
        idx = StoreIndexer(tmp_store).build_index()
        assert idx.exists()
        assert idx.name == "index.toml"

    def test_build_index_valid_toml(self, tmp_store: Path):
        StoreIndexer(tmp_store).build_index()
        data = tomllib.loads((tmp_store / "index.toml").read_text(encoding="utf-8"))
        assert data["meta"]["skill_count"] == 2
        assert data["meta"]["expert_count"] == 2
        assert len(data["skills"]) == 2
        assert len(data["experts"]) == 2

    def test_build_index_keywords_are_arrays(self, tmp_store: Path):
        StoreIndexer(tmp_store).build_index()
        data = tomllib.loads((tmp_store / "index.toml").read_text(encoding="utf-8"))
        for skill in data["skills"]:
            assert isinstance(skill["keywords"], list)
        for expert in data["experts"]:
            assert isinstance(expert["keywords"], list)

    def test_build_index_tools_present(self, tmp_store: Path):
        StoreIndexer(tmp_store).build_index()
        data = tomllib.loads((tmp_store / "index.toml").read_text(encoding="utf-8"))
        dice = next(s for s in data["skills"] if s["name"] == "dice")
        assert dice["tools"] == ["roll", "flip", "pick"]

    def test_build_index_roundtrip(self, tmp_store: Path):
        """build → load 后数据一致."""
        indexer = StoreIndexer(tmp_store)
        indexer.build_index()

        searcher = StoreSearcher(tmp_store)
        searcher.load()
        loaded = searcher.list_all()

        scanned = indexer.scan()
        assert len(loaded) == len(scanned)
        for l, s in zip(
            sorted(loaded, key=lambda c: c.name),
            sorted(scanned, key=lambda c: c.name),
        ):
            assert l.name == s.name
            assert l.type == s.type
            assert set(l.keywords) == set(s.keywords)


# ═══════════════════════════════════════════════════════════════
# Searcher._score  (静态方法直接测试)
# ═══════════════════════════════════════════════════════════════

class TestSearcherScore:
    """直接测试 _score 静态方法的 8 个评分等级."""

    @staticmethod
    def _comp(**kw) -> ComponentInfo:
        defaults = dict(
            name="test", type="skill", version="1.0.0",
            description="", keywords=[], aliases=[], path="", weight=1, tools=[],
        )
        defaults.update(kw)
        return ComponentInfo(**defaults)  # type: ignore[arg-type]

    # Level 1 — 名称完全匹配 (100)
    def test_name_exact(self):
        score, _ = StoreSearcher._score("dice", self._comp(name="dice"))
        assert score == 100

    def test_name_exact_case_insensitive(self):
        score, _ = StoreSearcher._score("dice", self._comp(name="DICE"))
        assert score == 100

    # Level 2 — 名称包含 (90)
    def test_name_contains_query_in_name(self):
        score, _ = StoreSearcher._score("rem", self._comp(name="reminder"))
        assert score == 90

    def test_name_contains_name_in_query(self):
        score, _ = StoreSearcher._score("dice_game", self._comp(name="dice"))
        assert score == 90

    def test_name_single_char_no_90(self):
        """单字符查询不触发名称包含 (len<2 guard)."""
        score, _ = StoreSearcher._score("d", self._comp(name="dice"))
        assert score < 90 or score == 100

    # Level 3 — 关键词完全匹配 (80)
    def test_keyword_exact_chinese(self):
        score, _ = StoreSearcher._score("骰子", self._comp(keywords=["骰子", "dice"]))
        assert score == 80

    def test_keyword_exact_english(self):
        score, _ = StoreSearcher._score("roll", self._comp(keywords=["roll", "flip"]))
        assert score == 80

    # Level 4 — 别名完全匹配 (75)
    def test_alias_exact(self):
        score, _ = StoreSearcher._score("色子", self._comp(aliases=["色子"]))
        assert score == 75

    # Level 5 — 关键词包含 (60)
    def test_keyword_substring_query_contains_kw(self):
        """查询 '掷骰子吧' 包含关键词 '骰子'."""
        score, _ = StoreSearcher._score("掷骰子吧", self._comp(keywords=["骰子"]))
        assert score == 60

    def test_keyword_substring_kw_contains_query(self):
        """关键词 '提醒我' 包含查询 '提醒'."""
        score, _ = StoreSearcher._score("提醒", self._comp(keywords=["提醒我"]))
        assert score == 60

    def test_keyword_short_no_match(self):
        """单字符关键词不触发包含匹配 (len<2 guard)."""
        score, _ = StoreSearcher._score("abc", self._comp(keywords=["a"]))
        assert score < 60

    # Level 6 — 别名包含 (55)
    def test_alias_substring(self):
        score, _ = StoreSearcher._score("掷色子", self._comp(aliases=["色子"]))
        assert score == 55

    # Level 7 — 描述匹配 (40)
    def test_description_match(self):
        score, _ = StoreSearcher._score(
            "随机抽选", self._comp(description="掷骰子、抛硬币、随机抽选"),
        )
        assert score == 40

    def test_description_single_char_no_match(self):
        """单字符查询不触发描述匹配 (len<2 guard)."""
        score, _ = StoreSearcher._score("掷", self._comp(description="掷骰子"))
        assert score == 0

    # Level 8 — 模糊匹配 (≤30)
    def test_fuzzy_match(self):
        comp = self._comp(description="掷骰子抛硬币", keywords=["骰子", "硬币"])
        score, reason = StoreSearcher._score("骰硬", comp)
        assert 0 < score <= 30
        assert "模糊" in reason

    def test_fuzzy_below_threshold_no_match(self):
        """字符重叠率 < 60% → 不匹配."""
        comp = self._comp(description="abc", keywords=["abc"])
        score, _ = StoreSearcher._score("xyzw", comp)
        assert score == 0

    # No match at all
    def test_total_miss(self):
        comp = self._comp(
            name="dice", description="掷骰子", keywords=["骰子"],
        )
        score, _ = StoreSearcher._score("量子计算", comp)
        assert score == 0

    # priority: keyword exact (80) beats description (40) — scored correctly
    def test_keyword_wins_over_description(self):
        comp = self._comp(
            description="骰子游戏", keywords=["骰子"],
        )
        score, reason = StoreSearcher._score("骰子", comp)
        assert score == 80
        assert "关键词匹配" in reason


# ═══════════════════════════════════════════════════════════════
# Searcher (集成)
# ═══════════════════════════════════════════════════════════════

class TestSearcher:

    # ── 基本搜索 ──────────────────────────────────────────────

    def test_search_name_exact(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("dice")
        assert results and results[0].name == "dice" and results[0].score == 100

    def test_search_keyword_chinese(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("骰子")
        assert results and results[0].name == "dice" and results[0].score == 80

    def test_search_keyword_english(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("roll")
        assert results and results[0].name == "dice"

    def test_search_keyword_substring(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("掷骰子")
        assert results and results[0].name == "dice"

    def test_search_reminder(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("提醒")
        assert results and results[0].name == "reminder"

    def test_search_weather(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("天气")
        assert results and results[0].name == "weather"

    def test_search_alias(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("色子")
        assert results and results[0].name == "dice"

    # ── type_filter ───────────────────────────────────────────

    def test_filter_skill_only(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("天气", type_filter="skill")
        assert all(r.type == "skill" for r in results)

    def test_filter_expert_only(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("天气", type_filter="expert")
        assert results and results[0].type == "expert"

    # ── 边界条件 ──────────────────────────────────────────────

    def test_empty_query(self, tmp_store: Path):
        assert StoreSearcher(tmp_store).search("") == []

    def test_whitespace_query(self, tmp_store: Path):
        assert StoreSearcher(tmp_store).search("   ") == []

    def test_no_match(self, tmp_store: Path):
        assert StoreSearcher(tmp_store).search("量子计算") == []

    def test_case_insensitive(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("DICE")
        assert results and results[0].name == "dice"

    def test_sorted_by_score(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("dice")
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_limit(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("a", limit=1)
        assert len(results) <= 1

    # ── search result 字段完整性 ──────────────────────────────

    def test_result_has_all_fields(self, tmp_store: Path):
        results = StoreSearcher(tmp_store).search("dice")
        r = results[0]
        assert r.name == "dice"
        assert r.type == "skill"
        assert r.version == "1.0.0"
        assert r.description
        assert r.path
        assert r.score > 0
        assert r.match_reason
        assert r.weight == 1
        assert "roll" in r.tools

    # ── list_all ──────────────────────────────────────────────

    def test_list_all(self, tmp_store: Path):
        assert len(StoreSearcher(tmp_store).list_all()) == 4

    def test_list_all_skills_only(self, tmp_store: Path):
        skills = StoreSearcher(tmp_store).list_all(type_filter="skill")
        assert len(skills) == 2
        assert all(s.type == "skill" for s in skills)

    def test_list_all_experts_only(self, tmp_store: Path):
        experts = StoreSearcher(tmp_store).list_all(type_filter="expert")
        assert len(experts) == 2
        assert all(e.type == "expert" for e in experts)

    # ── index.toml 加载 vs 降级扫描 ──────────────────────────

    def test_uses_index_toml_if_exists(self, tmp_store: Path):
        StoreIndexer(tmp_store).build_index()
        searcher = StoreSearcher(tmp_store)
        results = searcher.search("dice")
        assert results and results[0].name == "dice"

    def test_falls_back_to_scan(self, tmp_store: Path):
        """无 index.toml 时降级为实时扫描."""
        assert not (tmp_store / "index.toml").exists()
        searcher = StoreSearcher(tmp_store)
        results = searcher.search("dice")
        assert results and results[0].name == "dice"
