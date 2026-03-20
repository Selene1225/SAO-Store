"""扫描 SAO-Store 目录，生成 index.toml 统一索引."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────

@dataclass
class ComponentInfo:
    """组件元数据."""

    name: str
    type: str                                  # "skill" or "expert"
    version: str
    description: str
    keywords: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    path: str = ""
    weight: int | None = None
    tools: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Indexer
# ─────────────────────────────────────────────────────────────

class StoreIndexer:
    """扫描 SAO-Store 仓库，生成统一组件索引."""

    def __init__(self, store_path: str | Path) -> None:
        self.store_path = Path(store_path)

    # ── 扫描 ─────────────────────────────────────────────────

    def scan(self) -> list[ComponentInfo]:
        """扫描所有 skills 和 experts，返回组件列表."""
        components: list[ComponentInfo] = []

        # Skills
        skills_dir = self.store_path / "skills"
        if skills_dir.is_dir():
            for skill_dir in sorted(skills_dir.iterdir()):
                if skill_dir.is_dir() and skill_dir.name.startswith("sao-skill-"):
                    # SKILL.toml 位于包目录内 (sao_skill_{name}/SKILL.toml)
                    pkg_name = skill_dir.name.replace("-", "_")
                    toml_path = skill_dir / pkg_name / "SKILL.toml"
                    if not toml_path.exists():
                        # 兼容旧布局: 根目录下的 SKILL.toml
                        toml_path = skill_dir / "SKILL.toml"
                    if toml_path.exists():
                        comp = self._parse_skill(toml_path, skill_dir)
                        if comp:
                            components.append(comp)

        # Experts
        experts_dir = self.store_path / "experts"
        if experts_dir.is_dir():
            for expert_file in sorted(experts_dir.glob("*.toml")):
                comp = self._parse_expert(expert_file)
                if comp:
                    components.append(comp)

        return components

    # ── 构建 index.toml ──────────────────────────────────────

    def build_index(self) -> Path:
        """扫描并写入 index.toml，返回文件路径."""
        components = self.scan()
        index_path = self.store_path / "index.toml"

        skills = [c for c in components if c.type == "skill"]
        experts = [c for c in components if c.type == "expert"]

        lines = [
            "# SAO-Store Component Index (auto-generated)",
            "# Rebuild: python -m sao_store_index rebuild",
            "",
            "[meta]",
            'version = "1.0.0"',
            f'updated = "{date.today().isoformat()}"',
            f"skill_count = {len(skills)}",
            f"expert_count = {len(experts)}",
        ]

        for comp in skills:
            lines.append("")
            lines.append("[[skills]]")
            lines.extend(self._format_component(comp))

        for comp in experts:
            lines.append("")
            lines.append("[[experts]]")
            lines.extend(self._format_component(comp))

        lines.append("")  # trailing newline
        index_path.write_text("\n".join(lines), encoding="utf-8")
        return index_path

    # ── 解析 SKILL.toml ──────────────────────────────────────

    def _parse_skill(self, toml_path: Path, skill_dir: Path) -> ComponentInfo | None:
        """解析 SKILL.toml → ComponentInfo."""
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        skill = data.get("skill", {})
        name = skill.get("name", "")
        if not name:
            return None

        keywords = self._parse_keywords(skill.get("keywords", ""))
        aliases = self._parse_keywords(skill.get("aliases", ""))
        tools = [t.get("name", "") for t in data.get("tools", []) if t.get("name")]

        return ComponentInfo(
            name=name,
            type="skill",
            version=skill.get("version", "0.0.0"),
            description=skill.get("description", ""),
            keywords=keywords,
            aliases=aliases,
            path=str(skill_dir.relative_to(self.store_path)).replace("\\", "/"),
            weight=skill.get("weight"),
            tools=tools,
        )

    # ── 解析 Expert TOML ─────────────────────────────────────

    def _parse_expert(self, toml_path: Path) -> ComponentInfo | None:
        """解析 Expert TOML → ComponentInfo."""
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        expert = data.get("expert", {})
        name = expert.get("name", "")
        if not name:
            return None

        keywords = self._parse_keywords(expert.get("keywords", ""))
        aliases = self._parse_keywords(expert.get("aliases", ""))

        return ComponentInfo(
            name=name,
            type="expert",
            version=expert.get("version", "0.0.0"),
            description=expert.get("description", ""),
            keywords=keywords,
            aliases=aliases,
            path=f"experts/{toml_path.name}",
        )

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _parse_keywords(raw: str | list) -> list[str]:
        """Parse keywords — 兼容逗号字符串和数组两种格式."""
        if isinstance(raw, list):
            return [s.strip() for s in raw if isinstance(s, str) and s.strip()]
        if isinstance(raw, str) and raw.strip():
            return [s.strip() for s in raw.split(",") if s.strip()]
        return []

    @staticmethod
    def _format_component(comp: ComponentInfo) -> list[str]:
        """将 ComponentInfo 格式化为 TOML 键值行."""

        def q(s: str) -> str:
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

        def arr(items: list[str]) -> str:
            if not items:
                return "[]"
            return "[" + ", ".join(q(s) for s in items) + "]"

        lines = [
            f"name = {q(comp.name)}",
            f"version = {q(comp.version)}",
            f"description = {q(comp.description)}",
            f"keywords = {arr(comp.keywords)}",
            f"aliases = {arr(comp.aliases)}",
            f"path = {q(comp.path)}",
        ]
        if comp.weight is not None:
            lines.append(f"weight = {comp.weight}")
        if comp.tools:
            lines.append(f"tools = {arr(comp.tools)}")
        return lines
