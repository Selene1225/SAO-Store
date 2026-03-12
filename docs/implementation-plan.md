# SAO 实现计划

> 日期: 2026-03-11 | 状态: 规划中
>
> 基于 `docs/experts.md`、`docs/skills.md`、`docs/programming-skill.md`、`docs/rules-reference.md` 整理。

---

## 当前状态（已完成）

| 组件 | 类型 | 状态 | 位置 |
|---|---|---|---|
| general Expert | TOML 配置 | ✅ 已实现 | `experts/general.toml` |
| weather Expert | TOML 配置 | ✅ 已实现 | `experts/weather.toml` |
| code Expert | TOML 配置 | ✅ 已实现 | `experts/code.toml` |
| translate Expert | TOML 配置 | ✅ 已实现 | `experts/translate.toml` |
| search Expert | TOML 配置 | ✅ 已实现 | `experts/search.toml` |
| Reminder Skill | Python 代码 | ✅ 已实现 | `skills/sao-skill-reminder/` |
| Programming Skill | 设计文档 | ✅ 设计完成 | `docs/programming-skill.md` |

---

## 架构要点

### 1. Programming Skill = 1 个 Skill + 多个 IDE Adapter

编程不是每个 IDE 一个 Skill，而是 **1 个 ProgrammingSkill + 多个 Adapter**。用户不关心用什么 IDE，只关心任务完成。IDE 的选择通过 `~/.sao/machines.yaml` 中的 `ide.name` 配置决定。

### 0. Skill 声明 weight，SAO 决定调度方式

Skill 在 SKILL.toml 中声明数值 `weight`（1~10），根据预估耗时和流程复杂度设定。SAO 据此决定：

| weight | 调用方式 | 示例 |
|---|---|---|
| **1~3** | 主 Agent (CEO) 同步直调 `skill.execute()` | reminder (1), store_manager (2) |
| **4~6** | 视情况决定 | 浏览器自动化等 |
| **7~10** | 主 Agent 派 SubAgent (员工) 异步盯着执行 | programming (9), forge (8) |

SAO 主仓库 `BaseSkill` 根据 weight 提供 `requires_subagent` 属性（阈值默认 5）：

```python
class BaseSkill:
    @property
    def requires_subagent(self) -> bool:
        return getattr(self, '_weight', 1) >= SUBAGENT_THRESHOLD
```

> Skill 本身不关心调度——它只提供 `execute()` 接口，weight 告诉 SAO 怎么调它。

详见 `docs/programming-skill.md` §6.6。

```
            ProgrammingSkill（唯一入口）
                    │
        machines.yaml 的 ide.name 决定
                    │
        ┌───────┼───────┬──────────┐
        ▼       ▼       ▼          ▼
    VSCode   Antigravity Claude    Aider
    Adapter   Adapter   Code       Adapter
       │        │       Adapter       │
       ▼        ▼         ▼          ▼
    Copilot   Gemini    Claude     Aider CLI
```

### 2. Workspace 配置：开发者 vs 普通用户

- **SAO 开发者**：在 `machines.yaml` 中配置 `sao` + `sao-store` 两个 workspace，可以让 SAO 在 SAO-Store 中直接开发新 Skill/Expert
- **普通用户**：只配自己的项目 workspace，通过 StoreManager 从 GitHub 安装组件

### 3. Forge = 技能锻造

Forge（锻造）让 SAO 自己写技能：用户用自然语言描述需求 → LLM 自动生成 SKILL.toml + main.py → 沙箱测试 → 人工审批部署。简单技能（<50 行）LLM 直接生成，复杂技能委派给 Programming Skill 在 IDE 中开发。

---

## 实现路线

### Phase 1: StoreManager Skill（P1，基础设施）

> 安装一切组件的入口，位于 **SAO 主仓库** (`Super-Agent-OS`)，不在 SAO-Store。

| 步骤 | 内容 | 说明 |
|---|---|---|
| 1 | `sao/skills/store_manager.py` | 内置技能，非 TOML |
| 2 | 5 个 tool | `search` / `install` / `uninstall` / `update` / `list` |
| 3 | Skill 安装 | `pip install -e SAO-Store/skills/{name}/` |
| 4 | Expert 安装 | 复制 TOML 到 `~/.sao/experts/` |
| 5 | 热加载 | 安装后立即注册到 Registry，无需重启 |
| 6 | `/store` 斜杠命令 | Pre-Router 直接分发 |

**依赖**: SAO 主仓库的 Skill Registry 已有基础。

**验收标准**:
```
[飞书] 安装提醒技能
[SAO]  ✅ 已安装技能: reminder (v1.0.0)
```

---

### Phase 2: Programming Skill — MVP（P0，Phase A）

> 核心差异化能力。在 **SAO 主仓库** 实现。详见 `docs/programming-skill.md`。

| 步骤 | 文件 | 说明 |
|---|---|---|
| 1 | `sao/skills/programming/models.py` | `CodingTask`, `CodingResult`, `MachineConfig` 数据模型 |
| 2 | `sao/skills/programming/config.py` | 加载 `~/.sao/machines.yaml`，解析项目→机器映射 |
| 3 | `sao/skills/programming/connector.py` | `LocalConnector`（`asyncio.create_subprocess_shell`） |
| 4 | `sao/skills/programming/adapters/base.py` | `IDEAdapter` 抽象基类（6 个抽象方法） |
| 5 | `sao/skills/programming/adapters/cli_agent.py` | 通用 CLI Agent 适配器（Claude Code / Aider / Codex） |
| 6 | `sao/skills/programming/runner.py` | `ProgrammingRunner`（SubAgent 执行器，编码→测试循环） |
| 7 | `sao/skills/programming/skill.py` | `ProgrammingSkill` 主入口 + Router 注册 |
| 8 | `~/.sao/rules/default.md` | 默认开发规则模板（Phase 0~5 + 反模式） |
| 9 | `~/.sao/rules/quick.md` | 精简规则（小任务，跳过文档阶段） |
| 10 | `~/.sao/rules/sao-project.md` | SAO 项目定制规则（项目快照 + 编码约定） |

**文件结构**:
```
sao/skills/programming/
├── __init__.py
├── skill.py              # ProgrammingSkill 主入口
├── models.py             # CodingTask, CodingResult, MachineConfig
├── config.py             # 加载 ~/.sao/machines.yaml
├── runner.py             # ProgrammingRunner (SubAgent 执行器)
├── connector.py          # LocalConnector
└── adapters/
    ├── __init__.py       # ADAPTERS 注册表
    ├── base.py           # IDEAdapter 抽象基类
    └── cli_agent.py      # 通用 CLI Agent Adapter
```

**验收标准**:
```
[飞书] 帮我在 sao 项目里加个 health check 接口
[SAO]  🔧 编程任务已创建 (task-id: p-xxx)
       📍 项目: sao | IDE: VS Code + Copilot
       ⏳ 正在编码中...
[SAO]  ✅ 编程完成 | 📊 2 files, +30 lines | 🧪 tests passed ✅
```

---

### Phase 3: Programming Skill — 多 IDE + 进度推送（Phase B）

| 步骤 | 文件 | 说明 |
|---|---|---|
| 1 | `adapters/vscode.py` | VS Code + Copilot Adapter（sao-vscode-bridge 扩展） |
| 2 | `adapters/antigravity.py` | Antigravity Adapter |
| 3 | 飞书交互卡片 | 任务创建 / 进度更新 / 完成通知 / 失败通知 |
| 4 | 两层规则架构 | `xxx.slim.md`（prompt 注入）+ `xxx.md`（写入 AGENTS.md） |

---

### Phase 4: Programming Skill — 高级功能（Phase C）

| 步骤 | 说明 |
|---|---|
| 1 | 自动修复循环（测试失败 → 修复 → 重测，`MAX_FIX_ATTEMPTS=3`） |
| 2 | Git 操作自动化（创建 `sao/task-{id}` 分支 / commit / push） |
| 3 | SAO Diff 审查（scope check + 安全扫描 + 敏感内容检测） |
| 4 | 多任务并行（同时在不同项目上编程） |

---

### Phase 5: Forge Skill（P0，依赖 Phase 2）

> Agent 自写技能。在 **SAO 主仓库** 实现。

| 步骤 | 说明 |
|---|---|
| 1 | `sao/skills/forge.py`（内置技能） |
| 2 | `create` tool — LLM 生成 SKILL.toml + main.py → Docker 沙箱测试 → 飞书审批卡片 |
| 3 | `deploy` tool — 审批通过 → 写入 `~/.sao/skills/` 或 SAO-Store → Registry 热加载 |
| 4 | 复杂技能（>50 行）委派 Programming Skill 在 IDE 中开发 |

**验收标准**:
```
[飞书] 帮我写一个查询 A 股股息率前10的技能
[SAO]  🔨 正在锻造技能...
       [📄 查看代码] [✅ 部署] [❌ 放弃]
```

---

### Phase 6: Memory 系统

| 步骤 | 说明 |
|---|---|
| 1 | `memory_store` / `memory_recall` / `memory_forget` 内置工具 |
| 2 | 借鉴 self-improving-agent 的学习日志 → 规则提升模式 |
| 3 | `/memory` `/compact` 斜杠命令 |
| 4 | 3 层记忆架构（短期对话 / 中期会话摘要 / 长期知识库） |

---

## 执行顺序与依赖关系

```
Phase 1: StoreManager ──────────────────────────────┐
                                                     │ (可并行，不同仓库)
Phase 2: Programming Skill MVP ─────────────────────┤
    │                                                │
    ▼                                                │
Phase 3: 多 IDE + 进度推送                            │
    │                                                │
    ▼                                                │
Phase 4: 高级功能（自动修复/Git/审查）                  │
    │                                                │
    ▼                                                │
Phase 5: Forge（依赖 Programming Skill + 沙箱）  ◄────┘
    │
    ▼
Phase 6: Memory 系统
```

**最高优先级**: Phase 2（Programming Skill MVP）— SAO 的核心差异化能力，设计文档已完整。

**可并行**: Phase 1（StoreManager）与 Phase 2 在不同仓库，可同时推进。

---

## 各 Phase 预估工作量

| Phase | 预估 | 核心产出 |
|---|---|---|
| Phase 1 | 2-3 天 | `store_manager.py` + 5 个 tool |
| Phase 2 | 5-7 天 | 8 个文件 + 3 个 Rules 模板 |
| Phase 3 | 3-4 天 | 2 个 Adapter + 飞书卡片 |
| Phase 4 | 3-4 天 | 修复循环 + Git + Diff 审查 |
| Phase 5 | 4-5 天 | Forge + 沙箱 + 审批流 |
| Phase 6 | 5-7 天 | 3 层记忆 + 斜杠命令 |

---

## 涉及的仓库

| 仓库 | 内容 |
|---|---|
| **SAO-Store** (本仓库) | Expert TOML 配置 + Skill pip 包 + 文档 |
| **Super-Agent-OS** (主仓库) | StoreManager / Programming Skill / Forge / Memory 等核心代码 |

Phase 1~6 的代码实现均在 **Super-Agent-OS** 主仓库。SAO-Store 仓库负责存放可共享的组件（Expert TOML + Skill 包）和设计文档。
