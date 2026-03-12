"""SAO-Store LocalIndex — 组件搜索索引系统.

提供两个核心能力:
1. StoreIndexer: 扫描 SAO-Store 目录 → 生成 index.toml
2. StoreSearcher: 基于 index.toml 搜索组件（关键词/模糊/别名）

Usage:
    python -m sao_store_index rebuild          # 重建索引
    python -m sao_store_index search "骰子"    # 搜索组件
"""

from .indexer import StoreIndexer, ComponentInfo
from .searcher import StoreSearcher, SearchResult

__all__ = ["StoreIndexer", "StoreSearcher", "ComponentInfo", "SearchResult"]
