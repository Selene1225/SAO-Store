# SAO-Store 实现计划

> 日期: 2026-03-11 | 状态: 规划中
>
> SAO-Store 仓库自身的改进计划。SAO 主仓库的实现计划见 `docs/sao-runtime-improvements.md`。

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
| Programming Skill | Python 代码 | ✅ 已实现 | `skills/sao-skill-programming/` |

---

## 待办任务

> 借鉴 OpenClaw 设计，配合 SAO 主仓库的运行时改进。
> SAO 侧改动详见 `docs/sao-runtime-improvements.md`。

### T1: SKILL.toml Gating 字段增强（P0） ✅ 已完成

给 `[skill.requires]` 增加标准化的环境依赖声明，SAO 加载时据此决定是否跳过。

**改动**：更新所有已有 SKILL.toml + 更新 `sao-integration-guide.md` 规范。

```toml
# SKILL.toml — [skill.requires] 增强
[skill.requires]
sao = ">=2.0.0"
env = ["FEISHU_BITABLE_APP_TOKEN", "FEISHU_BITABLE_REMINDER_TABLE_ID"]  # 必需环境变量
bins = []                    # 必需的外部命令（PATH 上）
features = ["feishu"]        # SAO 功能开关（对应 config.toml [features]）
```

**涉及文件**：
| 文件 | 改动 |
|---|---|
| `skills/sao-skill-reminder/SKILL.toml` | `[skill.requires]` 增加 `env` / `bins` / `features` |
| `docs/sao-integration-guide.md` | §4 SKILL.toml 规范增加 gating 字段说明 |
| 后续新 Skill 的 SKILL.toml | 均须声明 requires |

预估：0.5 小时。

---

### T2: Expert TOML Gating 字段（P1） ✅ 已完成

给 Expert TOML 增加可选的 `[expert.requires]` 段，SAO 可据此跳过不满足条件的 Expert。

```toml
# experts/weather.toml — 增加 requires
[expert]
name = "weather"
# ... 现有字段 ...

[expert.requires]               # 可选
features = ["dashscope_search"]  # 天气依赖联网搜索
```

**涉及文件**：
| 文件 | 改动 |
|---|---|
| `experts/search.toml` | 增加 `requires.features = ["dashscope_search"]` |
| `experts/weather.toml` | 增加 `requires.features = ["dashscope_search"]` |
| `docs/sao-integration-guide.md` | §5 Expert 规范增加 requires 说明 |

预估：0.5 小时。

---

### T3: Token 预算友好 — 精简 description 和 examples（P2） ✅ 已完成

审查所有 Skill/Expert 的 description 和 examples，确保精简、不浪费 Router prompt token。

**原则**：
- description 控制在 30 字以内
- examples 不超过 4 个（最具代表性的）
- 避免 tool description 重复 skill description 的信息

预估：1 小时。

---

### T4: self-improve Skill 框架（Phase 6）

开发 `sao-skill-self-improve`，参考 OpenClaw 的 [self-improving-agent](https://clawhub.ai/pskoett/self-improving-agent)。

```
skills/sao-skill-self-improve/
├── SKILL.toml              # weight=2（轻量，主 Agent 直调）
├── pyproject.toml
└── sao_skill_self_improve/
    ├── __init__.py
    └── skill.py            # tools: log_learning / log_error / review / promote
```

**tools**：
| tool | 说明 |
|---|---|
| `log_learning` | 记录纠正/知识/最佳实践到 `~/.sao/memory/learnings/` |
| `log_error` | 记录错误到学习日志 |
| `review` | 查看待处理的学习条目 |
| `promote` | 将反复出现的学习提升为系统规则 |

**依赖**: SAO 主仓库的 Memory 系统（Phase 6）。

预估：3-4 天（含 SAO 侧 Memory 接口对接）。

---

### T5: Classlog Skill — 兴趣班课时管理（待 Memory 系统）

开发 `sao-skill-classlog`，记录娃上兴趣班的课时包、上课记录，查询剩余课时并对账。

```
skills/sao-skill-classlog/
├── SKILL.toml              # weight=1（轻量，主 Agent 直调）
├── pyproject.toml
└── sao_skill_classlog/
    ├── __init__.py
    └── skill.py            # tools: log / buy / balance / history / rotate
```

**设计要点**（已定稿）：
| 项目 | 决定 |
|---|---|
| 存储 | 飞书多维表格，独立 app_token（`FEISHU_BITABLE_CLASSLOG_APP_TOKEN`） |
| table_id | 不存储，每次 list tables 按名称查，找不到自动创建 |
| 课时包表 | `课时包`，永久不轮换，每次续费一行 |
| 上课记录表 | `上课记录_2026上` / `上课记录_2026下`，按学期轮换 |
| 学期规则 | 1-6月=上，7-12月=下 |
| 请假 | 不扣课时 |
| balance | 展示剩余/总购/已上，不展示金额 |

**tools**：
| tool | 说明 |
|---|---|
| `log` | 记录一次上课（自动创建当前学期表） |
| `buy` | 记录购买/续费课时包（自动创建课时包表） |
| `balance` | 查询课程剩余课时 |
| `history` | 按课程/月份查上课记录（对账用） |
| `rotate` | 归档当前学期 → 汇总回写课时包 → 创建新学期表 |

**依赖**: SAO 主仓库的 Memory 系统（用于缓存 table_id，可选优化）+ 飞书 Bitable API 建表能力。

**阻塞原因**: 创建多维表格后的 app_token 需要持久化存储，等 Memory 系统就绪后可自动管理。

预估：2-3 天。

---

### SAO-Store 待办优先级总结

| # | 任务 | 优先级 | 工作量 | 依赖 |
|---|------|--------|--------|------|
| T1 | SKILL.toml gating 字段 | **P0** | 0.5h | ✅ 已完成 |
| T2 | Expert TOML gating 字段 | **P1** | 0.5h | ✅ 已完成 |
| T3 | Token 预算精简 | **P2** | 1h | ✅ 已完成 |
| T4 | self-improve Skill | **P2** | 3-4d | SAO Phase 6 Memory |
| T5 | Classlog Skill（课时管理） | **P1** | 2-3d | SAO Memory 系统 |
