# SAO 开发规则参考库 — Rules Reference

> 来源: ZeroClaw AGENTS.md / CLAUDE.md + awesome-cursorrules + 社区最佳实践
> 用途: SAO 构建 `~/.sao/rules/*.md` 模板时的素材库，开发时直接复用
> 日期: 2026-03-11

---

## 1. 工程原则（Engineering Principles）

> 来源: ZeroClaw AGENTS.md §3

所有开发行为的底线约束，任何规则与原则冲突时以原则为准：

| 原则 | 含义 | 违反示例 |
|---|---|---|
| **KISS** | 选择最简单的可行方案，拒绝过度抽象 | 为一个 if/else 写工厂模式 |
| **YAGNI** | 不写当前任务不需要的代码 | 任务是修 bug，却顺手加了缓存层 |
| **DRY** | 提取重复 ≥ 3 次的逻辑，但不为 DRY 牺牲可读性 | 强行合并两个相似但语义不同的函数 |
| **SRP** | 每个函数/模块只做一件事 | 一个函数里既做解析又做网络请求又做存储 |
| **ISP** | 接口应尽量窄，不强迫调用方依赖不需要的方法 | 一个 10 方法的 ABC 只用到 2 个 |
| **Fail Fast** | 在函数入口验证参数/前置条件，尽早抛出明确错误 | 参数错误传到第 5 层才报 NoneType |
| **Secure by Default** | 不硬编码凭证/密钥；输入必须校验 | 写死 API_KEY="sk-xxx" |
| **Determinism** | 相同输入 → 相同输出；避免隐式全局状态 | 函数行为依赖全局变量 |
| **Reversibility** | 优先可回滚的方案（新增 > 修改 > 删除） | 直接删掉旧实现、重写 |

---

## 2. 先读后写（Read Before Write）

> 来源: ZeroClaw AGENTS.md §6 + awesome-cursorrules 通用 pattern

**规则**: 在做任何修改之前，**必须**先了解现有代码：

```
Phase 0: Read Before Write
1. 阅读任务涉及的源文件和已有测试
2. 阅读项目的 README / CONTRIBUTING / 相关文档
3. 搜索代码库中相似的实现，了解项目惯例和模式
4. 如果项目有 .cursorrules、AGENTS.md、CLAUDE.md 等文件，优先遵守其中的项目规则
```

**目的**: 避免重复造轮子、覆盖他人逻辑、或违背项目架构。

---

## 3. 干净分支（Clean Branch Gate）

> 来源: ZeroClaw AGENTS.md §2 "Clean-worktree gate"

```
Phase 0.5: Clean Branch Gate
- 如果指定了分支名，切换到该分支
- 如果未指定分支，创建 sao/task-{task_id} 分支
- 确认 git status 工作区干净后再开始开发
- 如果工作区有未提交变更：先 stash，完成任务后再 pop
```

**ZeroClaw 原文**: _"When starting a task, verify git status is clean. If there are uncommitted changes, stash them before beginning."_

---

## 4. 项目快照（Project Snapshot）

> 来源: ZeroClaw CLAUDE.md "Project Snapshot" 段

在项目定制规则中提供一段简短的项目元信息，帮助 IDE Agent 快速了解项目：

```markdown
## 项目快照 (Project Snapshot)
- 语言: Python 3.11+, asyncio
- 包: sao/ (核心引擎 + experts/ + skills/ + channels/ + dashboard/)
- 启动: `python -m sao --channel feishu`
- 数据库: SQLite (aiosqlite, WAL mode)
- LLM: Qwen via DashScope API
```

**优点**: IDE Agent 不需要花时间探索项目结构，直接知道关键信息。

---

## 5. 风险分级（Risk Tiers）

> 来源: ZeroClaw AGENTS.md §5 + CLAUDE.md §Risk Tiers

对不同文件/模块的修改要求不同级别的审慎度：

| Tier | 范围 | 要求 |
|---|---|---|
| **Low** | 文档、注释、测试、README | 直接提交，不需要额外验证 |
| **Medium** | 非核心模块（dashboard、experts、工具函数） | 测试通过即可 |
| **High** | 核心模块（core/、security/、main.py、数据库 schema） | 必须写文档 + 全量测试 + diff 审查 |
| **Critical** | 凭证文件、.env、部署配置、安全策略 | **禁止 IDE Agent 修改**，必须人工操作 |

**ZeroClaw 示例**: 
- Low-risk: docs, tests, comments
- Medium-risk: non-critical source files
- High-risk: core libraries, configuration, security modules

---

## 6. 反模式清单（Anti-Patterns）

> 来源: ZeroClaw AGENTS.md §11 + awesome-cursorrules 多项目合并

| 反模式 | 说明 | 正确做法 |
|---|---|---|
| **Scope Creep** | 修改任务范围外的文件，顺手重构 | 只改任务要求的部分 |
| **Test Sabotage** | 删除或注释掉已有测试让 CI 通过 | 修复测试失败的根因 |
| **Phantom Dependency** | 引入未在 requirements 中声明的依赖 | 明确记录新依赖 |
| **Secret Leak** | 在代码中硬编码 API Key / 密码 | 用环境变量 / secrets 管理 |
| **Big Bang Commit** | 一次提交所有变更，无法逐个回滚 | 原子性提交 |
| **Blind Edit** | 未阅读上下文就修改代码 | 先 Read Before Write |
| **Silent Failure** | 吞掉异常或返回空结果 | 明确抛出/记录错误 |
| **TODO Bombing** | 留下大量 TODO 但不处理 | 要么当场解决，要么明确报告 |
| **Auto-merge Trap** | 自动合并冲突而不理解语义 | 冲突时暂停，报告给用户 |
| **Infinite Loop** | 自我修复循环无退出条件 | 硬上限 MAX_FIX_ATTEMPTS |

---

## 7. 交接报告（Handoff Template）

> 来源: ZeroClaw AGENTS.md §12 "Handoff Template"

**5 字段结构**，确保每次任务完成后信息完整传递：

```
[SAO:TASK_COMPLETE]
status: success | partial | failed
what_changed: {修改了哪些文件，做了什么，用 1-3 句话概括}
what_not_changed: {任务中哪些要求没有完成，以及原因}
validation: {测试结果/lint 结果/手动验证情况}
risks: {可能的副作用、需要人工关注的点}
next_action: {建议的后续步骤，没有则填「无」}
```

**对比旧版**（只有 status + files_changed + test_result + summary）→ 新版增加了 what_not_changed、risks、next_action，信息更完整。

---

## 8. Vibe Coding 护栏

> 来源: ZeroClaw AGENTS.md §14 "Vibe Coding Guardrails"

即使是"快速修复"、"随便试试"的场景，也最低要求：

```
Vibe Coding Guardrails:
1. 不读代码就改代码（Blind Edit）→ 禁止
2. 修改任务范围外的文件（Scope Creep）→ 禁止
3. 跳过测试验证 → 禁止（必须至少运行一次）
4. 吞掉异常或 TODO 标记 → 禁止（必须处理或明确报告）
5. 不写提交信息 → 禁止（每次 commit 必须有描述）
```

**适用场景**: `quick.md` 精简规则中使用，防止小任务产生大问题。

---

## 9. 两层规则架构（Two-Layer Rules）

> 来源: ZeroClaw CLAUDE.md (~50行) + AGENTS.md (~500行) 分层设计

**问题**: 完整规则 ~100 行，全部注入 IDE Agent prompt 浪费 token。

**方案**: 分成 slim + full 两层：

| 层 | 文件 | 注入方式 | Token 数 |
|---|---|---|---|
| **slim** | `default.slim.md` | SAO 注入到 IDE Agent system prompt | ~200-400 |
| **full** | `default.md` | SAO 复制到项目工作区 `AGENTS.md`，IDE Agent 自行读取 | ~800-1500 |

```
~/.sao/rules/
├── default.md              # 完整版
├── default.slim.md         # 精简版（可选）
├── quick.md
├── quick.slim.md
├── sao-project.md
└── sao-project.slim.md
```

**加载策略**:
1. 如果 `xxx.slim.md` 存在 → prompt 注入 slim 版本 + full 版本写到 `AGENTS.md`
2. 如果 `xxx.slim.md` 不存在 → prompt 注入完整的 `xxx.md`（向后兼容）

**ZeroClaw 参考**:
- `CLAUDE.md` (~50 行): Commands, Project Snapshot, Repo Map, Risk Tiers, Workflow, Anti-Patterns, Linked References
- `AGENTS.md` (~500 行): 完整 12 节，包含所有工程原则、代码约定、验证矩阵等

---

## 10. 代码命名约定（Code Naming Contract）

> 来源: ZeroClaw AGENTS.md §8

为项目定制规则中提供命名约定，避免 IDE Agent 乱命名：

```markdown
## 命名约定
- 变量/函数: snake_case
- 类: PascalCase  
- 常量: UPPER_SNAKE_CASE
- 私有: 前缀 _
- 文件: snake_case.py
- 模块: 短名词，避免缩写（除非是通用缩写如 db, ws, api）
```

---

## 11. 架构边界约定（Architecture Boundary Contract）

> 来源: ZeroClaw AGENTS.md §9

定义模块间的依赖方向，防止 IDE Agent 引入循环依赖：

```markdown
## 依赖方向（只允许从上到下）
channels/ → core/agent → core/router → core/llm/
                       → experts/
                       → skills/
                       → pipeline/
core/ → memory/
     → security/
     → subagent/
skills/ → sandbox/ (仅 TOML/Forge 技能)
skills/programming/ → subagent/ (IDE 编程任务)

## 禁止
- skills/ 不能 import channels/
- experts/ 不能 import skills/
- core/llm/ 不能 import core/agent（循环依赖）
```

---

## 12. 验证矩阵（Validation Matrix）

> 来源: ZeroClaw AGENTS.md §10

不同类型的变更需要不同的验证手段：

| 变更类型 | 单元测试 | 集成测试 | Lint | 类型检查 | 手动验证 |
|---|---|---|---|---|---|
| Bug 修复 | ✓ | 可选 | ✓ | 可选 | - |
| 新功能 | ✓ | ✓ | ✓ | 可选 | - |
| 重构 | ✓ | ✓ | ✓ | ✓ | - |
| 安全修复 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 配置变更 | - | ✓ | - | - | ✓ |
| 文档变更 | - | - | - | - | ✓ |

---

## 13. 变更手册（Change Playbooks）

> 来源: ZeroClaw AGENTS.md §10

为常见变更类型提供标准操作流程：

### 13.1 新增模块

```
1. 在文档中声明模块职责和接口
2. 创建模块文件，写好 docstring
3. 实现核心逻辑
4. 编写单元测试
5. 在 __init__.py 中导出公共接口
6. 更新相关文档（design.md / skills.md / experts.md）
```

### 13.2 修复 Bug

```
1. 编写失败测试用例（复现 bug）
2. 定位根因
3. 最小修复（不扩大修改范围）
4. 验证测试通过
5. 检查是否有同类 bug
```

### 13.3 重构

```
1. 确保已有测试覆盖被重构的代码
2. 小步迭代（每步保持测试通过）
3. 不在重构中混入新功能
4. 完成后运行全量测试
```

### 13.4 删除代码

```
1. 确认没有其他地方引用（搜索所有 import / 调用）
2. 先废弃（deprecation 标记），再删除
3. 更新相关文档
4. 运行全量测试
```

---

## 14. 安全开发约束（Security Constraints）

> 来源: ZeroClaw AGENTS.md §3 "Secure by Default" + awesome-cursorrules security patterns

### 14.1 IDE Agent 禁止操作

以下操作 IDE Agent **不允许执行**，Rules 中明确声明：

```markdown
## 绝对禁止
- 修改 .env / .env.local / secrets 文件
- 在代码中硬编码任何凭证、API Key、密码
- 执行 rm -rf / del /s /q 等批量删除命令
- 修改 Git 历史（git rebase / git push --force）
- 安装系统级软件包（apt install / choco install）
- 修改 SSH 配置或密钥文件
- 执行网络监听或端口扫描
- 访问或修改 ~/.sao/secrets.db
```

### 14.2 需确认操作

以下操作需要 SAO 中转确认（IDE Agent 输出意图，SAO 判断是否执行）：

```markdown
## 需确认
- 安装新的 pip/npm 依赖
- 删除文件（而非内容修改）
- 修改数据库 schema
- 修改端口配置
- 创建新的网络服务
```

### 14.3 文件作用域限制

```markdown
## 文件作用域
- 只允许修改 workspace 目录下的文件
- 不允许修改 workspace 外的任何文件
- 不允许创建 workspace 之外的文件
- 临时文件只能在 workspace 的 .tmp/ 目录下
```

---

## 15. awesome-cursorrules 常见模板摘要

> 来源: github.com/PatrickJS/awesome-cursorrules (38.4k stars)

### 15.1 通用 Python 模板

```
You are an expert in Python, async programming, and clean architecture.

Key Principles:
- Write concise, technical responses with accurate Python examples
- Use functional, declarative programming; avoid classes where functions suffice
- Prefer iteration and modularization over code duplication
- Use descriptive variable names with auxiliary verbs (is_active, has_permission)
- Follow PEP 8 naming conventions
- Use type hints for all function signatures
- Prefer pathlib over os.path
- Write docstrings for all public functions/classes

Error Handling:
- Use specific exceptions, not bare except
- Log errors with context (logger.error("...", exc_info=True))
- Validate inputs at function boundaries (fail fast)
```

### 15.2 TypeScript / React 模板（参考）

```
Key Principles:
- Use functional components and TypeScript interfaces
- Prefer const over let, avoid var
- Use early returns to reduce nesting
- Always use CSS modules or Tailwind for styling
- Implement proper error boundaries
```

### 15.3 通用安全模板

```
Security:
- Never hardcode secrets or API keys
- Always validate and sanitize user input
- Use parameterized queries for database operations
- Implement proper authentication and authorization checks
- Set secure HTTP headers
- Log security events for auditing
```

---

## 16. ZeroClaw AGENTS.md 完整大纲

> 供参考的 ZeroClaw 12 节原始结构（~500 行）

```
§1  Session Default Target
    - agent_language: 中文
    - output_format: Markdown
    - risk_tolerance: conservative
    
§2  Clean-worktree Gate
    - git status must be clean before starting
    - stash if dirty, pop after completion

§3  Engineering Principles (KISS/YAGNI/DRY/SRP/ISP/Fail Fast/Secure by Default/Determinism/Reversibility)

§4  Project Snapshot
    - language, package manager, build system, test framework

§5  Repository Map
    - directory structure with one-line descriptions
    
§6  Risk Tiers
    - Low / Medium / High / Critical with per-tier requirements

§7  Agent Workflow (6 steps)
    1. Understand → 2. Plan → 3. Execute → 4. Verify → 5. Document → 6. Handoff

§8  Code Naming Contract
    - naming conventions per language

§9  Architecture Boundary Contract
    - dependency direction rules, forbidden imports

§10 Change Playbooks + Validation Matrix
    - standard procedures for add/fix/refactor/delete
    - verification requirements by change type

§11 PR Discipline
    - atomic commits, descriptive messages, no force push

§12 Anti-Patterns
    - scope creep, test sabotage, phantom deps, etc.

§13 Handoff Template
    - what_changed / what_not_changed / validation / risks / next_action

§14 Vibe Coding Guardrails
    - minimum requirements even for quick/casual coding
```

---

## 17. ZeroClaw CLAUDE.md 完整结构

> 精简版 ~50 行，注入 system prompt

```
§ Commands
    /test — run full test suite
    /lint — run linter
    /build — compile project

§ Project Snapshot
    - one-paragraph project description
    - key technologies and versions

§ Repository Map
    - top-level directory → purpose (one line each)

§ Risk Tiers (summary)
    - Low: docs/tests → go ahead
    - High: core/security → extra caution

§ Workflow (condensed)
    - Read → Plan → Execute → Test → Handoff

§ Anti-Patterns (top 5)
    - scope creep, blind edit, test sabotage, phantom deps, secret leak

§ Linked References
    - "See AGENTS.md for full engineering protocol"
    - "See docs/ for architecture details"
```

---

## 18. SAO 自用模板建议

基于以上素材，SAO 的 `~/.sao/rules/` 推荐这样组织：

| 文件 | 用途 | 核心内容 |
|---|---|---|
| `default.md` | 通用开发规则（所有项目） | 工程原则 + Phase 0~5 + 反模式 + 交接报告 |
| `default.slim.md` | 精简版（token 省量） | Phase 0~5 流水线 + 反模式 top5 + 交接格式 |
| `quick.md` | 小任务规则 | 跳过文档 + Vibe Coding 护栏 + 交接报告 |
| `sao-project.md` | SAO 项目定制 | 继承 default + 项目快照 + 命名约定 + 依赖方向 + 风险分级 |
| `{project}.md` | 其他项目定制 | 继承 default + 项目特定约定 |

**Rules 加载优先级**: 
```
项目级 (.cursorrules / AGENTS.md / CLAUDE.md)  ← IDE Agent 自行读取
    ↑
SAO 项目定制规则 ({project}.md)                 ← SAO 注入 prompt
    ↑
SAO 通用规则 (default.md)                       ← SAO fallback
```

---

_本文件仅作参考素材库，不直接用于生产。实际规则模板见 `~/.sao/rules/` 目录。_
