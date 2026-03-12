# SAO v2 技能规划

> 最后更新: 2026-03-11 | 技能系统状态: **Phase 1.5 Reminder 已实现，天气已走 Chat Expert，Programming Skill 设计完成**
>
> v2 采用 **双轨技能系统**：TOML 声明式 + Python 代码。
> TOML/Forge/市场技能运行在 Docker 沙箱中；Programming Skill 不用容器，通过 Git 分支隔离 + Rules 行为约束 + SAO 审查保证安全（详见 `docs/programming-skill.md` §12）。
> 天气查询已通过 **Chat Expert** 模式实现（DashScope 联网搜索，详见 `docs/experts.md`）。
>
> **关键设计**：Skill 在 SKILL.toml 中声明数值 `weight`（1~10，根据预估耗时和流程复杂度设定），SAO 据此决定是主 Agent 直调还是分配 SubAgent 盯着执行。
> 1~3 轻量（秒级、单次调用）；4~6 中等；7~10 重量（分钟~小时级、多轮交互）。
> 详见 `docs/programming-skill.md` §6.6。
>
> 本文档记录所有规划中的技能、实现计划和优先级。

---

## 技能总览

| # | 技能名 | 类型 | weight | 优先级 | 计划阶段 | 状态 | 说明 |
|---|---|---|---|---|---|---|---|
| 1 | `weather` | Chat Expert | — | P0 | Phase 1.5 | ✅ 已实现 | 天气查询（DashScope 联网搜索 + 专属 Prompt） |
| 2 | `reminder` | Python 代码 | **1** | P0 | Phase 1.5 | ✅ 已实现 | 定时提醒（Bitable 存储，主 Agent 直调） |
| 3 | `programming` | Python 代码 | **9** | P0 | Phase A~C | ✅ 设计完成 | 编排本地 IDE Agent 编程（SubAgent 盯着执行） |
| 4 | `forge` | 内置 (硬编码) | **8** | P0 | Phase 4 | 待开发 | 技能锻造（Agent 自写技能） |
| 5 | `store_manager` | 内置 (硬编码) | **2** | P1 | Phase 1.5 | 待开发 | 组件商店管理（搜索/安装/卸载/更新/列表） |
| 6 | `stock_monitor` | Python 代码 | **1** | P2 | Phase 4+ | 示例 | A 股股息率监控（Forge 生成示例） |

### 内置工具（非技能，Agent 直接调用）

| 工具 | 计划阶段 | 状态 | 说明 |
|---|---|---|---|
| `memory_store` | Phase 3 | 待开发 | LLM 存储一条记忆 |
| `memory_recall` | Phase 3 | 待开发 | LLM 搜索相关记忆 |
| `memory_forget` | Phase 3 | 待开发 | LLM 删除一条记忆 |

---

## 1. WeatherSkill — 天气查询

> ✅ **已通过 Chat Expert 实现** | DashScope 联网搜索 | 详见 `docs/experts.md`
>
> 天气不再作为独立 Skill，而是通过 Router `chat_mode=weather` 分流到天气专家，
> 使用 DashScope `enable_search=true` 联网获取实时天气，卡片格式输出。
>
> 未来如需更精确的天气数据，可在 Phase 2+ 改为独立 TOML Skill（调用和风 API）。

| 字段 | 值 |
|---|---|
| 名称 | `weather` |
| 类型 | TOML 声明式 (`SKILL.toml` + `weather.py`) |
| 位置 | `~/.sao/skills/weather/` |
| 优先级 | **P0** — Phase 2 首个技能，验证整条 TOML→Sandbox 链路 |

### 示例触发

- `北京天气怎么样`
- `上海今天天气`
- `明天深圳气温多少`

### SKILL.toml 设计

```toml
[skill]
name = "weather"
description = "查询城市天气预报"
version = "1.0.0"
tags = ["生活", "天气"]

[skill.permissions]
network = true
env_vars = ["WEATHER_API_KEY"]

[[tools]]
name = "get_weather"
description = "获取指定城市的天气预报"
kind = "python"
command = "python weather.py --city {city}"

[tools.args.city]
type = "string"
description = "城市名称"
required = true

[tools.args.days]
type = "integer"
description = "预报天数"
required = false
default = 3

[[examples]]
user = "明天北京天气怎么样"
tool = "get_weather"
args = { city = "北京", days = 1 }
```

### 实现方案

- **方案 A**：调用真实天气 API（如和风天气 / OpenWeatherMap），需 `WEATHER_API_KEY`
- **方案 B**：纯 LLM 推理（当季气候参考），零外部依赖，但非实时
- 优先实现方案 A，方案 B 作为无 API key 时的降级

### 验收标准

```
[飞书] 北京天气怎么样
[SAO]  🌤 北京今日天气：晴，12°C~22°C...（从 Docker 容器中执行返回）
```

---

## 2. ReminderSkill — 定时提醒

> ✅ **已实现** (Phase 1.5) | Python 代码技能 | 飞书 Bitable 存储
>
> 当前位置: `sao_skill_reminder` 外部包（源码在 SAO-Store/skills/sao-skill-reminder/），`pip install -e` 安装后作为 Python BaseSkill 直接运行在主进程。
> Phase 2+ 可迁移到 Docker 沙箱中执行。

| 字段 | 值 |
|---|---|
| 名称 | `reminder` |
| 类型 | Python 代码 (`SKILL.toml` + `skill.py`) |
| 位置 | SAO-Store/skills/sao-skill-reminder/ |
| weight | **1**（轻量，主 Agent 直调） |
| 优先级 | **P0** — 高频使用，v1 已验证需求 |
| v2 实现 | `sao_skill_reminder` pip 包，`pip install -e` 安装后 SAO 通过 entry points 自动发现 |

### 示例触发

- `3月10号下午3点提醒我开会`
- `明天早上9点提醒我给老板打电话`
- `查看我的提醒`
- `把开会那个提醒改成8点`
- `取消报名考试的提醒`
- `半小时后提醒我吃药`

### Tools

| Tool | 说明 |
|---|---|
| `set`（默认） | LLM 提取时间+内容 → 存储 → 调度定时任务 |
| `list` | 查询当前用户所有待执行提醒 |
| `update` | LLM 匹配目标提醒 → 更新字段 → 重新调度 |
| `cancel` | LLM 匹配目标提醒 → 删除记录 → 取消定时任务 |

### 架构要点

| 维度 | 说明 |
|---|---|
| 存储 | 飞书 Bitable（多维表格 CRUD） |
| 构造 | `__init__(self, ctx: SkillContext)` — 统一接口，从 ctx 获取 lark_client |
| 入口 | `execute(tool, args, ctx)` — 按 tool 名分发到内部 handler |
| 工具定义 | SKILL.toml `[[tools]]` 声明（SAO 读取后注入 Router prompt） |
| 执行环境 | 主进程内（weight=1，主 Agent 直调） |

### 依赖

- `lark-oapi>=1.3` — 飞书 SDK
- `super-agent-os>=2.0.0` — 提供 BaseSkill / SkillContext
- 环境变量：`FEISHU_BITABLE_APP_TOKEN`、`FEISHU_BITABLE_REMINDER_TABLE_ID`

### 验收标准

```
[飞书] 明天上午10点提醒我开会
[SAO]  ✅ 已设置提醒：明天 10:00 - 开会

[飞书] 查看我的提醒
[SAO]  📋 你的提醒：
       1. 明天 10:00 - 开会
```

---

## 3. Forge — 技能锻造（Agent 自写技能）

> Phase 4 交付物 · 内置技能（硬编码） · Agent 自写技能
>
> **Forge = 锻造**。让 SAO 根据用户的自然语言需求，自动生成完整的技能代码（SKILL.toml + main.py），
> 在 Docker 沙箱中测试通过后，经用户审批部署上线。这是 SAO 的核心自进化能力。
> 简单技能（<50 行）由 LLM 直接生成；复杂技能委派给 Programming Skill 在 IDE 中开发。

| 字段 | 值 |
|---|---|
| 名称 | `forge` |
| 类型 | 内置技能（`sao/skills/forge.py`，非 TOML） |
| 优先级 | **P0** — SAO 的核心差异化能力 |

### 示例触发

- `帮我写一个查询A股股息率的技能`
- `创建一个翻译技能`
- `开发一个查快递的功能`

### Tools

| Tool | 说明 |
|---|---|
| `create`（默认） | LLM 生成 `SKILL.toml` + `main.py` → 沙箱测试 → 发飞书审批卡片 |
| `deploy` | 用户审批通过后，写入 `~/.sao/skills/{name}/` → Registry 热加载 |

### 流程

```
用户请求 → Router → {"route":"skill", "skill":"forge", "tool":"create", ...}
    │
    ▼
1. LLM 生成 SKILL.toml + main.py (+ requirements.txt)
2. 写入临时目录
3. Docker 沙箱内试运行
4. 发飞书审批卡片（展示代码 + 测试结果）
    │
    ├─ 用户 [✅ 部署] → 写入 skills 目录 → Registry 热加载
    └─ 用户 [❌ 放弃] → 清理临时文件
```

### 复杂技能走 SubAgent

简单技能（<50行）由 Forge 直接生成；复杂技能 Router 会路由到 `delegate`，SubAgent 后台调用 Forge 完成多轮 编写→测试→修复 循环。

**Forge 生成的技能放在 SAO-Store**：复杂技能由 Forge 在 `SAO-Store/skills/` 中新建 `sao-skill-{name}/` 子目录，委派给 Programming Skill 在 IDE 中开发，完成后 push 到 GitHub。

### 验收标准

```
[飞书] 帮我写一个查询 A 股股息率前10的技能
[SAO]  🔨 正在锻造技能...
       ┌─ stock_dividend ──────────────────┐
       │ SKILL.toml: 已生成                 │
       │ main.py: 62 行                     │
       │ 沙箱测试: ✅ 通过（返回10条数据）    │
       │                                    │
       │ [📄 查看代码] [✅ 部署] [❌ 放弃]    │
       └────────────────────────────────────┘
```

---

## 4. StoreManagerSkill — 组件商店管理

> Phase 1.5 P1 · 内置技能（硬编码） · SAO-Store 统一管理 技能 + 专家

| 字段 | 值 |
|---|---|
| 名称 | `store_manager` |
| 类型 | 内置技能（`sao/skills/store_manager.py`，非 TOML — 它是安装一切的引导机制） |
| 位置 | 主仓库 `Super-Agent-OS`，**不**放在 SAO-Store（它是基础设施） |
| 优先级 | **P1** |

### 为什么是内置？

StoreManager 是安装其他 Skill / Expert 的入口，自身不能通过 Store 安装——必须内置于 SAO 主程序。

### 示例触发

- `帮我搜索天气相关的技能`
- `安装 sao-skill-weather`
- `安装天气专家`
- `卸载天气技能`
- `更新 Store`
- `查看已安装的组件`

### Tools

| Tool | 说明 |
|---|---|
| `search`（默认） | 在 SAO-Store 中搜索可用的技能和专家 |
| `install` | 安装技能（`pip install -e`）或专家（复制 TOML 到 `~/.sao/experts/`） + 热注册 |
| `uninstall` | 卸载技能（`pip uninstall`）或专家（删除 TOML） + 从 Registry 注销 |
| `update` | `git pull` 拉取 SAO-Store 最新版本 |
| `list` | 列出已安装的技能和专家 |

### 架构设计

```
用户: "安装提醒技能"
    │
    ▼
Router → {"route":"skill", "skill":"store_manager", "tool":"install", "args":{"query":"提醒"}}
    │
    ▼
StoreManager.execute("install", {"query": "提醒"})
    │
    ├─ 1. 在 SAO-Store/skills/ 中匹配 → sao-skill-reminder
    ├─ 2. subprocess: pip install -e SAO-Store/skills/sao-skill-reminder/
    ├─ 3. 动态 import → 获取 Skill 类
    └─ 4. agent.register_skill() 热注册 → Router prompt 更新
    │
    ▼
回复: "✅ 已安装技能: reminder (v1.0.0)"
```

### 组件类型处理

| 组件类型 | 安装方式 | 卸载方式 | 存储位置 |
|---|---|---|---|
| **Skill** (pip 包) | `pip install -e SAO-Store/skills/{name}/` | `pip uninstall {package}` | SAO-Store/skills/ |
| **Expert** (TOML) | 复制 `{name}.toml` 到 `~/.sao/experts/` | 删除 `~/.sao/experts/{name}.toml` | SAO-Store/experts/ |

### SAO-Store 仓库结构

```
# GitHub: git@github.com:Selene1225/SAO-Store.git
# 本地: C:\Users\yiliu4\code\SAO-Store
SAO-Store/
├── skills/                    # ── 技能（pip 包）──
│   ├── sao-skill-reminder/    # 每个技能一个子目录
│   │   ├── SKILL.toml
│   │   ├── pyproject.toml     # pip install -e skills/sao-skill-reminder/
│   │   └── sao_skill_reminder/
│   │       ├── __init__.py
│   │       └── skill.py
│   └── sao-skill-{name}/      # 后续新增技能
└── experts/                   # ── 专家（TOML 配置）──
    ├── weather.toml
    ├── search.toml
    ├── code.toml
    ├── translate.toml
    └── general.toml
```

### 设计要点

- **数据源**：本地 SAO-Store 仓库（`git pull` 同步），不依赖 PyPI / GitHub API
- **包命名约定**：技能 `sao-skill-*` 子目录 + `SKILL.toml`；专家 `{name}.toml`
- **热加载**：安装后立即注册到 Agent Skill Registry / Expert 注册表，无需重启
- **幂等安装**：重复安装同名组件不报错，只提示已安装
- **无条件注册**：StoreManager 是核心基础设施，启动时始终加载（不像 Reminder 需 Bitable token）
- **安全约束**：仅从本地受信 SAO-Store 仓库安装，不从任意 URL 安装

---

## 5. 用户自创技能（Forge 生成示例）

以下技能不是预置的，而是用户通过 Forge 或 SubAgent 动态创建的示例，展示 SAO 的自进化能力：

### 5.1 stock_monitor — A 股股息率监控

> 设计文档中的示例技能，由 SubAgent 后台开发

```
用户: "帮我开发一个 A 股股息率监控技能"
SAO:  收到，正在后台开发中... (task-id: abc123)

--- 后台 SubAgent 自动完成 ---
1. 分析需求 → 设计 SKILL.toml 接口
2. 编写 main.py（调用 akshare API）
3. 沙箱测试（返回10条数据, 2.3s）
4. 自我审查代码安全性和质量

SAO:  ✅ 后台任务完成 (task-id: abc123)
      📦 技能: stock_dividend | 测试: ✅ | [部署] [放弃]
```

### 5.2 更多可能的自创技能

| 技能 | 触发示例 | 说明 |
|---|---|---|
| 翻译 | `帮我写一个翻译技能` | 调用翻译 API |
| 快递查询 | `开发一个查快递的功能` | 调用快递100 API |
| 汇率换算 | `帮我写个汇率查询` | 实时汇率 API |
| 新闻摘要 | `创建一个新闻摘要技能` | 抓取+LLM 总结 |

---

## 斜杠命令规划

> 以 `/` 开头的消息由 Pre-Router 直接分发，不经 LLM。

| 命令 | 计划阶段 | 状态 | 说明 |
|---|---|---|---|
| `/help` | Phase 1 | ✅ 已实现 | 显示帮助信息 |
| `/status` | Phase 1 | ✅ 已实现 | 系统运行状态 |
| `/skills` | Phase 1 | ✅ 已实现 | 已加载技能列表 |
| `/new` | Phase 1 | ✅ 已实现 | 重置对话历史 |
| `/model <name>` | Phase 6 | 待开发 | 切换主模型 |
| `/doctor` | Phase 5 | 待开发 | 系统自检 |
| `/memory` | Phase 3 | 待开发 | 查看长期记忆 |
| `/compact` | Phase 3 | 待开发 | 压缩对话历史 |
| `/cost` | Phase 5 | 待开发 | Token 成本统计 |
| `/tasks` | Phase 5 | 待开发 | 列出后台任务 |
| `/cancel <id>` | Phase 5 | 待开发 | 取消后台任务 |
| `/secrets set` | Phase 3 | 待开发 | 安全存储凭证 |
| `/secrets list` | Phase 3 | 待开发 | 查看已存储凭证 |
| `/audit` | Phase 3 | 待开发 | 执行审计日志 |
| `/estop` | Phase 3 | 待开发 | 紧急制动 |
| `/store` | Phase 1.5 | 待开发 | 组件商店 CLI |

---

## OpenClaw 生态技能评估

> 评估日期: 2026-03-11 | 来源: [ClawHub](https://clawhub.ai/) (19,014 skills)
>
> 以下技能来自 OpenClaw 生态，评估其安全性、实用性和潜在问题，决定是否适合集成到 SAO。

### 评估总览

| # | 技能 | Stars | 安全评级 | 依赖 | SAO 实用性 | 建议 |
|---|---|---|---|---|---|---|
| 1 | self-improving-agent | 1.6k | ✅ Benign | 无 | **高** | ⭐ 推荐借鉴模式 |
| 2 | proactive-agent | 471 | ⚠️ Suspicious | 无 | **高（有风险）** | 借鉴架构，慎用指令 |
| 3 | find-skills | 623 | ⚠️ Suspicious | npx/Node | **中** | 需配合 vetter 使用 |
| 4 | summarize | 460 | ✅ Benign | CLI + API keys | **高** | SAO 可原生实现 |
| 5 | skill-vetter | 204 | ✅ Benign | 无 | **中高** | ⭐ 推荐借鉴清单 |
| 6 | playwright-mcp | 18.3k | ✅ Benign | Node + Playwright | **高** | Python 直接集成更佳 |
| 7 | xiaohongshu-mcp | 13.4k | ⚠️ Suspicious | Go 二进制 + Python | **中** | ⛔ 安全风险高 |
| 8 | agent-browser | 95.3k | ✅/⚠️ 混合 | Node + Rust CLI | **高** | 功能强，可选方案 |

---

### 1. self-improving-agent ⭐

| 维度 | 详情 |
|---|---|
| 作者 | @pskoett · v3.0.0 · MIT-0 |
| 功能 | Agent 自动记录学习成果和错误到 `.learnings/` 目录，逐步提升为 AGENTS.md/SOUL.md 等规则文件。含 shell hook 自动检测错误 |
| 依赖 | 无（纯指令 + shell hooks） |
| 安全 | VirusTotal **Benign** · OpenClaw **Benign** (高置信度) |
| **对 SAO 的价值** | **高** — 自我改进是 PA 核心能力。错误日志→学习→规则提升的模式可直接移植到 SAO 的 memory 架构 |
| **建议** | ✅ **推荐借鉴模式**，将 `.learnings/` 模式融入 SAO 的 Phase 3 长期记忆系统 |

### 2. proactive-agent ⚠️

| 维度 | 详情 |
|---|---|
| 作者 | @halthelobster · v3.1.0 · MIT-0 (Hal Stack 系列) |
| 功能 | WAL（Write-Ahead Log）协议、工作缓冲区、压缩恢复、自主 Cron、3 层记忆架构、心跳系统、反向提示 |
| 依赖 | 无（纯指令） |
| 安全 | VirusTotal **Benign** · OpenClaw **Suspicious** (中置信度) — 内部指令矛盾："Don't ask permission. Just do it." vs "Nothing external without approval." |
| **安全隐患** | 🔴 指令鼓励 Agent 自主行动而不征求用户同意，与 SAO 人类确认设计原则冲突 |
| **对 SAO 的价值** | **高（需改造）** — WAL 崩溃恢复、心跳、3 层记忆概念很有价值，但"自主执行"指令需过滤 |
| **建议** | ⚠️ 借鉴 WAL/心跳/定时任务架构，**删除**所有绕过用户确认的指令 |

### 3. find-skills ⚠️

| 维度 | 详情 |
|---|---|
| 作者 | @JimLiuxinghai · v0.1.0 · MIT-0 |
| 功能 | 元技能，让 Agent 运行时从 ClawHub 搜索并安装新技能（`npx skills find/add`） |
| 依赖 | 需要 `npx` / Node.js |
| 安全 | ⚠️ Suspicious — "鼓励执行第三方代码 via npx，-y 跳过提示全局安装" |
| **安全隐患** | 🔴 自动安装未审核的第三方代码，v0.1.0 早期版本，安全模型薄弱 |
| **对 SAO 的价值** | **中** — 自扩展概念强大，但 SAO 已有 Marketplace 规划（Phase 6），可原生实现更安全的版本 |
| **建议** | ❌ 不直接使用。SAO 的 Marketplace 设计已覆盖此功能，且有安全审计 |

### 4. summarize ✅

| 维度 | 详情 |
|---|---|
| 作者 | @steipete (OpenClaw 创始人官方技能) · v1.0.0 · MIT-0 |
| 功能 | 多模态摘要：网页 URL、PDF、图片、音频、YouTube 字幕 → 浓缩摘要 |
| 依赖 | **重**：需要 `summarize` CLI (`brew/npm` 安装)，需要 OpenAI/Anthropic/Gemini API key |
| 安全 | ✅ Benign (高置信度) |
| **问题** | 外部 CLI 依赖 + 额外 API key，SAO 已有自己的 LLM，不需要额外 key |
| **对 SAO 的价值** | **高（功能价值高）** — 多模态摘要是 PA 核心能力，但实现方式不适合 SAO |
| **建议** | ✅ 功能值得做，但 SAO 应原生实现（用 Qwen 做摘要），不依赖外部 CLI |

### 5. skill-vetter ✅

| 维度 | 详情 |
|---|---|
| 作者 | @spclaudehome · v1.0.0 · MIT-0 |
| 功能 | 4 步安全审查协议：(1) 来源检查 (2) 代码审查（红旗清单） (3) 权限范围分析 (4) 风险分级 (LOW/MEDIUM/HIGH/EXTREME) |
| 依赖 | 无（纯指令） |
| 安全 | ✅ Benign (高置信度) |
| **对 SAO 的价值** | **中高** — 红旗清单（过度权限、混淆代码、凭证窃取等）可直接复用到 SAO 的插件安全模型 |
| **建议** | ⭐ **推荐借鉴清单**，作为 SAO Marketplace 安全审查的参考框架 |

### 6. playwright-mcp ✅

| 维度 | 详情 |
|---|---|
| 作者 | @Spiceman161 · v1.0.0 · MIT-0 |
| 功能 | 通过 MCP 协议进行浏览器自动化：导航、点击、填表、截图、执行 JS。支持 Chromium/Firefox/WebKit，可配置域名白名单和沙箱 |
| 依赖 | `npx`、Node.js、`@playwright/mcp`、Chromium |
| 安全 | ✅ Benign — 内建安全：域名白名单、来源屏蔽、沙箱、Service Worker 拦截 |
| **对 SAO 的价值** | **高** — 浏览器自动化是 PA 必备能力。上游 Playwright (微软维护，6.3M 周下载) 非常成熟 |
| **建议** | ✅ 功能需要，但 SAO 的 Python 技术栈建议直接用 **`playwright` Python 库**，而非绕道 Node.js 包装层 |

### 7. xiaohongshu-mcp ⛔

| 维度 | 详情 |
|---|---|
| 作者 | @Borye · v1.0.0 · MIT-0 · 上游 xpzouying/xiaohongshu-mcp (8.4k stars) |
| 功能 | 小红书完整操作：发布图文/视频、搜索笔记/趋势、分析评论、管理用户资料。需手机扫码登录 |
| 依赖 | **非常重**：Go 二进制文件 (xiaohongshu-mcp + xiaohongshu-login)、Python、本地 MCP 服务 localhost:18060 |
| 安全 | ⚠️ VirusTotal **Suspicious** · OpenClaw **Benign** (中置信度) |
| **安全隐患** | 🔴🔴🔴 **严重**：(1) 需运行第三方闭源 Go 二进制 → 无法审计源码 (2) 二进制控制你的小红书账号会话 (3) 基于逆向工程 API → 随时可能被封号 (4) 账号凭据完全暴露给 Go 进程 |
| **对 SAO 的价值** | **中** — 仅当需管理中国社交媒体时有用 |
| **建议** | ⛔ **不推荐使用**。闭源二进制 + 账号控制 = 高风险。如需小红书功能，应直接调用 xiaohongshu-mcp server API 并自行审计 |

### 8. agent-browser (代理浏览器) ✅

| 维度 | 详情 |
|---|---|
| 作者 | @TheSethRose · v0.2.0 · MIT-0 · 上游 vercel-labs/agent-browser (Vercel 维护) |
| 功能 | Rust 无头浏览器 CLI：导航、可访问性树快照 (ref 引用交互)、截图、PDF、录屏、Cookie 管理、网络拦截、多标签页、会话状态持久化 |
| 依赖 | Node.js、`agent-browser` CLI (`npm install -g`) |
| 安全 | VirusTotal **Suspicious** (自动化模式误报) · OpenClaw **Benign** (高置信度) |
| **对 SAO 的价值** | **高** — 比 playwright-mcp 更适合 AI Agent：ref 引用交互模型（快照→获取引用→按引用操作），会话持久化，Vercel 团队维护 |
| **建议** | ✅ 备选浏览器方案。与 playwright 二选一，agent-browser 的 ref 模型更适合 Agent，但多一层 Node.js 依赖 |

---

### 关键结论

**1. 借鉴模式，不借鉴代码**
> self-improving-agent、proactive-agent、skill-vetter 都是纯指令技能。价值在于设计模式（错误日志→学习提升、WAL 恢复、安全审查清单），应移植到 SAO 的 Python 架构中。

**2. 浏览器自动化：Python 原生优先**
> playwright-mcp 和 agent-browser 都是 Node.js 包装。SAO 是 Python 技术栈，建议直接用 `playwright` Python 库或 `browser-use` Python 库，减少依赖层。

**3. 安全红线**
> - 小红书 MCP：闭源 Go 二进制 + 账号控制 → **⛔ 不使用**
> - find-skills：自动安装未审核代码 → **❌ SAO Marketplace 已覆盖**
> - proactive-agent：绕过用户确认 → **需删除危险指令后再借鉴**

**4. SAO 原生实现优先列表**
> | 能力 | 来源参考 | SAO 实现方式 |
> |---|---|---|
> | 自我改进 | self-improving-agent | Phase 3 长期记忆 + 学习日志 |
> | 多模态摘要 | summarize | Qwen 原生实现 |
> | 浏览器自动化 | playwright / agent-browser | playwright Python 库 |
> | 插件安全审查 | skill-vetter | Marketplace 安全模块 |
> | 定时主动任务 | proactive-agent | Phase 5 后台任务 + Cron |

---

## 技能系统架构

### 发现与注册

```
启动时:
  ~/.sao/skills/          扫描本地技能的 SKILL.toml
  pip packages            扫描已安装的 sao-skill-* 包
       │
       ▼
  Skill Loader            解析 TOML → SkillManifest
       │
       ▼
  Skill Registry          注册到全局表 → 注入 Router prompt
```

### 执行流程（weight 决定调用路径）

```
Router → {"route":"skill", "skill":"xxx", "tool":"...", "args":{...}}
    │
    ▼
Skill Registry            查找 SkillManifest → 读取 weight (1~10)
    │
    ├── weight < 5（轻量，主 Agent 直调）
    │     │
    │     ▼
    │   skill.execute(tool, args, ctx)
    │     │
    │     ▼
    │   返回结果给用户（同步，秒级）
    │
    └── weight >= 5（重量，派 SubAgent 盯着）
          │
          ▼
        SubAgent Manager → 创建 SubAgent（员工）
          │
          ├─ 立即回复飞书: "🔧 任务已创建 (task-id: xxx)"
          │
          └─ SubAgent 后台异步执行:
               1. skill.execute(tool, args, ctx)
               2. 监控进度 / 多轮交互循环
               3. 完成后向主 Agent (CEO) 汇报
               4. 主 Agent 在飞书通知用户
```

> **主 Agent = CEO**：接消息、路由、派活、汇报飞书。
> **SubAgent = 员工**：盯着 heavy Skill 执行，跟 Skill 多轮对话（测试失败→修复→重测），完成后向 CEO 汇报。
> **Skill = 工具/能力**：纯执行逻辑，不管调度和通知。Skill 在 SAO-Store 开发，SAO 主仓库 `pip install -e` 安装后使用。

### 技能目录结构

**本地技能**（自创 / Forge 生成）：

```
~/.sao/skills/
├── stock_monitor/            # Forge/SubAgent 自创技能
│   ├── SKILL.toml
│   ├── main.py
│   └── requirements.txt
└── my_custom_skill/          # 用户自创技能
    ├── SKILL.toml
    └── main.py
```

**可发布组件**（SAO-Store 仓库）：

```
# 统一组件仓库: git@github.com:Selene1225/SAO-Store.git
# 本地路径: C:\Users\yiliu4\code\SAO-Store
SAO-Store/
├── skills/                    # ── 技能（pip 包）──
│   ├── sao-skill-reminder/    # pip install -e skills/sao-skill-reminder/
│   │   ├── SKILL.toml
│   │   ├── pyproject.toml
│   │   └── sao_skill_reminder/
│   │       ├── __init__.py
│   │       └── skill.py
│   └── sao-skill-{name}/      # 后续新增技能
│       └── ...
└── experts/                   # ── 专家（TOML 配置）──
    ├── weather.toml
    ├── search.toml
    └── ...

# 安装方式
pip install -e SAO-Store/skills/sao-skill-reminder          # 技能：本地开发
pip install "sao-skill-reminder @ git+https://github.com/Selene1225/SAO-Store.git#subdirectory=skills/sao-skill-reminder"  # 技能：GitHub
sao expert install SAO-Store/experts/weather.toml           # 专家：复制 TOML
```

好处：
- 技能 + 专家在一个仓库统一管理
- Skill 是独立 pip 包，按需安装；Expert 是 TOML 配置，复制即用
- 与 Marketplace `sao-skill-*` / `sao-expert-*` 命名约定天然兼容
