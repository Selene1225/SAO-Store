# SAO-Store LocalIndex 使用指南

> 本文档说明 SAO 如何通过 LocalIndex 系统搜索、发现和管理 SAO-Store 中的 Skill 与 Expert。

---

## 目录

1. [概述](#1-概述)
2. [架构](#2-架构)
3. [CLI 命令参考](#3-cli-命令参考)
4. [SAO 代码集成](#4-sao-代码集成)
5. [搜索评分规则](#5-搜索评分规则)
6. [index.toml 格式](#6-indextoml-格式)
7. [Skill 开发者必读](#7-skill-开发者必读)
8. [FAQ](#8-faq)

---

## 1. 概述

SAO-Store LocalIndex 是一套本地组件索引系统，解决的核心问题：

**SAO 如何知道 Store 里有哪些 Skill / Expert？**

方案：扫描 `skills/` 和 `experts/` 目录下的所有 TOML 元数据 → 生成一份集中索引文件 `index.toml` → SAO 读取该文件进行关键词/模糊搜索。

### 特点

- **零外部依赖** — 仅用 Python 3.11+ 标准库 `tomllib`
- **中英文搜索** — 支持中文关键词精确/模糊匹配
- **8 级评分** — 从名称精确匹配(100) 到字符模糊匹配(≤30)
- **降级策略** — 无 index.toml 时自动实时扫描

---

## 2. 架构

```
SAO-Store/
├── index.toml                    ← 自动生成的集中索引
├── sao_store_index/              ← 索引包
│   ├── __init__.py               # 导出 StoreIndexer, StoreSearcher
│   ├── indexer.py                # 扫描 → 生成 index.toml
│   ├── searcher.py               # 读取 index.toml → 搜索
│   └── __main__.py               # CLI 入口
├── skills/                       ← SKILL.toml 在这里被扫描
│   ├── sao-skill-dice/
│   ├── sao-skill-reminder/
│   └── ...
└── experts/                      ← Expert TOML 在这里被扫描
    ├── weather.toml
    └── ...
```

**数据流：**

```
SKILL.toml / Expert.toml
         │
    StoreIndexer.scan()
         │
    StoreIndexer.build_index()  →  index.toml
         │
    StoreSearcher.load()        ←  index.toml
         │
    StoreSearcher.search("骰子")  →  [SearchResult(...)]
```

---

## 3. CLI 命令参考

所有命令在 SAO-Store 根目录下运行。

### 3.1 重建索引

```bash
python -m sao_store_index rebuild
```

输出示例：
```
✅ 索引已重建: C:\...\SAO-Store\index.toml
   技能: 3 个 | 专家: 5 个
```

> **什么时候必须执行？** 每次新增/修改/删除 Skill 或 Expert 的 TOML 后。

### 3.2 搜索组件

```bash
# 搜索所有类型
python -m sao_store_index search "骰子"

# 只搜 Skill
python -m sao_store_index search "骰子" --type skill

# 只搜 Expert
python -m sao_store_index search "天气" --type expert
```

输出示例：
```
🔍 搜索 "骰子"，找到 1 个结果:

  🔧 dice v1.0.0 (weight=1)
     掷骰子、抛硬币、随机抽选
     匹配: 关键词匹配: 骰子 (score=80)
     工具: roll, flip, pick
```

### 3.3 列出所有组件

```bash
# 列出全部
python -m sao_store_index list

# 只列 Skill
python -m sao_store_index list --type skill
```

### 3.4 指定 Store 路径

如果不在 SAO-Store 目录中运行：

```bash
python -m sao_store_index search "提醒" --store /path/to/SAO-Store
```

---

## 4. SAO 代码集成

### 4.1 搜索组件

```python
from sao_store_index import StoreSearcher

searcher = StoreSearcher("/path/to/SAO-Store")

# 搜索（自动加载 index.toml，不存在则降级扫描）
results = searcher.search("提醒我明天开会")
# → [SearchResult(name="reminder", type="skill", score=60, match_reason="关键词部分匹配: 提醒我", ...)]

for r in results:
    print(f"{r.name} (score={r.score}): {r.description}")
    print(f"  匹配原因: {r.match_reason}")
    if r.tools:
        print(f"  工具: {', '.join(r.tools)}")
```

### 4.2 SearchResult 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 组件名 (如 `"dice"`) |
| `type` | `str` | `"skill"` 或 `"expert"` |
| `version` | `str` | 版本号 |
| `description` | `str` | 描述文本 |
| `path` | `str` | 相对路径 (如 `"skills/sao-skill-dice"`) |
| `score` | `int` | 匹配分数 0-100 |
| `match_reason` | `str` | 人类可读的匹配原因 |
| `weight` | `int \| None` | Skill 权重 (Expert 为 None) |
| `tools` | `list[str]` | Skill 的工具列表 (Expert 为 []) |

### 4.3 按类型过滤

```python
# 只搜 Skill
skills = searcher.search("骰子", type_filter="skill")

# 只搜 Expert
experts = searcher.search("天气", type_filter="expert")

# 限制返回数量
top3 = searcher.search("提醒", limit=3)
```

### 4.4 列出所有组件

```python
from sao_store_index import StoreSearcher

searcher = StoreSearcher("/path/to/SAO-Store")

all_components = searcher.list_all()              # 全部
all_skills = searcher.list_all("skill")           # 只列 Skill
all_experts = searcher.list_all("expert")         # 只列 Expert

# 返回 ComponentInfo 列表
for comp in all_skills:
    print(f"{comp.name}: {comp.description} (weight={comp.weight})")
```

### 4.5 手动重建索引

```python
from sao_store_index import StoreIndexer

indexer = StoreIndexer("/path/to/SAO-Store")
index_path = indexer.build_index()   # → Path("index.toml")
components = indexer.scan()          # → [ComponentInfo(...)]
```

### 4.6 store_manager 集成示例

SAO 的 `store_manager` 可以这样接入：

```python
class StoreManager:
    def __init__(self, store_path: str):
        self.searcher = StoreSearcher(store_path)

    def find_skill(self, user_query: str) -> str | None:
        """根据用户意图搜索最匹配的 Skill."""
        results = self.searcher.search(user_query, type_filter="skill", limit=3)
        if results and results[0].score >= 60:
            return results[0].name
        return None

    def find_expert(self, user_query: str) -> str | None:
        """搜索最匹配的 Expert."""
        results = self.searcher.search(user_query, type_filter="expert", limit=3)
        if results and results[0].score >= 60:
            return results[0].name
        return None

    def get_skill_path(self, user_query: str) -> str | None:
        """返回 Skill 的安装路径，用于 pip install -e."""
        results = self.searcher.search(user_query, type_filter="skill", limit=1)
        if results and results[0].score >= 60:
            return results[0].path
        return None
```

---

## 5. 搜索评分规则

搜索引擎使用 8 级评分，**由高到低**短路匹配：

| 级别 | 分数 | 条件 | 示例 |
|------|------|------|------|
| 1 | **100** | 名称完全匹配 | `"dice"` → `dice` |
| 2 | **90** | 名称包含 (query⊂name 或 name⊂query) | `"rem"` → `reminder` |
| 3 | **80** | 关键词完全匹配 | `"骰子"` → dice (keyword=骰子) |
| 4 | **75** | 别名完全匹配 | `"色子"` → dice (alias=色子) |
| 5 | **60** | 关键词包含 (query⊂kw 或 kw⊂query) | `"提醒我开会"` → reminder (keyword=提醒我) |
| 6 | **55** | 别名包含 | `"掷色子"` → dice (alias=色子) |
| 7 | **40** | 描述文本包含 | `"随机抽选"` → dice (desc 含) |
| 8 | **≤30** | 字符重叠模糊 (≥60% 字符在候选中出现) | `"骰硬"` → dice (模糊) |

**建议阈值：**
- `score >= 80`：高度自信，可直接安装/调用
- `60 <= score < 80`：中度匹配，可展示给用户确认
- `score < 60`：低匹配，建议提示用户换关键词

---

## 6. index.toml 格式

自动生成，**请勿手动编辑**。

```toml
# SAO-Store Component Index (auto-generated)
# Rebuild: python -m sao_store_index rebuild

[meta]
version = "1.0.0"
updated = "2026-03-12"
skill_count = 3
expert_count = 5

[[skills]]
name = "dice"
version = "1.0.0"
description = "掷骰子、抛硬币、随机抽选"
keywords = ["骰子", "掷骰", "抛硬币", "dice", "roll", "flip"]
aliases = ["色子", "扊骰"]
path = "skills/sao-skill-dice"
weight = 1
tools = ["roll", "flip", "pick"]

[[experts]]
name = "weather"
version = "1.0.0"
description = "天气查询专家"
keywords = ["天气", "气温", "降雨", "weather"]
aliases = []
path = "experts/weather.toml"
```

---

## 7. Skill 开发者必读

### 开发完成 → 上线的 checklist

```
✅ 1. SKILL.toml 包含 keywords 字段（中文在前，英文在后，10-20 个词）
✅ 2. 所有单元测试通过: python -m pytest skills/sao-skill-{name}/tests/ -v
✅ 3. 重建索引: python -m sao_store_index rebuild
✅ 4. 验证搜索: python -m sao_store_index search "{你的中文关键词}"
✅ 5. 提交推送: git add -A && git commit && git push
```

### keywords 编写规范

```toml
# ✅ 好的 keywords — 中文高频触发词在前，英文在后
keywords = "骰子,掷骰,抛硬币,随机选择,dice,roll,flip,coin,random,pick"

# ❌ 坏的 keywords — 纯英文、太少
keywords = "dice"

# ❌ 没有 keywords — 搜不到！
# (缺少 keywords 字段)
```

### 为什么搜不到我的 Skill？

1. **没有 `keywords` 字段** — `SKILL.toml` 的 `[skill]` 中必须加
2. **没有 `python -m sao_store_index rebuild`** — 新组件不会自动进入 `index.toml`
3. **keywords 太少** — 多加中文同义词、口语化表达
4. **拼写错误** — 检查 TOML 语法是否正确

---

## 8. FAQ

### Q: index.toml 需要提交到 git 吗？

**是的。** `index.toml` 是 SAO 运行时读取的索引文件，必须和代码一起提交。
SAO 部署后直接读取该文件，无需在生产环境执行 rebuild。

### Q: 没有 index.toml 会怎样？

StoreSearcher 会降级为**实时扫描**模式 — 遍历 `skills/` 和 `experts/` 目录读取所有 TOML。
功能完全一致，但首次搜索会稍慢（组件多时）。

### Q: 搜索是否支持拼音？

目前不支持。搜索基于字符匹配，请使用中文汉字或英文关键词。

### Q: Expert 需要 rebuild 吗？

**是的。** Expert TOML 同样被扫描并写入 `index.toml`。
新增或修改 Expert 后也需要 `python -m sao_store_index rebuild`。

### Q: 如何在 SAO 中自动安装搜索到的 Skill？

```python
import subprocess
from sao_store_index import StoreSearcher

searcher = StoreSearcher("/path/to/SAO-Store")
results = searcher.search("骰子", type_filter="skill")

if results:
    skill_path = results[0].path   # "skills/sao-skill-dice"
    full_path = f"/path/to/SAO-Store/{skill_path}"
    subprocess.run(["pip", "install", "-e", full_path], check=True)
```
