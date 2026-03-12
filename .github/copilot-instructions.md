# SAO-Store 开发规范

> 本文件供 IDE AI 助手（GitHub Copilot / Cursor / Claude Code 等）在编码时参考。
> 也适用于 SAO Agent 的 Programming Skill SubAgent。

## 仓库概述

SAO-Store 是 Super-Agent-OS（SAO）的组件仓库，包含两类组件：

- **Skill**（技能）：Python pip 包，继承 `BaseSkill`，通过 `execute(tool, args, ctx)` 执行具体操作
- **Expert**（专家）：TOML 配置文件，定义 System Prompt + 搜索开关 + 温度，无代码

## Skill 开发规范

### 文件结构（必须）

```
skills/sao-skill-{name}/
├── SKILL.toml                    # 元数据 + tools + examples + instructions
├── pyproject.toml                # pip 包配置 + entry-points + pytest config
├── sao_skill_{name}/
│   ├── __init__.py               # 导出 XxxSkill
│   └── skill.py                  # 实现 BaseSkill 子类
└── tests/
    ├── __init__.py
    └── test_skill.py             # 单元测试（必须通过才能上线）
```

### SKILL.toml 必须包含

- `[skill]`: name, version, description (≤30字), weight (1-10)
- `[skill.requires]`: sao 版本 + env/bins/features gating 字段
- `[[tools]]`: 每个 tool 有 name + description + args
- `[[examples]]`: 至少 2 个，不超过 4 个
- `[skill.instructions]`: SubAgent 工作流指令（weight ≥ 5 必填）

### Python 代码规范

- 继承 `sao.skills.BaseSkill`
- `__init__(self, ctx: SkillContext)` — 从 ctx 获取资源，不做 IO
- `execute(self, tool, args, ctx)` — 用 dict dispatch handler
- 所有 handler 方法命名: `_handle_{tool_name}`
- 参数校验放在 handler 开头，缺参直接返回 `⚠️` 提示
- 异步用 `async/await`，不阻塞事件循环
- 外部命令用 `asyncio.create_subprocess_shell` + timeout
- 路径操作必须做穿越防护（`_safe_path` 模式）
- 类型注解: Python 3.11+, `from __future__ import annotations`

### pyproject.toml 必须包含

```toml
[project.entry-points."sao.skills"]
{name} = "sao_skill_{name}:{Name}Skill"

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-asyncio>=0.21"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### 单元测试规范（上线前必须通过）

| 测试类型 | 说明 |
|----------|------|
| 参数校验 | 每个 tool 的缺参/空参/非法参数 |
| 路由分发 | `execute()` 路由到所有 tool + 未知 tool 返回警告 |
| 核心逻辑 | 纯函数/工具方法的单元测试 |
| 成功路径 | mock 外部依赖后的正常流程 |
| 安全防护 | 路径穿越、危险命令拦截等（如适用） |

外部依赖（`sao.*`、`lark_oapi` 等）通过 `sys.modules.setdefault()` mock，无需安装即可测试。

运行测试:

```bash
python -m pytest skills/sao-skill-{name}/tests/ -v
```

### weight 规则

| 范围 | 说明 | 调用方式 |
|------|------|----------|
| 1-3 | 轻量（秒级，单次调用） | 主 Agent 同步直调 |
| 4-6 | 中等 | 视情况决定 |
| 7-10 | 重量（分钟~小时，多轮交互） | SubAgent 异步管理 |

## Expert 开发规范

### 文件格式

```toml
[expert]
name = "{name}"                    # Router chat_mode 匹配值
version = "1.0.0"
description = "..."                # ≤ 20 字
search = true/false                # 联网搜索
temperature = 0.3                  # 0.0 ~ 1.0

[expert.requires]                  # 可选
features = ["dashscope_search"]    # 功能开关

[expert.system_prompt]
text = "..."                       # 专注领域行为和格式
```

### description 原则

- ≤ 20 字，不说"覆盖"，用具体场景词
- 高频触发词放前面（Router 靠关键词语义匹配）

## Git 提交规范

- feat: 新功能（`feat: add xxx skill`）
- fix: 修复
- refactor: 重构无功能变化
- test: 测试相关
- docs: 文档

## 注意事项

- 不要在 Python 代码中定义 tools，统一在 SKILL.toml 声明
- description 要精简，消耗 Router prompt token 预算
- `[skill.requires]` 的 env/bins/features 用于 SAO 加载时 gating 检查
- Expert 无需代码，纯 TOML 配置
