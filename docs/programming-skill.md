# SAO Programming Skill 设计文档

> 版本: 1.1.0 | 日期: 2026-03-11 | 状态: 设计完成（含 ZeroClaw 最佳实践）
>
> 编程是一个 **Skill**（不是 Expert）。SAO 不自己写代码——它编排本地 IDE/Agent 来完成编程任务。
> 所有编程操作都在 **SubAgent** 中异步执行（长时间运行）。
>
> **关键设计决策**：编程是 **1 个 Skill + 多个 IDE Adapter**，不是每个 IDE 一个 Skill。
> 用户不关心用什么 IDE，只关心任务完成。IDE 的选择通过 `machines.yaml` 配置决定，不由 Router 判断。

---

## 1. 核心理念

```
┌──────────────────────────────────────────────────────────────┐
│                         SAO = 编排者                          │
│                                                              │
│  "帮我在 project-a 里加个登录功能"                              │
│       │                                                      │
│       ▼                                                      │
│  SAO 不写一行代码，而是：                                       │
│  1. 找到 project-a 对应的本地工作区                                 │
│  2. 找到本机上配置的 IDE/Agent                                    │
│  3. 打开 IDE，把任务交给 Agent                                  │
│  4. 监控进度，收集结果                                          │
│  5. 在飞书上汇报                                               │
│  6. 完成后 git push 到 GitHub 同步                               │
└──────────────────────────────────────────────────────────────┘
```

### 为什么是 Skill 不是 Expert？

| 维度 | Expert（Chat 分流） | Skill（编排执行） |
|---|---|---|
| 本质 | 换一套 Prompt 让 LLM 回答 | 调用外部工具/系统完成任务 |
| 编程场景 | LLM 直接生成代码片段（已有 `code` Expert） | **操控 IDE Agent 在真实项目中编程** |
| 耗时 | 秒级 | 分钟~小时级 |
| 状态 | 无状态 | 有状态（项目、分支、文件变更） |
| 输出 | 文本 | diff / commit / 测试报告 / 运行结果 |

**`code` Expert 仍然保留**——用于回答编程问题、生成代码片段。`programming` Skill 用于在真实项目中执行编程任务。

---

## 2. 架构总览

```
飞书: "帮我在 sao 项目里重构 router"
    │
    ▼
┌──────────┐  {"route":"skill", "skill":"programming",
│  Router  │   "tool":"code", "args":{"task":"重构 router", "project":"sao"}}
└────┬─────┘
     │
     ▼
┌──────────────────────┐
│  ProgrammingSkill    │
│                      │
│  1. 解析 project     │──► Machine Registry（project → machine 映射）
│  2. 选择 adapter     │──► IDE Adapter Registry（machine → adapter）
│  3. 创建 SubAgent    │──► SubAgent Manager（异步后台执行）
│  4. 返回 task-id     │
└──────────────────────┘
     │
     ▼ (立即返回飞书)
"🔧 编程任务已创建 (task-id: abc123)
 📍 项目: sao | IDE: VS Code + Copilot
 使用 /tasks 查看进度"

     ▼ (后台 SubAgent 异步执行)
┌──────────────────────────────────────────────────┐
│  SubAgent: ProgrammingRunner                      │
│                                                  │
│  ┌─────────────┐    ┌─────────────────────────┐  │
│  │  Connector  │───►│  IDE Agent              │  │
│  │  (本地)      │    │  (Copilot/Antigravity/  │  │
│  │             │    │   Claude Code/Cursor)   │  │
│  └─────────────┘    └────────────┬────────────┘  │
│                                  │               │
│  ┌───────────────────────────────▼────────────┐  │
│  │  Task Pipeline:                            │  │
│  │  1. Open project in IDE                    │  │
│  │  2. Send coding task → Agent               │  │
│  │  3. Monitor progress (polling/streaming)    │  │
│  │  4. Collect results (diff/files)           │  │
│  │  5. Run tests (via IDE)                    │  │
│  │  6. Report back to Feishu                  │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

---

## 3. Machine & IDE 配置

### 3.1 配置文件

在 `~/.sao/machines.yaml`（或 `.env` 中声明路径）中定义本机可用 IDE：

> **跨平台策略**：每台机器本地运行 SAO + 本地 IDE Agent，代码通过 GitHub 同步。
> 不采用 SSH 远程控制——远程机器上各自运行 SAO 实例，共享同一份配置。

```yaml
# ~/.sao/machines.yaml
# ── SAO 开发者配置示例（Windows 本机）──
# 作为 SAO + SAO-Store 的开发者，同时配置两个仓库的 workspace，
# 这样可以让 SAO 在 SAO-Store 中直接开发新 Skill / Expert。

machines:
  # ─── Windows 本机 ───
  local:
    host: localhost
    platform: windows
    default: true
    ide:
      name: vscode                     # IDE 类型
      agent: copilot                   # Agent 类型 (copilot | claude-code | aider | codex)
      binary: "code"                   # VS Code CLI 路径（PATH 中可直接调用）
      agent_mode: agent                # copilot 模式: agent | chat | edit
    workspaces:
      - name: sao                      # SAO 主仓库
        path: "C:\\Users\\yiliu4\\code\\Super-Agent-OS"
        rules: sao-project             # 项目定制规则
      - name: sao-store               # 组件仓库 (SAO-Store: skills + experts)
        path: "C:\\Users\\yiliu4\\code\\SAO-Store"
        rules: sao-project             # 同样使用 SAO 项目规则
      - name: web-app
        path: "C:\\Users\\yiliu4\\code\\my-web-app"
        rules: default
```

**普通用户**只需配置自己的项目，不需要 `sao` 或 `sao-store` workspace。
他们通过 StoreManager 的 `install` 命令从 GitHub 拉取组件即可：

```yaml
# 普通用户的 ~/.sao/machines.yaml
machines:
  local:
    host: localhost
    platform: windows
    default: true
    ide:
      name: vscode
      agent: copilot
      binary: "code"
    workspaces:
      - name: my-app                   # 只有自己的项目
        path: "C:\\Users\\someone\\code\\my-app"
      - name: my-blog
        path: "C:\\Users\\someone\\code\\my-blog"
```

**Mac / Linux 机器**上同样在本地运行 SAO，配置各自的 `machines.yaml`。
注意 `ide.name` 和 `ide.agent` 的不同——同一个 Programming Skill 会自动选择对应的 Adapter：

```yaml
# Mac Studio 上的 ~/.sao/machines.yaml
machines:
  local:
    host: localhost
    platform: macos
    default: true
    ide:
      name: cursor                     # 换 IDE 只需改这里
      agent: claude-code               # 换 Agent 只需改这里
      binary: "cursor"
    workspaces:
      - name: sao
        path: "/Users/yiliu4/code/Super-Agent-OS"
      - name: ios-app
        path: "/Users/yiliu4/code/ios-app"
```

> **核心原则**：workspace 只是告诉 SAO "这个别名对应磁盘哪个目录"。
> IDE 的选择通过 `ide.name` + `ide.agent` 配置，不是用户在飞书消息里指定的。
> 用户只需说 "帮我在 sao-store 里写个新 skill"，SAO 自动根据配置选择正确的 IDE + Adapter。

### 3.2 项目解析规则

当用户说 "在 sao 项目里改个 bug" 时，Router 提取 `project=sao`，Skill 按以下顺序查找：

```
1. 精确匹配 workspace.name → 找到 "sao" → local
2. 路径匹配（用户说了完整路径）
3. 模糊匹配（Levenshtein 距离 ≤ 2）
4. 未找到 → 用默认机器 + 让用户指定目录
```

### 3.3 跨平台同步策略

不采用 SSH 远程控制，而是每台机器本地运行 SAO，代码通过 **GitHub** 同步：

```
┌── Windows 本机 ────────┐   ┌── Mac Studio ─────────┐
│ SAO + VS Code + Copilot  │   │ SAO + Cursor + Claude   │
│ ~/.sao/machines.yaml     │   │ ~/.sao/machines.yaml     │
│ git clone sao / skills   │   │ git clone sao / skills   │
└─────────┬──────────────┘   └─────────┬───────────────┘
          │                               │
          └─────────┬─────────────┘
                    │
              ┌─────┴─────┐
              │   GitHub    │
              │  (git push  │
              │   / pull)   │
              └───────────┘
```

**优点**：
- 无需 SSH 隧道、无需开放端口，零网络配置
- 每台机器的 IDE Agent 在本地运行，无延迟、无权限问题
- Git 分支天然提供变更跟踪 + 回滚能力
- 多机器并行开发时，GitHub 做合并点

---

## 4. IDE Adapter 抽象

### 4.1 基类

```python
# sao/skills/programming/adapters/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class CodingTask:
    """编程任务描述"""
    task: str                    # 自然语言任务描述（来自 resolved_query）
    project: str                 # 项目别名
    workspace_path: str          # 绝对路径
    rules_profile: str = "default"        # 开发规则模板名（详见 §6.5）
    files: list[str] | None = None        # 指定文件（可选）
    branch: str | None = None             # Git 分支（可选）
    test_after: bool = True               # 编码后是否自动测试
    run_after: bool = False               # 编码后是否自动运行

@dataclass
class CodingResult:
    """编程结果"""
    success: bool
    summary: str                 # 人类可读摘要
    diff: str | None = None     # Git diff
    files_changed: list[str] | None = None
    test_output: str | None = None
    test_passed: bool | None = None
    error: str | None = None
    duration_s: float = 0

class IDEAdapter(ABC):
    """IDE Agent 适配器基类"""

    @abstractmethod
    async def open_project(self, workspace_path: str) -> bool:
        """打开项目/工作区"""
        ...

    @abstractmethod
    async def send_task(self, task: CodingTask) -> str:
        """发送编程任务给 IDE Agent，返回 session/task ID"""
        ...

    @abstractmethod
    async def poll_status(self, session_id: str) -> str:
        """轮询任务状态: pending | running | completed | failed"""
        ...

    @abstractmethod
    async def collect_result(self, session_id: str) -> CodingResult:
        """收集编程结果"""
        ...

    @abstractmethod
    async def run_tests(self, workspace_path: str, command: str | None = None) -> CodingResult:
        """在 IDE 中运行测试"""
        ...

    @abstractmethod
    async def run_project(self, workspace_path: str, command: str | None = None) -> CodingResult:
        """在 IDE 中运行项目"""
        ...
```

### 4.2 VS Code + Copilot Adapter

```python
# sao/skills/programming/adapters/vscode.py

class VSCodeCopilotAdapter(IDEAdapter):
    """
    通过 VS Code CLI + Copilot Agent Mode 编程。

    工作原理：
    1. `code <path>` 打开项目
    2. 通过 VS Code Extension API（或内置终端）发送任务给 Copilot
    3. Copilot Agent Mode 自主编辑文件、运行命令
    4. 通过 git diff 收集结果

    依赖：
    - VS Code 已安装且在 PATH 中
    - GitHub Copilot 扩展已安装并登录
    - sao-vscode-bridge 扩展（可选，提供 HTTP API 控制）
    """

    async def open_project(self, workspace_path: str) -> bool:
        # 本地: code <path>
        cmd = f'code "{workspace_path}"'
        result = await self.connector.execute(cmd)
        return result.exit_code == 0

    async def send_task(self, task: CodingTask) -> str:
        """
        方案 A: sao-vscode-bridge 扩展（推荐）
          - VS Code 扩展监听 HTTP 端口
          - POST /task {"prompt": "...", "files": [...]}
          - 扩展调用 Copilot Chat API (@workspace 模式)

        方案 B: 终端自动化（降级方案）
          - 打开 VS Code 内置终端
          - 使用 Copilot CLI: gh copilot suggest "..."
          - 或直接调用 claude code CLI 作为替代

        方案 C: VS Code Extension Host（MCP 协议）
          - 通过 MCP client 连接 VS Code 的 MCP server
          - 使用 MCP tools 操控编辑器
        """
        ...

    async def run_tests(self, workspace_path: str, command: str | None = None) -> CodingResult:
        """
        在 VS Code 的终端中运行测试命令。
        如未指定命令，尝试自动检测：
        - Python: pytest / python -m pytest
        - Node.js: npm test
        - Go: go test ./...
        """
        ...
```

### 4.3 Antigravity Adapter

```python
# sao/skills/programming/adapters/antigravity.py

class AntigravityAdapter(IDEAdapter):
    """
    通过 Antigravity Agent 编程。

    工作原理：
    1. 本地启动 Antigravity CLI / API
    2. 发送任务，Antigravity 自主编程
    3. 收集结果

    依赖：
    - Antigravity 已在本地安装
    """

    async def send_task(self, task: CodingTask) -> str:
        # antigravity run --workspace <path> --task "<task>"
        cmd = f'cd "{task.workspace_path}" && antigravity run --task "{task.task}"'
        session_id = await self.connector.execute_background(cmd)
        return session_id
```

### 4.4 CLI Agent Adapter（通用）

```python
# sao/skills/programming/adapters/cli_agent.py

class CLIAgentAdapter(IDEAdapter):
    """
    通用 CLI Agent 适配器。
    支持任何有 CLI 的 coding agent:
    - Claude Code: `claude --task "..." --workspace <path>`
    - Aider: `aider --message "..." <files>`
    - Codex CLI: `codex "..." --cwd <path>`
    - Cursor (CLI mode 如有)

    这是最通用的适配器——任何能通过命令行接收任务的 Agent 都能用。
    """

    def __init__(self, binary: str, task_template: str, **kwargs):
        """
        binary: Agent 可执行文件路径
        task_template: 命令模板，支持 {task}, {workspace}, {files} 占位符
          例: 'claude --task "{task}" --workspace "{workspace}"'
          例: 'aider --message "{task}" {files}'
        """
        self.binary = binary
        self.task_template = task_template

    async def send_task(self, task: CodingTask) -> str:
        cmd = self.task_template.format(
            task=task.task,
            workspace=task.workspace_path,
            files=" ".join(task.files or []),
        )
        session_id = await self.connector.execute_background(
            f'cd "{task.workspace_path}" && {cmd}'
        )
        return session_id

    async def collect_result(self, session_id: str) -> CodingResult:
        # 通用方案：通过 git diff 收集变更
        diff = await self.connector.execute(
            f'cd "{self.workspace_path}" && git diff'
        )
        return CodingResult(
            success=True,
            summary=f"Agent 完成编码，{len(diff.stdout.splitlines())} 行变更",
            diff=diff.stdout,
        )
```

### 4.5 Adapter 注册表

**1 个 Skill + 多个 Adapter** 的核心就在这里——`machines.yaml` 中的 `ide.name` 作为 key 查找 Adapter：

```python
# sao/skills/programming/adapters/__init__.py

ADAPTERS: dict[str, type[IDEAdapter]] = {
    "vscode":       VSCodeCopilotAdapter,
    "antigravity":  AntigravityAdapter,
    "cli-agent":    CLIAgentAdapter,     # 通用 CLI
    "cursor":       CLIAgentAdapter,     # Cursor 通过 CLI 模式
    "claude-code":  CLIAgentAdapter,     # Claude Code CLI
    "aider":        CLIAgentAdapter,     # Aider CLI
}

# 选择逻辑（在 ProgrammingSkill 中）：
# adapter_cls = ADAPTERS[machine_config.ide.name]
# adapter = adapter_cls(binary=machine_config.ide.binary, ...)
#
# 用户在 machines.yaml 配 name: vscode → 用 VSCodeCopilotAdapter
# 用户在 machines.yaml 配 name: antigravity → 用 AntigravityAdapter
# 用户在 machines.yaml 配 name: claude-code → 用 CLIAgentAdapter
```

---

## 5. Connector（连接层）

连接层负责在 **本机** 执行命令：

```python
# sao/skills/programming/connector.py

class Connector(ABC):
    """命令执行连接器"""

    @abstractmethod
    async def execute(self, command: str, timeout: int = 60) -> ExecResult:
        """执行命令并等待结果"""
        ...

    @abstractmethod
    async def execute_background(self, command: str) -> str:
        """后台执行命令，返回 session ID"""
        ...

    @abstractmethod
    async def is_alive(self) -> bool:
        """连接是否存活"""
        ...


class LocalConnector(Connector):
    """本地命令执行（唯一实现）"""

    async def execute(self, command: str, timeout: int = 60) -> ExecResult:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return ExecResult(
            exit_code=proc.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )
```

> **为什么没有 SSHConnector？**
> 跨平台策略是每台机器本地运行 SAO + 本地 IDE Agent，代码通过 GitHub 同步，不需要 SSH 远程控制。
> 将来如确实需要远程场景，可以新增 SSHConnector，但不是 MVP 范围。

---

## 6. SubAgent 集成

### 6.1 为什么所有编程操作都走 SubAgent？

| 原因 | 说明 |
|---|---|
| **耗时长** | 编码任务分钟~小时级，不能阻塞 Agent 主循环 |
| **有状态** | 需要跟踪 IDE 会话、中间产物、测试结果 |
| **可中断** | 用户可能要取消或修改任务 |
| **多步骤** | 编码 → 测试 → 修复 → 再测 → 报告，是循环流程 |
| **可并行** | 同时在不同项目上执行多个编程任务 |

### 6.2 编程 SubAgent 流程

```
ProgrammingSkill.execute("code", args)
    │
    ├── 1. 解析 project → machine → adapter
    ├── 2. 创建 CodingTask
    ├── 3. 提交给 SubAgentManager.delegate()
    ├── 4. 立即返回 "任务已创建 (task-id: xxx)"
    │
    └── SubAgent 后台异步执行 ─────────────────────────────┐
                                                           │
        ┌──────────────────────────────────────────────────▼────┐
        │  ProgrammingRunner (SubAgent Task)                     │
        │                                                        │
        │  Step 1: Connect                                       │
        │    └── LocalConnector (localhost)                       │
        │                                                        │
        │  Step 2: Open Project                                  │
        │    └── adapter.open_project(workspace_path)             │
        │                                                        │
        │  Step 3: Build Prompt (Rules + Task)                   │
        │    └── prompt = build_task_prompt(coding_task, rules)   │
        │        → 注入开发规则：                                  │
        │          Phase 0: 先读后写（Read Before Write）          │
        │          Phase 0.5: 干净分支（Clean Branch Gate）        │
        │          Phase 1~5: 文档→编码→测试→超时汇报→交接报告     │
        │                                                        │
        │  Step 4: Send Task                                     │
        │    └── session_id = adapter.send_task(prompt)           │
        │                                                        │
        │  Step 5: Monitor (超时感知)                             │
        │    └── while status != "completed":                    │
        │          status = adapter.poll_status(session_id)       │
        │          if task_timeout (default 10min):              │
        │            → IDE Agent 内部规则会自行汇报当前进度         │
        │            → SAO 收到「仍在进行中」→ 决定是否继续等待     │
        │          if global_timeout (30min): abort()            │
        │          await sleep(poll_interval)                    │
        │          [可选] 发进度到飞书                              │
        │                                                        │
        │  Step 6: Collect Results                               │
        │    └── result = adapter.collect_result(session_id)      │
        │                                                        │
        │  Step 7: SAO Review (Agent 介入)                       │
        │    └── SAO Agent 检查结果:                               │
        │        ├── 文档写了吗？→ 没有则要求补                     │
        │        ├── 测试通过？→ 失败则进入自动修复循环              │
        │        ├── 代码质量？→ 通过 diff 检查                    │
        │        └── 需要额外操作？→ 发新 task 给 IDE Agent        │
        │                                                        │
        │  Step 8: Report to Feishu                              │
        │    └── 发送结果卡片（diff 摘要 + 测试结果 + 操作按钮）      │
        │                                                        │
        └────────────────────────────────────────────────────────┘
```

### 6.3 自动修复循环（Retry Loop）

```python
MAX_FIX_ATTEMPTS = 3

async def _coding_loop(self, task: CodingTask, adapter: IDEAdapter) -> CodingResult:
    """编码 → 测试 → 修复循环"""
    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        # 第一次: 发送原始任务; 后续: 发送修复任务
        if attempt == 1:
            session_id = await adapter.send_task(task)
        else:
            fix_task = CodingTask(
                task=f"测试失败，请修复以下错误:\n{last_error}\n\n原始任务: {task.task}",
                project=task.project,
                workspace_path=task.workspace_path,
                test_after=True,
            )
            session_id = await adapter.send_task(fix_task)

        # 等待完成
        result = await self._wait_and_collect(adapter, session_id)

        # 不需要测试 or 测试通过 → 完成
        if not task.test_after:
            return result
        test_result = await adapter.run_tests(task.workspace_path)
        if test_result.test_passed:
            result.test_output = test_result.test_output
            result.test_passed = True
            return result

        # 测试失败，记录错误
        last_error = test_result.test_output
        await self._notify_progress(
            f"⚠️ 第 {attempt} 次尝试测试未通过，自动修复中... ({attempt}/{MAX_FIX_ATTEMPTS})"
        )

    # 超出重试次数
    result.test_passed = False
    result.test_output = last_error
    return result
```

### 6.4 Development Rules — 开发规则协议

SAO 向 IDE Agent 发送的不是裸任务描述，而是一个 **结构化 Prompt**，包含开发规则（Rules）+ 任务目标。
规则确保 IDE Agent 按照 SAO 期望的流程工作：先写文档、再编码、测试、超时汇报。

#### 6.4.1 为什么需要 Rules？

| 问题 | 没有 Rules | 有 Rules |
|---|---|---|
| IDE Agent 直接改代码不写文档 | ✗ 改完不知道改了什么、为什么改 | ✓ 先输出设计文档，再动手 |
| 跑了 20 分钟还没完 | ✗ SAO 不知道进度，用户等得焦虑 | ✓ 10 分钟自动汇报进度 |
| 测试不通过就放弃 | ✗ 没有自愈能力 | ✓ 自动修复循环 |
| 不同 IDE Agent 行为不一致 | ✗ Copilot/Claude Code 各玩各的 | ✓ 统一开发流程 |

#### 6.4.2 Rules 模板

存储位置：`~/.sao/rules/` 目录，每个 `.md` 文件是一个 rules profile。

**默认规则** (`~/.sao/rules/default.md`)：

```markdown
# SAO Development Rules

你是 SAO 系统委派的编程代理。请严格按照以下流程执行任务。

## 工程原则（Engineering Principles）

所有阶段均须遵守以下约束，任何冲突以此为准：

| 原则 | 含义 |
|---|---|
| **KISS** | 选择最简单的可行方案，拒绝过度抽象 |
| **YAGNI** | 不写当前任务不需要的代码 |
| **DRY** | 提取重复 ≥ 3 次的逻辑，但不要为了 DRY 牺牲可读性 |
| **SRP** | 每个函数/模块只做一件事 |
| **Fail Fast** | 在函数入口验证参数/前置条件，尽早抛出明确错误 |
| **Secure by Default** | 不在代码中硬编码凭证/密钥；输入必须校验 |
| **Determinism** | 相同输入 → 相同输出；避免隐式全局状态 |
| **Reversibility** | 优先可回滚的方案（新增 > 修改 > 删除） |

## 阶段 0: 先读后写 (Read Before Write)

在做任何修改之前，**必须**先了解现有代码：

1. 阅读任务涉及的源文件和已有测试
2. 阅读项目的 README / CONTRIBUTING / 相关文档
3. 搜索代码库中相似的实现，了解项目惯例和模式
4. 如果项目有 `.cursorrules`、`AGENTS.md`、`CLAUDE.md` 等文件，**优先遵守其中的项目规则**

> 目的：避免重复造轮子、覆盖他人逻辑、或违背项目架构。

## 阶段 0.5: 干净分支 (Clean Branch Gate)

- 如果 SAO 指定了分支名，切换到该分支
- 如果未指定分支，创建 `sao/task-{task_id}` 分支
- 确认 `git status` 工作区干净后再开始开发
- 如果工作区有未提交变更：先 stash，完成任务后再 pop

## 阶段 1: 文档先行 (必须)

在写任何代码之前，先在项目根目录创建或更新 `docs/tasks/{task_id}.md`：

```
# Task: {task_title}

## 目标
{对任务目标的理解，用自己的话复述}

## 方案
- 需要修改的文件和模块
- 技术方案概要
- 预计影响范围

## 风险
- 可能的副作用或破坏性变更

## 验收标准
- [ ] 功能正常
- [ ] 测试通过
- [ ] 无新增 lint 错误
```

## 阶段 2: 编码

- 在 Git 工作分支上开发
- 遵循项目现有的代码风格和约定
- 每个逻辑变更尽量保持原子性
- 优先修改已有代码，避免新增文件（除非有结构性理由）

## 阶段 3: 测试与验证

- 编码完成后，运行项目的测试命令
- 如果测试失败：分析错误原因 → 修复 → 重新测试（最多 3 轮）
- 如果项目无测试，至少确保代码能正常运行不报错
- 运行 lint/type-check（如项目配置了的话）

## 阶段 4: 超时汇报

**重要**：如果你持续工作 **10 分钟** 仍未完成：
1. 立即暂停当前工作
2. 在 `docs/tasks/{task_id}.md` 中更新进度：
   - 已完成的部分
   - 当前卡在什么地方
   - 预计还需要多长时间
3. 输出 `[SAO:TIMEOUT_REPORT]` 标记，SAO 会据此介入

## 阶段 5: 完成交接报告 (Handoff)

任务完成后，输出以下 5 字段结构化交接信息：

```
[SAO:TASK_COMPLETE]
status: success | partial | failed
what_changed: {修改了哪些文件，做了什么，用 1-3 句话概括}
what_not_changed: {任务中哪些要求没有完成，以及原因}
validation: {测试结果/lint 结果/手动验证情况}
risks: {可能的副作用、需要人工关注的点}
next_action: {建议的后续步骤，没有则填「无」}
```

## 反模式（Anti-Patterns）—— 禁止事项

| 反模式 | 说明 |
|---|---|
| **Scope Creep** | 不要修改与任务无关的文件，不要顺手重构 |
| **Test Sabotage** | 不要删除或注释掉已有测试 |
| **Phantom Dependency** | 不要引入项目未使用的新依赖（除非任务明确要求） |
| **Secret Leak** | 不要修改 .env 或含密钥的文件，不要在代码中硬编码凭证 |
| **Big Bang Commit** | 不要一次提交所有变更，保持原子性 |
| **Blind Edit** | 不要未阅读上下文就修改代码（见阶段 0） |
| **Silent Failure** | 不要吞掉异常或返回空结果，确保错误可观测 |
```

**精简规则** (`~/.sao/rules/quick.md`)——用于小任务（< 10 行变更）：

```markdown
# SAO Quick Fix Rules

快速任务模式，跳过文档阶段，直接编码。

## 流程
1. 先阅读相关代码（不跳过阶段 0）
2. 直接编码修复
3. 运行测试验证
4. 输出 `[SAO:TASK_COMPLETE]` + 5 字段交接报告

## Vibe Coding 护栏

即使是小任务，也不允许：
- 不读代码就改代码（Blind Edit）
- 修改任务范围外的文件（Scope Creep）
- 跳过测试验证（必须至少运行一次）
- 吞掉异常或 TODO 标记（必须处理或明确报告）

10 分钟超时仍需汇报。
```

**项目定制规则** (`~/.sao/rules/sao-project.md`)——可以为特定项目定制：

```markdown
# SAO Project Development Rules

继承 default.md 全部规则，额外要求：

## 项目快照 (Project Snapshot)
- 语言: Python 3.11+, asyncio
- 包: sao/ (核心引擎 + experts/ + skills/ + channels/ + dashboard/)
- 启动: `python -m sao --channel feishu`
- 数据库: SQLite (aiosqlite, WAL mode)
- LLM: Qwen via DashScope API

## 编码约定
- 使用 Python 3.11+ 异步风格 (`async/await`)
- 所有新模块必须有 docstring
- 变量/函数用 `snake_case`，类用 `PascalCase`
- 优先使用 `pathlib.Path` 而非 `os.path`

## 文档联动
- 修改 core/ 下的文件时，必须更新 docs/design.md 中对应的模块说明
- 新增 Expert 时更新 docs/experts.md
- 新增 Skill 时更新 docs/skills.md

## 验证命令
- 测试: `python -m pytest tests/ -x -q`
- Lint: `ruff check sao/`
- 类型检查: `pyright sao/` (如有配置)

## 风险分级（Risk Tiers）
| Tier | 范围 | 要求 |
|---|---|---|
| **Low** | 文档/注释/测试 | 直接提交 |
| **Medium** | 非核心模块 (dashboard/experts) | 测试通过即可 |
| **High** | core/ / security/ / main.py | 必须写文档 + 全量测试 + diff 审查 |
```

#### 6.4.3 Rules 配置

在 `machines.yaml` 中为每个 workspace 指定 rules profile：

```yaml
machines:
  local:
    # ...
    workspaces:
      - name: sao
        path: "C:\\Users\\yiliu4\\code\\Super-Agent-OS"
        rules: sao-project              # → 加载 ~/.sao/rules/sao-project.md
      - name: web-app
        path: "C:\\Users\\yiliu4\\code\\my-web-app"
        rules: default                  # → 加载 ~/.sao/rules/default.md
      - name: hotfix-repo
        path: "C:\\Users\\yiliu4\\code\\hotfix"
        rules: quick                    # → 小项目用精简规则
```

未指定 rules 时，默认使用 `default`。

#### 6.4.4 Prompt 构建

SAO 将 rules + 用户任务 + 上下文组合成最终发给 IDE Agent 的 prompt：

```python
# sao/skills/programming/prompt_builder.py

def build_task_prompt(task: CodingTask, rules: str, context: dict) -> str:
    """构建发给 IDE Agent 的结构化 prompt"""
    return f"""
{rules}

---

# 当前任务

**Task ID**: {context['task_id']}
**项目**: {task.project}
**工作区**: {task.workspace_path}
**Git 分支**: {task.branch or '(当前分支)'}
**指定文件**: {', '.join(task.files) if task.files else '(自行判断)'}

## 任务描述

{task.task}

## 完成条件

- {'编码后运行测试' if task.test_after else '无需测试'}
- {'编码后运行项目' if task.run_after else '无需运行'}
- 持续工作 10 分钟未完成则输出 `[SAO:TIMEOUT_REPORT]`
- 完成后输出 `[SAO:TASK_COMPLETE]` 标记
"""
```

#### 6.4.5 SAO Agent 介入机制

IDE Agent 完成（或超时）后，SAO Agent 会收到结果并介入判断：

```
IDE Agent 输出
    │
    ├── 包含 [SAO:TASK_COMPLETE] ─────────────────────────┐
    │   │                                                 │
    │   ├── status=success + test=passed                  │
    │   │   → ✅ 直接报告飞书（附 diff + 测试结果）         │
    │   │                                                 │
    │   ├── status=success + test=failed                  │
    │   │   → 🔄 SAO 发修复任务给 IDE Agent（重试循环）     │
    │   │                                                 │
    │   ├── status=partial                                │
    │   │   → ⚠️ 报告飞书，让用户决定是否继续              │
    │   │                                                 │
    │   └── status=failed                                 │
    │       → ❌ 报告失败原因，让用户决定                   │
    │                                                     │
    ├── 包含 [SAO:TIMEOUT_REPORT] ────────────────────────┐
    │   → SAO Agent 读取进度文档                           │
    │   ├── 有明确进展 + 预计快完成                         │
    │   │   → 延长等待，通知飞书「进行中，预计 X 分钟」      │
    │   ├── 卡住了 / 无进展                               │
    │   │   → 飞书询问用户：继续等？还是我来分析？           │
    │   └── 达到全局超时 (30min)                           │
    │       → 强制终止 + 报告                              │
    │                                                     │
    └── 无标记（IDE Agent 异常退出）                       │
        → ❌ 报告错误 + 收集 stderr                        │
```

#### 6.4.6 Rules 继承与合并

```
项目级规则 (如 .cursorrules / AGENTS.md / CLAUDE.md)
    ▲  IDE Agent 自身读取，SAO 不干涉
    │
SAO Rules (~/.sao/rules/xxx.md)
    ▲  SAO 注入到任务 prompt 头部
    │
用户任务描述 (飞书消息)
    ▲  SAO Router 解析后注入
    │
最终 Prompt = [SAO Rules] + [Task] + [Constraints]
```

**优先级**：项目自身规则 > SAO Rules > 默认行为。SAO Rules 不会覆盖项目的 `.cursorrules` 等——它们是补充关系，SAO Rules 管流程（文档/超时/汇报），项目规则管代码风格。

#### 6.4.7 两层规则架构（Two-Layer Rules）

借鉴 ZeroClaw 的 CLAUDE.md (精简 ~50 行) + AGENTS.md (完整 ~500 行) 双层模式：

```
~/.sao/rules/
├── default.md              # 完整版（注入 IDE Agent prompt，~100 行）
├── default.slim.md         # 精简版（可选，仅核心流程指令，~20 行）
├── quick.md
├── quick.slim.md
├── sao-project.md
└── sao-project.slim.md
```

| 层 | 用途 | Token 数 |
|---|---|---|
| **slim** (精简版) | 注入 IDE Agent 的 system prompt 头部 | ~200-400 |
| **full** (完整版) | 放置在项目工作区 `AGENTS.md` 中，IDE Agent 自行读取 | ~800-1500 |

**加载策略**：
1. 如果 `xxx.slim.md` 存在 → prompt 注入 slim 版本，同时将 full 版本复制到项目工作区的 `AGENTS.md`
2. 如果 `xxx.slim.md` 不存在 → prompt 注入完整的 `xxx.md`（向后兼容）

**优点**：节省 IDE Agent 上下文窗口中的 token，完整规则通过 workspace 文件传递。

---

### 6.5 SubAgent Task 模型扩展

```python
# sao/subagent/models.py 中新增 hint 类型

class SubTaskHint(str, Enum):
    SKILL_DEV = "skill_dev"           # Forge 技能开发
    PROGRAMMING = "programming"       # IDE 编程任务
    RESEARCH = "research"             # 调研任务
    GENERAL = "general"               # 通用

# ProgrammingRunner 注册为 hint=programming 的 SubAgent 处理器
SUBAGENT_RUNNERS: dict[str, type] = {
    "skill_dev":    SkillDevRunner,     # Forge 技能开发
    "programming":  ProgrammingRunner,  # IDE 编程
    "general":      GeneralRunner,      # 通用
}
```

### 6.6 weight 机制 — Skill 声明数值轻重

SAO 主 Agent（CEO）需要知道哪些 Skill 走直调、哪些派 SubAgent（员工）盯着。
Skill 在 SKILL.toml 中声明 **数值 weight (1~10)**，根据预估耗时和流程复杂度设定：

| weight | 含义 | 调用方式 | 典型 Skill |
|---|---|---|---|
| **1~3** | 轻量，秒级返回，单次调用 | 主 Agent `_exec_skill()` 同步直调 | reminder (1), store_manager (2) |
| **4~6** | 中等，可能耗时较长但流程简单 | 视情况决定 | 未来的浏览器自动化技能 |
| **7~10** | 重量，分钟~小时级，多轮交互循环 | 主 Agent 派 SubAgent 异步盯着 | programming (9), forge (8) |

SAO 主仓库的 `BaseSkill` 根据 weight 提供 `requires_subagent` 属性：

```python
# SAO 主仓库 sao/skills/base.py
SUBAGENT_THRESHOLD = 5  # weight >= 5 派 SubAgent

class BaseSkill:
    @property
    def requires_subagent(self) -> bool:
        """weight >= 阈值时返回 True，SAO 派 SubAgent 盯着执行。"""
        return getattr(self, '_weight', 1) >= SUBAGENT_THRESHOLD

# SAO 主仓库 agent.py
async def _exec_skill(self, route):
    skill = self.registry.get(route.skill)
    if skill.requires_subagent:
        # CEO 派员工盯着
        task_id = await self.subagent_manager.delegate(skill, route)
        return f"🔧 任务已创建 (task-id: {task_id})"
    else:
        # CEO 自己直调
        return await skill.execute(route.tool, route.args, ctx)
```

> **约定**：weight 未声明时默认为 1（向后兼容，最轻量）。
> Skill 开发者根据自身执行特点设定 weight，SAO 不需要硬编码判断逻辑。

---

## 7. Skill 定义（SKILL.toml）

```toml
[skill]
name = "programming"
description = "在指定项目中使用本地 IDE/Agent 进行编程、测试、运行"
version = "1.0.0"
tags = ["开发", "编程", "IDE"]
weight = 9                              # 1~10，分钟~小时级 + 多轮交互循环 → 高 weight
builtin = true                          # 内置技能，非 TOML 沙箱执行

[[tools]]
name = "code"
description = "在指定项目中编写/修改代码"

[tools.args.task]
type = "string"
description = "编程任务的自然语言描述"
required = true

[tools.args.project]
type = "string"
description = "项目名称或路径"
required = false

[tools.args.files]
type = "string"
description = "需要修改的文件列表（逗号分隔）"
required = false

[tools.args.branch]
type = "string"
description = "Git 分支名（不指定则在当前分支）"
required = false

[[tools]]
name = "test"
description = "在指定项目中运行测试"

[tools.args.project]
type = "string"
description = "项目名称"
required = true

[tools.args.command]
type = "string"
description = "测试命令（如 pytest, npm test）"
required = false

[[tools]]
name = "run"
description = "在指定项目中运行/启动项目"

[tools.args.project]
type = "string"
description = "项目名称"
required = true

[tools.args.command]
type = "string"
description = "运行命令（如 python main.py, npm start）"
required = false

[[tools]]
name = "status"
description = "查看编程任务进度"

[tools.args.task_id]
type = "string"
description = "任务 ID"
required = false

[[tools]]
name = "diff"
description = "查看指定项目的当前代码变更"

[tools.args.project]
type = "string"
description = "项目名称"
required = true

# ─── 示例 ───

[[examples]]
user = "帮我在 sao 项目里重构 router 模块"
tool = "code"
args = { task = "重构 router 模块", project = "sao" }

[[examples]]
user = "运行一下 web-app 的测试"
tool = "test"
args = { project = "web-app" }

[[examples]]
user = "在 mac 上跑一下 ios-app"
tool = "run"
args = { project = "ios-app" }

[[examples]]
user = "编程任务进度怎么样了"
tool = "status"
args = {}

[[examples]]
user = "sao 项目改了什么"
tool = "diff"
args = { project = "sao" }
```

---

## 8. Router 集成

### 8.1 Router Prompt 注入

programming skill 在 Router 的 `<available_skills>` 中：

```xml
<skill name="programming" description="在指定项目中使用本地 IDE/Agent 进行编程、测试、运行">
  <tool name="code" description="编写/修改代码" args="task:string(required), project:string, files:string, branch:string"/>
  <tool name="test" description="运行测试" args="project:string(required), command:string"/>
  <tool name="run" description="运行项目" args="project:string(required), command:string"/>
  <tool name="status" description="查看编程任务进度" args="task_id:string"/>
  <tool name="diff" description="查看代码变更" args="project:string(required)"/>
</skill>
```

### 8.2 Router 输出示例

```json
// 编码任务（走 SubAgent）
{"route": "skill", "skill": "programming", "tool": "code",
 "resolved_query": "在 sao 项目中重构 router 模块",
 "args": {"task": "重构 router 模块，提取公共逻辑到基类", "project": "sao"}}

// 测试任务（走 SubAgent）
{"route": "skill", "skill": "programming", "tool": "test",
 "resolved_query": "运行 web-app 的测试",
 "args": {"project": "web-app"}}

// 运行项目（走 SubAgent）
{"route": "skill", "skill": "programming", "tool": "run",
 "resolved_query": "在 mac 上运行 ios-app",
 "args": {"project": "ios-app"}}

// 查看进度（同步，不走 SubAgent）
{"route": "skill", "skill": "programming", "tool": "status",
 "resolved_query": "查看编程任务进度",
 "args": {"task_id": "abc123"}}
```

> **注意**：`code` / `test` / `run` 走 SubAgent（异步），`status` / `diff` 同步返回。

---

## 9. 飞书交互卡片

### 9.1 任务创建通知

```
🔧 编程任务已创建
┌─────────────────────────────────────┐
│ Task ID: abc123                     │
│ 项目: sao (local)                    │
│ IDE: VS Code + Copilot Agent        │
│ 任务: 重构 router 模块               │
│ 状态: ⏳ 进行中                      │
│                                     │
│ [📋 查看进度]  [❌ 取消任务]          │
└─────────────────────────────────────┘
```

### 9.2 进度更新

```
🔄 编程进度更新 (abc123)
┌─────────────────────────────────────┐
│ 项目: sao                           │
│ 阶段: 编码完成 → 正在运行测试         │
│ 已修改: 3 个文件, +45 / -12 行       │
│ 耗时: 2m 30s                        │
└─────────────────────────────────────┘
```

### 9.3 任务完成通知

```
✅ 编程任务完成 (abc123)
┌──────────────────────────────────────────┐
│ 项目: sao | 耗时: 3m 15s                 │
│                                          │
│ 📝 摘要:                                 │
│   重构了 router.py，提取了 BaseRouter     │
│   基类，3 个子路由继承实现                  │
│                                          │
│ 📊 变更: 5 files, +120 / -80 lines       │
│ 🧪 测试: 42 passed, 0 failed ✅          │
│                                          │
│ [📄 查看 Diff] [🔄 继续修改] [✅ 提交]    │
└──────────────────────────────────────────┘
```

### 9.4 测试失败通知

```
⚠️ 编程任务需要关注 (abc123)
┌──────────────────────────────────────────┐
│ 项目: sao | 已尝试: 3/3 轮自动修复        │
│                                          │
│ 🧪 测试仍有 2 个失败:                     │
│   FAIL test_router.py::test_delegate     │
│   FAIL test_router.py::test_fallback     │
│                                          │
│ 📄 错误摘要:                              │
│   AttributeError: 'NoneType' has no      │
│   attribute 'route'                      │
│                                          │
│ [🔧 让 Agent 继续修] [📄 查看详情]        │
│ [✋ 我来手动修]       [❌ 放弃]            │
└──────────────────────────────────────────┘
```

---

## 10. 文件结构

```
sao/skills/programming/
├── __init__.py              # ProgrammingSkill 类（入口）
├── skill.py                 # 主逻辑（解析 project → adapter → SubAgent）
├── models.py                # CodingTask, CodingResult, MachineConfig, etc.
├── config.py                # 加载 ~/.sao/machines.yaml
├── runner.py                # ProgrammingRunner (SubAgent Task 执行器)
├── connector.py             # LocalConnector
└── adapters/
    ├── __init__.py          # ADAPTERS 注册表
    ├── base.py              # IDEAdapter 抽象基类
    ├── vscode.py            # VS Code + Copilot Adapter
    ├── antigravity.py       # Antigravity Adapter
    └── cli_agent.py         # 通用 CLI Agent Adapter
```

---

## 11. 与 Forge 的关系

| 维度 | Programming Skill | Forge Skill |
|---|---|---|
| **目标** | 在已有项目中编程 | 从零创建 SAO 技能 |
| **输入** | 任务描述 + 项目名 | 技能需求描述 |
| **输出** | 代码变更 (diff/commit) | SKILL.toml + main.py |
| **代码位置** | 用户的真实项目 | **SAO-Store 仓库 skills/ 子目录** |
| **执行者** | 本地 IDE Agent | SAO LLM 直接生成 |
| **环境** | 用户的真实项目 | SAO 沙箱 |
| **审批** | 可选（commit 前确认） | 必须（部署前审批） |
| **复杂度** | 高（真实项目、多文件） | 中（独立小型技能） |

**组件仓库约定**：

可共享的技能和专家统一放在 **SAO-Store** 仓库中（`git@github.com:Selene1225/SAO-Store.git`），按类型分目录：

```
# 本地路径: C:\Users\yiliu4\code\SAO-Store
SAO-Store/
├── skills/                       # ── 技能（pip 包）──
│   ├── sao-skill-reminder/       # 提醒技能
│   │   ├── SKILL.toml
│   │   ├── pyproject.toml        # pip install -e skills/sao-skill-reminder/
│   │   └── sao_skill_reminder/
│   │       ├── __init__.py
│   │       └── skill.py
│   └── sao-skill-{name}/         # 后续新增技能
│       └── ...
└── experts/                      # ── 专家（TOML 配置）──
    ├── weather.toml
    ├── search.toml
    └── ...
```

好处：
- 技能 + 专家在一个仓库统一管理、统一 CI/CD
- Skill 是独立 pip 包，可单独安装；Expert 是 TOML 配置，复制即用
- 其他用户 `git clone` 后按需安装
- 与 Marketplace (`sao-skill-*` / `sao-expert-*` 命名约定) 天然兼容

**协作场景**：Forge 可以调用 Programming Skill 来处理复杂技能开发：

```
用户: "帮我开发一个 A 股监控技能"
  └── Router → Forge (创建技能)
      └── Forge 发现需求复杂（涉及多个文件、需要真实 API 测试）
          └── Forge 在 SAO-Store/skills/ 中创建 sao-skill-stock-monitor/ 子目录
              └── Forge 委派给 Programming Skill
                  └── Programming Skill 在 IDE 中开发
                      └── 完成后 Forge 接管做 TOML 包装 + 部署审批
```

---

## 12. 安全考虑

### 12.1 为什么不用 Docker 容器？

| 维度 | Docker 沙箱（TOML/Forge 技能用） | IDE Agent 编程 |
|---|---|---|
| **执行者** | SAO 运行用户脚本 | 用户已有的 IDE Agent (Copilot/Claude Code) |
| **信任等级** | 不信任（第三方脚本） | **半信任**（用户订阅的工具，在用户机器上运行） |
| **容器可行性** | ✓ 脚本可沙箱化 | ✗ IDE Agent 需访问真实文件系统、Git、终端 |
| **安全责任** | SAO 兜底 | IDE Agent 产品自身负责 + SAO Rules 补充 |

**核心结论**：编程任务的「沙箱」不是 Docker 容器，而是 **Git 分支隔离 + Rules 行为约束 + SAO 审查**。

### 12.2 三层安全模型

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: Git 分支隔离                                │
│    ├── 所有编程任务在独立分支 (sao/task-{id}) 上执行    │
│    ├── 完成前不合并到主分支                             │
│    └── 失败可随时丢弃分支，零影响                       │
├─────────────────────────────────────────────────────┤
│  Layer 2: Rules 行为约束                              │
│    ├── 禁止操作清单（见 §12.3）                        │
│    ├── 文件作用域限制（只允许 workspace 内）             │
│    └── 反模式检测（见 §6.4.2 反模式表格）               │
├─────────────────────────────────────────────────────┤
│  Layer 3: SAO 审查                                    │
│    ├── 交接报告解析（5 字段 Handoff）                   │
│    ├── diff 审查（变更范围 vs 任务范围）                 │
│    ├── 测试结果验证                                    │
│    └── 用户最终确认（飞书卡片 [✅提交] [❌放弃]）       │
└─────────────────────────────────────────────────────┘
```

### 12.3 IDE Agent 禁止操作

以下操作在 Rules 中**明确声明禁止**，IDE Agent 不得执行：

| 类别 | 禁止行为 |
|---|---|
| **凭证** | 修改 .env / secrets 文件；硬编码 API Key/密码 |
| **破坏性** | `rm -rf` / `del /s /q` 等批量删除；`git push --force`；`git rebase` 改历史 |
| **系统级** | 安装系统软件包（apt/choco）；修改 SSH 配置/密钥 |
| **越权** | 访问 workspace 外的文件；修改 `~/.sao/secrets.db` |
| **网络** | 启动新的网络监听/端口扫描；发送 HTTP 请求到非项目 API |

### 12.4 需确认操作

以下操作 IDE Agent 可以提出意图，但 SAO 需中转确认：

| 操作 | SAO 处理 |
|---|---|
| 安装新 pip/npm 依赖 | SAO 检查包名合法性 → 飞书确认 |
| 删除文件（非内容修改） | SAO 检查是否在任务范围内 → 自动/手动确认 |
| 修改数据库 schema | SAO 检查是否有迁移脚本 → 飞书确认 |
| 创建新的网络服务/端口 | SAO 检查端口合法性 → 飞书确认 |

### 12.5 风险矩阵

| 风险 | 缓解 |
|---|---|
| SSH 私钥暴露 | 不适用（本地执行，无 SSH） |
| IDE Agent 执行恶意代码 | Git 分支隔离 + 用户审批 + diff 审查 + 自动回滚 |
| 任务注入（通过 task 描述） | task 描述经 scrubber 过滤 + IDE Agent 自身安全机制 |
| 无限循环修复 | `MAX_FIX_ATTEMPTS=3` 硬上限 |
| 长时间占用资源 | 全局超时（默认 30 分钟）+ 用户可随时取消 |
| Scope Creep（越界修改） | diff 审查: 变更文件 vs 任务描述，SAO 检查不一致时告警 |
| 依赖投毒 | 新依赖安装需确认 + 包名合法性校验 |

### 12.6 SAO Diff 审查逻辑

任务完成后，SAO 对 `git diff` 进行自动审查：

```python
async def review_diff(task: CodingTask, diff: str) -> ReviewResult:
    """SAO 自动审查 IDE Agent 的代码变更"""
    issues = []

    # 1. Scope 检查: 变更的文件是否在任务描述相关范围内
    changed_files = parse_diff_files(diff)
    if task.files:
        unexpected = set(changed_files) - set(task.files)
        if unexpected:
            issues.append(f"Scope Creep: 修改了任务范围外的文件: {unexpected}")

    # 2. 禁止文件检查
    FORBIDDEN_PATTERNS = [".env", "secrets", "id_rsa", "*.pem", "*.key"]
    for f in changed_files:
        if any(fnmatch(f, p) for p in FORBIDDEN_PATTERNS):
            issues.append(f"Security: 修改了禁止文件: {f}")

    # 3. 敏感内容检查
    SECRET_PATTERNS = [r'(?i)(api[_-]?key|password|secret)\s*=\s*["\'][^"\']+']
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, diff):
            issues.append("Security: diff 中可能包含硬编码的凭证")

    # 4. 破坏性命令检查
    DANGEROUS = ["rm -rf", "del /s", "DROP TABLE", "TRUNCATE", "format "]
    for cmd in DANGEROUS:
        if cmd in diff:
            issues.append(f"Danger: diff 中包含危险命令: {cmd}")

    return ReviewResult(
        passed=len(issues) == 0,
        issues=issues,
        recommendation="auto_commit" if not issues else "human_review"
    )
```

---

## 13. 配置示例 (.env)

```bash
# Programming Skill 配置
SAO_MACHINES_CONFIG=~/.sao/machines.yaml     # 机器配置文件路径
SAO_PROGRAMMING_TIMEOUT=1800                  # 全局超时（秒），默认 30 分钟
SAO_PROGRAMMING_MAX_FIX_ATTEMPTS=3            # 自动修复最大重试次数
SAO_PROGRAMMING_POLL_INTERVAL=10              # 轮询间隔（秒）
```

---

## 14. 实现路线

### Phase A: 基础框架 (MVP)

```
1. models.py             — CodingTask, CodingResult, MachineConfig
2. config.py             — 加载 machines.yaml
3. connector.py          — LocalConnector (仅本地)
4. adapters/base.py      — IDEAdapter 基类
5. adapters/cli_agent.py — 通用 CLI Agent Adapter (最通用)
6. runner.py             — ProgrammingRunner (SubAgent 执行器)
7. skill.py              — ProgrammingSkill 主入口
8. __init__.py           — 注册
```

**MVP 验收**：飞书说 "帮我在 sao 项目里加个 health check 接口"，
SAO 在本机打开 VS Code，通过 CLI Agent（如 Claude Code）完成编码，
飞书收到结果通知。

### Phase B: 多 IDE + 进度推送

```
9.  adapters/vscode.py   — VS Code + Copilot Adapter
10. adapters/antigravity.py — Antigravity Adapter
11. 进度推送             — 飞书交互卡片
```

### Phase C: 高级功能

```
12. 自动修复循环          — 测试失败 → 自动修复 → 重测
13. Git 操作             — 自动创建分支/commit/PR
14. 多任务并行           — 同时在不同项目上编程
```

---

## 15. 用户使用示例

```
[飞书] 帮我在 sao 项目里给 dashboard 加个实时日志推送功能

[SAO]  🔧 编程任务已创建 (task-id: p-7a3b)
       📍 项目: sao | IDE: VS Code + Copilot
       ⏳ 正在编码中...

[SAO]  🔄 进度: 已修改 2 个文件 (+38 行), 正在运行测试...

[SAO]  ✅ 编程完成 (task-id: p-7a3b) | 耗时: 4m 12s
       📝 新增了 WebSocket 推送 + 前端实时日志面板
       📊 3 files, +85 / -5 lines
       🧪 15 tests passed ✅
       [📄 查看 Diff] [✅ 提交] [❌ 放弃]

[飞书] 在 mac 上测一下 ios-app

[SAO]  🧪 测试任务已创建 (task-id: t-9c2d)
       📍 项目: ios-app | 机器: mac-studio | IDE: Antigravity
       ⏳ 正在运行测试...

[SAO]  ✅ 测试完成 (t-9c2d) | 耗时: 1m 30s
       🧪 128 tests: 126 passed, 2 skipped, 0 failed ✅

[飞书] 看看 sao 项目现在改了什么

[SAO]  📄 sao 项目当前未提交变更:
       M  sao/dashboard/server.py     (+38 -2)
       M  sao/dashboard/static/index.html (+42 -3)
       A  sao/dashboard/ws.py         (+25)
```
