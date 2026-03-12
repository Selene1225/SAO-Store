# SAO 集成指南 — 如何安装和使用 Skill / Expert

> 本文档面向 SAO 主仓库（Super-Agent-OS），说明如何从 SAO-Store 发现、安装、加载和调用 Skill 与 Expert。
>
> SAO-Store 仓库: `git@github.com:Selene1225/SAO-Store.git`

---

## 目录

1. [概念总览](#1-概念总览)
2. [Skill 安装与加载](#2-skill-安装与加载)
3. [Expert 安装与加载](#3-expert-安装与加载)
4. [SKILL.toml 规范](#4-skilltoml-规范)
5. [Expert TOML 规范](#5-expert-toml-规范)
6. [Skill 调用接口](#6-skill-调用接口)
7. [Weight 路由机制](#7-weight-路由机制)
8. [完整示例: Reminder Skill](#8-完整示例-reminder-skill)
9. [完整示例: Weather Expert](#9-完整示例-weather-expert)
10. [速查清单](#10-速查清单)

---

## 1. 概念总览

SAO-Store 提供两种组件：

| 组件 | 本质 | 安装方式 | 运行方式 | 适用场景 |
|------|------|----------|----------|----------|
| **Skill** | Python pip 包 | `pip install -e` | SAO 实例化类 → 调用 `execute()` | 需要代码逻辑 + 外部 API 调用 |
| **Expert** | TOML 配置文件 | 复制到 `~/.sao/experts/` | SAO 读取 prompt/search/temperature → 直接喂给 LLM | 只需定制 System Prompt + 搜索策略 |

**核心区别**：Skill 有代码执行，Expert 只是 LLM 参数配置。

---

## 2. Skill 安装与加载

### 2.1 安装

```bash
# 方式 1: 本地开发模式（修改即时生效）
pip install -e SAO-Store/skills/sao-skill-reminder/

# 方式 2: 从 GitHub 直接安装
pip install "sao-skill-reminder @ git+https://github.com/Selene1225/SAO-Store.git#subdirectory=skills/sao-skill-reminder"
```

### 2.2 发现机制 — Entry Points

Skill 通过 Python entry points 注册，SAO 启动时自动发现。

每个 Skill 的 `pyproject.toml` 声明 entry point：

```toml
[project.entry-points."sao.skills"]
reminder = "sao_skill_reminder:ReminderSkill"
#  ↑ 技能名     ↑ 模块路径:类名
```

**SAO 侧加载代码**：

```python
from importlib.metadata import entry_points

def discover_skills() -> dict[str, type]:
    """扫描所有已安装的 sao.skills entry points。"""
    skills = {}
    for ep in entry_points(group="sao.skills"):
        skill_cls = ep.load()           # 动态 import 得到类
        skills[ep.name] = skill_cls     # ep.name = "reminder"
    return skills

# 结果: {"reminder": <class ReminderSkill>}
```

### 2.3 读取 SKILL.toml

每个 Skill pip 包内含一个 `SKILL.toml`，是该技能的元数据单一真相源。

**SKILL.toml 位置**：与 `pyproject.toml` 同级目录。

```python
import tomllib
from pathlib import Path
from importlib.metadata import distribution

def load_skill_toml(skill_name: str) -> dict:
    """从已安装的 Skill 包中读取 SKILL.toml。"""
    dist = distribution(f"sao-skill-{skill_name}")
    # dist._path 指向包的 .dist-info 目录
    # SKILL.toml 在包的根目录（与 pyproject.toml 同级）
    package_dir = Path(dist._path).parent
    toml_path = package_dir / "SKILL.toml"
    
    # 如果是 editable install，从源码目录读取
    if not toml_path.exists():
        # 通过 entry point 反查源码位置
        for ep in entry_points(group="sao.skills"):
            if ep.name == skill_name:
                module = ep.load()
                source_dir = Path(module.__file__).parent.parent
                toml_path = source_dir / "SKILL.toml"
                break
    
    with open(toml_path, "rb") as f:
        return tomllib.load(f)
```

### 2.4 实例化 Skill

所有 Skill 统一接收 `SkillContext`：

```python
from sao.skills import SkillContext

# 构建 SkillContext（SAO 框架层准备）
ctx = SkillContext(
    lark_client=lark_client,     # 飞书 SDK 客户端
    channel=feishu_channel,      # 消息通道（用于发送即时回复）
    chat_id=chat_id,             # 当前会话 ID
    sender_id=sender_id,         # 发送者 ID
)

# 实例化
skill_cls = discovered_skills["reminder"]   # type: ReminderSkill
skill_instance = skill_cls(ctx)             # __init__(self, ctx: SkillContext)
```

**约定**：每个 Skill 的构造函数签名固定为 `__init__(self, ctx: SkillContext)`。Skill 从 ctx 中获取所需资源（如 `ctx.lark_client`），不直接接收具体依赖。

### 2.5 注册到 Router Prompt

从 SKILL.toml 提取 tools + examples，注入 Router 的 system prompt，使 LLM 知道有哪些技能可用：

```python
def build_router_skill_prompt(skill_toml: dict) -> str:
    """从 SKILL.toml 生成 Router 可理解的技能描述。"""
    skill = skill_toml["skill"]
    lines = [f"## Skill: {skill['name']}"]
    lines.append(f"描述: {skill['description']}")
    lines.append(f"weight: {skill['weight']}")
    lines.append("")
    
    # Tools
    for tool in skill_toml.get("tools", []):
        args_desc = ""
        if "args" in tool:
            args_parts = []
            for arg_name, arg_def in tool["args"].items():
                req = "必填" if arg_def.get("required") else "可选"
                args_parts.append(f"{arg_name}({arg_def['type']}, {req}): {arg_def['description']}")
            args_desc = " | ".join(args_parts)
        lines.append(f"- tool: {tool['name']} — {tool['description']}")
        if args_desc:
            lines.append(f"  args: {args_desc}")
    
    # Examples（帮助 Router 理解意图映射）
    examples = skill_toml.get("examples", [])
    if examples:
        lines.append("")
        lines.append("示例:")
        for ex in examples:
            lines.append(f'  用户: "{ex["user"]}" → tool={ex["tool"]}')
    
    return "\n".join(lines)
```

---

## 3. Expert 安装与加载

### 3.1 安装

```bash
# 复制 TOML 到 SAO 配置目录
cp SAO-Store/experts/weather.toml ~/.sao/experts/

# 或批量安装所有 Expert
cp SAO-Store/experts/*.toml ~/.sao/experts/
```

### 3.2 发现与加载

```python
import tomllib
from pathlib import Path
from dataclasses import dataclass

@dataclass
class ChatExpert:
    name: str
    description: str
    system: str          # System Prompt
    search: bool         # 是否开启联网搜索
    temperature: float   # LLM 温度

def load_experts(experts_dir: Path = Path.home() / ".sao" / "experts") -> dict[str, ChatExpert]:
    """扫描 ~/.sao/experts/*.toml，加载所有 Expert。"""
    experts = {}
    for toml_path in experts_dir.glob("*.toml"):
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        
        e = data["expert"]
        expert = ChatExpert(
            name=e["name"],
            description=e["description"],
            system=e["system_prompt"]["text"],
            search=e.get("search", False),
            temperature=e.get("temperature", 0.7),
        )
        experts[expert.name] = expert
    
    return experts

# 结果: {"general": ChatExpert(...), "weather": ChatExpert(...), ...}
```

### 3.3 Router 分流

Router 输出 `chat_mode` 字段，Agent 据此选择 Expert：

```python
async def exec_chat(self, route: dict, message: str):
    mode = route.get("chat_mode", "general")
    expert = self.experts.get(mode, self.experts["general"])  # fallback → general
    
    response = await self.llm.chat(
        system_prompt=expert.system,
        message=message,
        enable_search=expert.search,
        temperature=expert.temperature,
    )
    return response
```

---

## 4. SKILL.toml 规范

SKILL.toml 是每个 Skill 的**唯一元数据来源**。Python 代码中不再定义 tools，只实现 `execute()`。

```toml
# ── 基本信息 ──
[skill]
name = "reminder"                    # 技能名（全局唯一）
version = "1.0.0"
description = "管理提醒/闹钟..."      # 给 Router 看的一句话描述
author = "Selene"
weight = 1                           # 1~10 数值，越大越重
                                     # 1~3: 轻量，主 Agent 同步直调
                                     # 4~6: 中等，视情况决定
                                     # 7~10: 重量，SubAgent 异步盯着

[skill.requires]                     # 运行时依赖声明 (可选)
sao = ">=2.0.0"
feishu_bitable = true

# ── Tools 定义 ──
[[tools]]
name = "set"                         # tool 名（传给 execute 的第一个参数）
description = "创建新提醒/闹钟"

[tools.args.content]                 # 参数定义
type = "string"
required = true
description = "提醒内容"

[tools.args.remind_time]
type = "string"
required = true
description = "提醒时间，格式 YYYY-MM-DD HH:mm"

[[tools]]
name = "list"
description = "查看当前待执行的提醒列表"
# 无参数的 tool 不需要 [tools.args.*]

# ── 示例（帮助 Router 理解意图映射）──
[[examples]]
user = "3月10号下午3点提醒我开会"
tool = "set"
args = { content = "开会", remind_time = "2026-03-10 15:00" }

[[examples]]
user = "查看我的提醒"
tool = "list"
```

### 关键字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `skill.name` | ✅ | 全局唯一标识，匹配 entry point 名 |
| `skill.weight` | ✅ | 1~10 数值，决定调用路径（见第 7 节） |
| `skill.description` | ✅ | 注入 Router prompt 的描述 |
| `[[tools]]` | ✅ | tool 列表（name + description + args） |
| `[[examples]]` | 推荐 | 帮助 Router 正确映射用户意图 |
| `skill.requires` | 可选 | 运行时环境要求 |

---

## 5. Expert TOML 规范

```toml
[expert]
name = "weather"                          # Expert 名（Router 用 chat_mode 匹配）
version = "1.0.0"
description = "天气查询专家"               # 人类可读描述
search = true                             # 是否让 LLM 开启联网搜索
temperature = 0.3                         # LLM 温度

[expert.system_prompt]
text = """\
你是 SAO 天气专家。根据搜索结果回复天气，严格使用以下卡片格式...
"""
```

### 关键字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `expert.name` | ✅ | 唯一标识，Router `chat_mode` 用这个值匹配 |
| `expert.search` | ✅ | `true` 开启 DashScope 联网搜索 |
| `expert.temperature` | ✅ | 事实型低 (0.2~0.3)，创意型高 (0.7~0.9) |
| `expert.system_prompt.text` | ✅ | 专属 System Prompt，专注领域行为和格式 |

---

## 6. Skill 调用接口

### 6.1 BaseSkill 基类

```python
# sao/skills/base.py（SAO 主仓库提供）

class BaseSkill(ABC):
    """所有 Skill 的基类。"""
    name: str           # 技能标识
    description: str    # 技能描述

    @abstractmethod
    def __init__(self, ctx: SkillContext) -> None:
        """统一构造函数。Skill 从 ctx 获取所需资源。"""
        ...

    @abstractmethod
    async def execute(self, tool: str, args: dict[str, Any], ctx: SkillContext) -> str | None:
        """执行一个 tool。
        
        Args:
            tool: SKILL.toml 中定义的 tool name（如 "set", "list"）
            args: Router 解析出的参数 dict（如 {"content": "开会", "remind_time": "..."})
            ctx:  运行时上下文（可用于发送中间消息等）
        
        Returns:
            文本结果（发给用户），或 None（Skill 自己已通过 ctx.channel 发送）
        """
        ...

    @property
    def requires_subagent(self) -> bool:
        """根据 SKILL.toml 的 weight 决定是否需要 SubAgent。
        SAO 框架层从 SKILL.toml 读取 weight，设置此属性。
        Skill 自身不需要关心这个。
        """
        ...
```

### 6.2 SkillContext

```python
@dataclass
class SkillContext:
    """Skill 运行时上下文 — 统一注入所有依赖。"""
    lark_client: Any        # 飞书 SDK 客户端
    channel: Any            # 消息通道（send 方法发消息到飞书）
    chat_id: str            # 当前会话 ID
    sender_id: str | None   # 发送者 ID（可选）
```

### 6.3 调用流程

```python
# SAO Agent 执行 Skill 的核心逻辑

async def handle_skill_route(self, route: dict, ctx: SkillContext):
    skill_name = route["skill"]    # "reminder"
    tool_name = route["tool"]      # "set"
    args = route.get("args", {})   # {"content": "开会", "remind_time": "..."}
    
    # 1. 查找已注册的 Skill 实例
    skill = self.skill_registry[skill_name]
    
    # 2. 检查 weight → 决定直调 or SubAgent
    toml = self.skill_tomls[skill_name]
    weight = toml["skill"]["weight"]
    
    if weight < 5:
        # 轻量：主 Agent 同步直调
        result = await skill.execute(tool_name, args, ctx)
        if result:
            await ctx.channel.send(ctx.chat_id, result)
    else:
        # 重量：派 SubAgent 盯着
        task = await self.subagent_manager.create(skill, tool_name, args, ctx)
        await ctx.channel.send(ctx.chat_id, f"🔧 任务已创建 (task-id: {task.id})")
```

---

## 7. Weight 路由机制

SKILL.toml 中的 `weight` 字段（1~10）决定 SAO 的调用策略：

```
              weight
    1 ─────── 3 ─────── 5 ─────── 7 ─────── 10
    │         │         │         │          │
    └── 轻量 ──┘    阈值线     └── 重量 ────┘
    主Agent直调     SUBAGENT_THRESHOLD=5    SubAgent盯着
    秒级同步                                 分钟~小时级异步
```

| weight 范围 | 分类 | 调用方式 | 典型场景 |
|-------------|------|----------|----------|
| 1~3 | 轻量 | 主 Agent 同步直调 `execute()` | 提醒 CRUD、查天气、翻译 |
| 4~6 | 中等 | 视具体情况决定 | 复杂搜索、数据分析 |
| 7~10 | 重量 | SubAgent 异步盯着执行 | 编程任务、技能锻造 |

**判断逻辑**：

```python
SUBAGENT_THRESHOLD = 5

def requires_subagent(weight: int) -> bool:
    return weight >= SUBAGENT_THRESHOLD
```

### `requires_subagent` 属性

SAO 框架在加载 Skill 时，从 SKILL.toml 读取 weight 并设置 `requires_subagent` 属性：

```python
skill.requires_subagent = (toml["skill"]["weight"] >= SUBAGENT_THRESHOLD)
```

Router 或 Agent 可直接检查：

```python
if skill.requires_subagent:
    # 派 SubAgent
else:
    # 主 Agent 直调
```

---

## 8. 完整示例: Reminder Skill

### SAO-Store 中的文件结构

```
SAO-Store/skills/sao-skill-reminder/
├── SKILL.toml                    # 元数据 + tools + examples + weight
├── pyproject.toml                # pip 包定义 + entry points
└── sao_skill_reminder/
    ├── __init__.py               # 导出 ReminderSkill
    └── skill.py                  # 实现 BaseSkill
```

### SAO 侧完整流程

```
1. 安装
   $ pip install -e SAO-Store/skills/sao-skill-reminder/

2. 启动时发现
   entry_points(group="sao.skills") → {"reminder": ReminderSkill}

3. 读取 SKILL.toml
   weight=1, tools=[set, list, update, cancel], examples=[...]

4. 实例化
   ctx = SkillContext(lark_client=..., channel=..., chat_id=..., sender_id=...)
   skill = ReminderSkill(ctx)

5. 注入 Router prompt
   "Skill: reminder — 管理提醒/闹钟，tools: set/list/update/cancel ..."

6. 用户消息: "3月10号下午3点提醒我开会"
   Router → {"route":"skill", "skill":"reminder", "tool":"set",
             "args":{"content":"开会", "remind_time":"2026-03-10 15:00"}}

7. 检查 weight=1 < 5 → 主 Agent 直调
   result = await skill.execute("set", {"content":"开会", ...}, ctx)

8. 返回结果
   "✅ 提醒已创建\n📝 内容: 开会\n⏰ 时间: 2026-03-10 15:00\n🔖 状态: 待执行"
```

---

## 9. 完整示例: Weather Expert

### SAO-Store 中的文件

```
SAO-Store/experts/weather.toml
```

### TOML 内容

```toml
[expert]
name = "weather"
version = "1.0.0"
description = "天气查询专家"
search = true
temperature = 0.3

[expert.system_prompt]
text = """\
你是 SAO 天气专家。根据搜索结果回复天气，严格使用以下卡片格式...
"""
```

### SAO 侧完整流程

```
1. 安装
   $ cp SAO-Store/experts/weather.toml ~/.sao/experts/

2. 启动时加载
   load_experts() → {"weather": ChatExpert(name="weather", search=True, ...)}

3. 注入 Router prompt
   "Expert: weather — 天气查询专家（chat_mode='weather'）"

4. 用户消息: "北京天气怎么样"
   Router → {"route":"chat", "chat_mode":"weather", "needs_search":true,
             "resolved_query":"北京天气"}

5. Agent 选择 Expert
   expert = experts["weather"]

6. 调用 LLM
   llm.chat(system=expert.system, enable_search=True, temperature=0.3)

7. 返回结果（卡片格式）
   🌤 **北京** 天气参考
   🌡 温度: 12°C
   ☁ 天气: 晴
   ...
```

---

## 10. 速查清单

### Skill 集成清单

- [ ] `pip install -e SAO-Store/skills/sao-skill-{name}/`
- [ ] `entry_points(group="sao.skills")` 自动发现
- [ ] 读取 `SKILL.toml` → 获取 weight、tools、examples
- [ ] 用 `SkillContext` 实例化 → `SkillCls(ctx)`
- [ ] 提取 tools/examples → 注入 Router prompt
- [ ] 检查 `weight >= 5` → 决定直调 or SubAgent
- [ ] 调用 `skill.execute(tool, args, ctx)` → 获取文本结果

### Expert 集成清单

- [ ] `cp SAO-Store/experts/{name}.toml ~/.sao/experts/`
- [ ] 启动时扫描 `~/.sao/experts/*.toml`
- [ ] 解析为 `ChatExpert(name, system, search, temperature)`
- [ ] Router 输出 `chat_mode` → 匹配 Expert
- [ ] Fallback: 未知 mode → `general`
- [ ] 用 Expert 的 system/search/temperature 调用 LLM

### 当前已实现组件

| 组件 | 类型 | 状态 | 位置 |
|------|------|------|------|
| reminder | Skill (weight=1) | ✅ 已实现 | `skills/sao-skill-reminder/` |
| weather | Expert | ✅ 已实现 | `experts/weather.toml` |
| general | Expert | ✅ 已实现 | `experts/general.toml` |
| code | Expert | ✅ 已实现 | `experts/code.toml` |
| search | Expert | ✅ 已实现 | `experts/search.toml` |
| translate | Expert | ✅ 已实现 | `experts/translate.toml` |
