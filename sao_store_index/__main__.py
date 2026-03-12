"""CLI for SAO-Store LocalIndex.

Usage:
    python -m sao_store_index rebuild                  重建 index.toml
    python -m sao_store_index search QUERY             搜索组件
    python -m sao_store_index search QUERY --type skill  只搜技能
    python -m sao_store_index list                     列出所有组件
"""

from __future__ import annotations

import sys
from pathlib import Path

from .indexer import StoreIndexer
from .searcher import StoreSearcher


def _find_store_root() -> Path:
    """从当前目录向上查找 SAO-Store 根目录."""
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / "skills").is_dir() and (p / "experts").is_dir():
            return p
    return cwd


def _parse_args(args: list[str]) -> tuple[str | None, list[str]]:
    """提取 --store PATH 选项，返回 (store_path, remaining_args)."""
    store_path = None
    remaining = list(args)
    if "--store" in remaining:
        idx = remaining.index("--store")
        if idx + 1 < len(remaining):
            store_path = remaining[idx + 1]
            remaining = remaining[:idx] + remaining[idx + 2:]
    return store_path, remaining


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    command = args[0]
    store_str, remaining = _parse_args(args[1:])
    store_path = Path(store_str) if store_str else _find_store_root()

    if command == "rebuild":
        indexer = StoreIndexer(store_path)
        index_path = indexer.build_index()
        components = indexer.scan()
        skills = sum(1 for c in components if c.type == "skill")
        experts = sum(1 for c in components if c.type == "expert")
        print(f"✅ 索引已重建: {index_path}")
        print(f"   技能: {skills} 个 | 专家: {experts} 个")

    elif command == "search":
        if not remaining:
            print("⚠️ 请提供搜索关键词")
            return

        query = remaining[0]
        type_filter = None
        if "--type" in remaining:
            idx = remaining.index("--type")
            if idx + 1 < len(remaining):
                type_filter = remaining[idx + 1]

        searcher = StoreSearcher(store_path)
        results = searcher.search(query, type_filter=type_filter)

        if not results:
            print(f'🔍 未找到与 "{query}" 相关的组件')
            return

        print(f'🔍 搜索 "{query}"，找到 {len(results)} 个结果:\n')
        for r in results:
            icon = "🔧" if r.type == "skill" else "🎓"
            w = f" (weight={r.weight})" if r.weight is not None else ""
            print(f"  {icon} {r.name} v{r.version}{w}")
            print(f"     {r.description}")
            print(f"     匹配: {r.match_reason} (score={r.score})")
            if r.tools:
                print(f"     工具: {', '.join(r.tools)}")
            print()

    elif command == "list":
        type_filter = None
        if "--type" in remaining:
            idx = remaining.index("--type")
            if idx + 1 < len(remaining):
                type_filter = remaining[idx + 1]

        searcher = StoreSearcher(store_path)
        components = searcher.list_all(type_filter=type_filter)

        if not components:
            print("📦 没有找到组件")
            return

        skills = [c for c in components if c.type == "skill"]
        experts = [c for c in components if c.type == "expert"]

        if skills and (type_filter is None or type_filter == "skill"):
            print(f"🔧 技能 ({len(skills)}):")
            for c in skills:
                w = f" weight={c.weight}" if c.weight is not None else ""
                print(f"   {c.name} v{c.version}{w} — {c.description}")

        if experts and (type_filter is None or type_filter == "expert"):
            print(f"\n🎓 专家 ({len(experts)}):")
            for c in experts:
                print(f"   {c.name} v{c.version} — {c.description}")

    else:
        print(f"⚠️ 未知命令: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
