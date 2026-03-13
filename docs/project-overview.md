# SAO-Store 项目总览

> 供代码审查参考。说明项目架构、文件结构、功能实现的方法论。
> 不解释具体代码 — 请直接阅读源码判断实现是否正确。

---

## 1. 项目定位

SAO-Store 是 Super-Agent-OS（SAO）的 **组件仓库**，提供两类可插拔组件：

| 类型 | 本质 | 载体 | 发现机制 |
|------|------|------|----------|
| **Skill** | Python pip 包 | `skills/sao-skill-{name}/` 目录 | `pyproject.toml` entry-point `"sao.skills"` |
| **Expert** | 纯 TOML 配置 | `experts/{name}.toml` 单文件 | 目录扫描 `experts/*.toml` |

SAO 主程序通过 **LocalIndex**（`index.toml`）搜索/发现组件，按 weight 决定调用策略。

---

## 2. 整体文件结构

```
SAO-Store/
├── index.toml                        # [自动生成] 组件搜索索引
├── pyproject.toml                    # 根包配置 (sao-store-index)
├── README.md
│
├── .github/
│   └── copilot-instructions.md       # IDE AI 助手开发规范
│
├── sao_store_index/                  # LocalIndex 搜索引擎包
│   ├── __init__.py                   # 导出 StoreIndexer, StoreSearcher
│   ├── __main__.py                   # CLI: rebuild / search / list
│   ├── indexer.py                    # 扫描目录 → 生成 index.toml
│   └── searcher.py                   # 读取 index.toml → 多级评分搜索
│
├── tests/
│   └── test_store_index.py           # LocalIndex 单元测试 (64 cases)
│
├── skills/                           # ── Skill 组件 ──
│   ├── sao-skill-dice/               # 掷骰子 (weight=1, 轻量)
│   ├── sao-skill-programming/        # 全周期编程 (weight=8, SubAgent)
│   └── sao-skill-reminder/           # 提醒管理 (weight=1, 轻量)
│
├── experts/                          # ── Expert 组件 ──
│   ├── code.toml                     # 编程专家
│   ├── general.toml                  # 通用助理（默认）
│   ├── search.toml                   # 搜索专家
│   ├── translate.toml                # 翻译专家
│   └── weather.toml                  # 天气专家
│
└── docs/                             # 文档
    ├── project-overview.md           # ← 本文件
    ├── implementation-plan.md        # 改进计划（T1-T3 ✅, T4-T5 待做）
    ├── local-index-guide.md          # LocalIndex 使用指南
    ├── programming-skill.md          # Programming Skill 设计文档
    ├── rules-reference.md            # Programming Skill 规则素材
    ├── sao-integration-guide.md      # SAO 集成规范
    ├── skills.md                     # 技能总路线图
    └── archived/                     # 与当前实现不符的旧文档
        ├── experts.md                # 旧版 Expert 架构（Python 类方式）
        └── sao-runtime-improvements.md  # SAO 主仓库改进提案
```

---

## 3. 组件架构

### 3.1 Skill 架构

每个 Skill 是一个独立 pip 包，遵循统一目录约定：

```
skills/sao-skill-{name}/
├── SKILL.toml                        # 元数据 + tools 声明 + examples + instructions
├── pyproject.toml                    # pip 包配置 + entry-point + pytest 配置
├── sao_skill_{name}/
│   ├── __init__.py                   # 导出 {Name}Skill 类
│   └── skill.py                      # BaseSkill 子类实现
└── tests/
    └── test_skill.py                 # 单元测试
```

**关键设计决策：**

- **元数据与代码分离**: tools 定义在 `SKILL.toml` 中声明（SAO 读取后注入 Router prompt），不在 Python 代码中定义
- **Entry-point 发现**: `pyproject.toml` 通过 `[project.entry-points."sao.skills"]` 注册，SAO 通过 `importlib.metadata` 发现可用技能
- **Weight 路由**: weight 1-3 主 Agent 同步直调，7-10 派 SubAgent 异步管理
- **`[skill.requires]` Gating**: 声明 `env`（环境变量）、`bins`（外部命令）、`features`（功能开关），SAO 加载时校验是否满足

### 3.2 Expert 架构

Expert 是纯 TOML 配置文件，无代码：

```toml
[expert]
name = "{name}"
description = "..."
keywords = "..."
search = true/false          # 是否联网搜索
temperature = 0.3

[expert.requires]            # 可选 gating
features = ["..."]

[expert.system_prompt]
text = "..."                 # System Prompt 全文
```

SAO Router 根据用户消息匹配 Expert name 或关键词，切换到对应 Expert 的 system prompt + 参数配置。

### 3.3 组件对比

| 维度 | Skill | Expert |
|------|-------|--------|
| 执行能力 | 有（Python 代码） | 无（仅影响对话） |
| 文件数 | 多文件目录 | 单个 TOML |
| 注册方式 | entry-point | 目录扫描 |
| keywords | `SKILL.toml [skill]` | Expert TOML `[expert]` |
| gating | env + bins + features | features only |

---

## 4. LocalIndex 搜索引擎

### 4.1 定位

`sao_store_index/` 是仓库级 Python 包，解决 "SAO 如何发现 SAO-Store 中的组件" 问题。

### 4.2 两层架构

```
StoreIndexer (indexer.py)        StoreSearcher (searcher.py)
  扫描 skills/ + experts/   →     读取 index.toml
  解析各 TOML 元数据        →     多级评分匹配
  生成 index.toml            →     返回 [SearchResult]
```

### 4.3 索引生成（Indexer）

`StoreIndexer.build_index()` 流程：

1. 遍历 `skills/sao-skill-*/SKILL.toml`，解析 `[skill]` 段提取 name/version/description/keywords/weight/tools
2. 遍历 `experts/*.toml`，解析 `[expert]` 段提取同类字段
3. 统一写入 `index.toml`（`[[skills]]` + `[[experts]]` 数组格式）

数据模型是 `ComponentInfo` dataclass，统一表示 Skill 和 Expert 的元数据。

### 4.4 搜索评分（Searcher）

`StoreSearcher.search(query)` 采用 **8 级优先评分**，单关键词输入：

| 优先级 | 分数 | 匹配方式 | 说明 |
|--------|------|----------|------|
| 1 | 100 | 名称完全匹配 | `query == component.name` |
| 2 | 90 | 名称包含匹配 | `query in name` 或 `name in query` |
| 3 | 80 | 关键词完全匹配 | `query` 完全等于某个 keyword |
| 4 | 75 | 别名完全匹配 | `query` 完全等于某个 alias |
| 5 | 60 | 关键词子串匹配 | `query ⊂ keyword` 或 `keyword ⊂ query` |
| 6 | 55 | 别名子串匹配 | 同上，针对 aliases |
| 7 | 40 | 描述包含匹配 | `query in description` |
| 8 | ≤30 | 字符重叠模糊 | 中文字符级 overlap ratio |

搜索结果为 `SearchResult` dataclass，包含 score + match_reason。

调用方（如 SAO 的 store_manager）可多次调用 `search()` 并合并结果，实现多关键词搜索。

### 4.5 CLI

```bash
python -m sao_store_index rebuild              # 重建 index.toml
python -m sao_store_index search "骰子"        # 搜索
python -m sao_store_index list                 # 列出全部
```

CLI 通过 `_find_store_root()` 自动向上查找包含 `skills/` + `experts/` 的目录。

---

## 5. 已实现的 Skill 概览

### 5.1 dice (weight=1)

| 项目 | 说明 |
|------|------|
| 路径 | `skills/sao-skill-dice/` |
| Tools | `roll`（掷骰 NdM±K）、`flip`（抛硬币）、`pick`（随机抽选） |
| 方法论 | 纯函数计算，无外部依赖。`execute()` 通过 dict dispatch 路由到 `_handle_roll/flip/pick` |
| 特色 | Mock-safe import（`try/except` 导入 `BaseSkill`，测试时不需安装 SAO SDK） |
| 安全 | 参数上限校验（`_MAX_DICE=100`, `_MAX_FACES=1000`, `_MAX_FLIP=100`, `_MAX_PICK=50`） |
| 测试 | 28 cases，覆盖参数校验、路由分发、核心逻辑、边界条件 |

### 5.2 programming (weight=8)

| 项目 | 说明 |
|------|------|
| 路径 | `skills/sao-skill-programming/` |
| Tools | `init`、`write_file`、`read_file`、`run`、`push` |
| 方法论 | 重量级 Skill，由 SubAgent 异步管理多轮开发循环。SKILL.toml 有完整 `[skill.instructions]`，定义 SubAgent 工作流 |
| 状态 | SKILL.toml 设计完成，`skill.py` 实现待完善（需配合 SAO SubAgent 框架） |
| 安全 | `bins = ["git"]` gating；路径穿越防护（`_safe_path` 设计） |

### 5.3 reminder (weight=1)

| 项目 | 说明 |
|------|------|
| 路径 | `skills/sao-skill-reminder/` |
| Tools | `set`、`list`、`update`、`cancel` |
| 方法论 | 飞书 Bitable（多维表格）作为存储后端。通过 `lark_oapi` SDK 操作 AppTableRecord |
| 依赖 | `env = ["FEISHU_BITABLE_APP_TOKEN", ...]`, `features = ["feishu"]` |
| 特色 | 多格式时间解析（6 种 datetime 格式）、全异步设计（`async/await`） |

---

## 6. Expert 概览

5 个 Expert，均为纯 TOML 配置：

| Expert | search | temperature | 要点 |
|--------|--------|-------------|------|
| code | false | 0.1 | 编程助手，无需联网 |
| general | false | 0.5 | 默认 fallback |
| search | true | 0.3 | 依赖 `dashscope_search` feature |
| translate | false | 0.1 | 中英互译 + 多语言 |
| weather | true | 0.3 | 依赖 `dashscope_search` feature |

---

## 7. 测试体系

### 7.1 Skill 测试规范

每个 Skill 的 `tests/test_skill.py` 覆盖 5 类场景：

1. **参数校验**: 缺参/空参/非法参数 → 返回 `⚠️` 提示
2. **路由分发**: `execute()` 能路由到所有 tool + 未知 tool 返回警告
3. **核心逻辑**: 纯函数/工具方法的单元测试
4. **成功路径**: mock 外部依赖后的正常流程
5. **安全防护**: 路径穿越、上限校验等

### 7.2 外部依赖隔离

SAO SDK（`sao.*`）、飞书 SDK（`lark_oapi`）等在测试时通过两种方式隔离：

- **`sys.modules.setdefault()` mock**: reminder skill 使用此模式，在 test 文件顶部 mock 掉未安装的包
- **`try/except` import**: dice skill 使用此模式，模块级 fallback 到 stub 类

两种方式的目标相同：**不安装 SAO SDK 也能运行测试**。

### 7.3 LocalIndex 测试

`tests/test_store_index.py` 包含 64 个 cases，覆盖：

- Indexer：扫描 skill/expert、生成 index.toml、字段完整性
- Searcher：8 个评分层级、type 过滤、limit、空查询、fallback 扫描（无 index.toml 时）
- CLI：rebuild / search / list 三个子命令

---

## 8. 开发流程

新 Skill 上线的 6 步流程（详见 `.github/copilot-instructions.md`）：

```
1. 脚手架  →  2. 编码  →  3. 测试  →  4. 注册索引  →  5. 提交  →  6. 验证搜索
                                          ↑                          ↑
                                   python -m sao_store_index    python -m sao_store_index
                                          rebuild                search "{关键词}"
```

步骤 4 和 6 是必须的 — 未注册到 `index.toml` 的组件，SAO 无法通过搜索发现。

---

## 9. 关键设计原则

| 原则 | 体现 |
|------|------|
| **元数据驱动** | tools/examples/instructions 声明在 TOML，不硬编码在 Python 中 |
| **Gating 前置** | `[skill.requires]` 在加载时检查 env/bins/features，不满足直接跳过 |
| **Weight 分层** | 轻量 Skill 同步调用、重量 Skill 交给 SubAgent，避免阻塞主对话 |
| **测试可独立运行** | 通过 mock/stub 隔离 SAO SDK，`pytest` 直接跑无需安装整个 SAO |
| **索引集中化** | 一个 `index.toml` 汇总所有组件元数据，搜索不需要遍历文件系统 |
| **Keywords 必填** | 每个组件必须声明中英文关键词，这是搜索发现的基础 |

---

## 10. 待完成事项

参见 `docs/implementation-plan.md`：

- **T4 / T5**: Memory 系统（ClassLog → 课堂记录技能），尚未启动
- **Programming Skill**: TOML 设计完成，`skill.py` 完整实现待做（详见 `docs/programming-skill.md`）

---

*生成于项目 commit fd75d37 之后，仅作审查参考。*
