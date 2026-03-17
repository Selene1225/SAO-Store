# SAO Skill 开发规范 v2

> 适用于 SAO v2.x，`sao-skill-*` 包的作者请按此规范更新。

---

## 快速对照：v1 → v2 变更点

| 项目 | v1（旧） | v2（新） |
|------|----------|----------|
| SKILL.toml args 格式 | `[tools.args.xxx]` inline table | `[[tools.args]]` array of tables |
| `keywords` 字段类型 | 逗号分隔字符串 | 字符串数组 |
| `__init__` 签名 | `def __init__(self)` | `def __init__(self, **kwargs)` |

---

## 一、目录结构

```
sao-skill-mypkg/
├── pyproject.toml          # 含 entry_points
├── SKILL.toml              # 技能元数据（SAO 读取）
└── sao_skill_mypkg/
    └── __init__.py         # 技能实现
```

---

## 二、SKILL.toml 完整格式

```toml
[skill]
name = "reminder"
version = "1.0.0"
description = "管理提醒/闹钟：创建、查看、更新、取消"
author = "yourname"
keywords = ["提醒", "闹钟", "定时", "reminder", "alarm"]  # ✅ 数组格式
weight = 1
# weight 含义:
#   1~3  轻量 — 主 Agent 同步直调（秒级，单次调用）
#   4~6  中等 — 视情况决定
#   7~10 重量 — SubAgent 异步委派（分钟~小时级，多轮交互）

[skill.requires]
sao = ">=2.0.0"
env = ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]  # 必须存在的环境变量，缺失则 Gating 不加载
bins = []                                       # 必须在 PATH 中的命令，如 ["ffmpeg"]
features = ["feishu"]                           # config.toml [features] 中必须启用的开关

# ── Tools 定义 ────────────────────────────────────────────────────────────
# 每个 [[tools]] 对应一个可调用操作，SAO 会把它注入 Router prompt

[[tools]]
name = "set"
description = "创建新提醒/闹钟"

[[tools.args]]              # ✅ 必须是 array of tables（[[tools.args]]），不能用 [tools.args.xxx]
name = "content"
type = "string"             # string | integer | boolean
required = true
description = "提醒内容"

[[tools.args]]
name = "remind_time"
type = "string"
required = true
description = "提醒时间，格式 YYYY-MM-DD HH:mm"

[[tools]]
name = "list"
description = "查看待执行的提醒"
# 无参数时不写 [[tools.args]]

[[tools]]
name = "cancel"
description = "取消待执行的提醒"

[[tools.args]]
name = "keyword"
type = "string"
required = true
description = "关键词匹配提醒"

# ── 示例（帮助 Router 理解意图，强烈建议提供）────────────────────────────

[[examples]]
user = "明天早8点提醒我开会"
tool = "set"
args = { content = "开会", remind_time = "2026-03-18 08:00" }

[[examples]]
user = "查看我的提醒"
tool = "list"

[[examples]]
user = "取消开会的提醒"
tool = "cancel"
args = { keyword = "开会" }
```

---

## 三、Python 实现

### 3.1 `__init__` 签名

```python
from sao.skills import BaseSkill, SkillContext

class ReminderSkill(BaseSkill):
    name = "reminder"
    description = "管理提醒/闹钟：创建、查看、更新、取消"

    def __init__(self, **kwargs):
        # SAO 在实例化时会传入 channel 注入的依赖（如 lark_client），
        # 用 **kwargs 接住，按需取用，不需要的忽略即可。
        self.lark_client = kwargs.get("lark_client")
```

> **为什么要 `**kwargs`？**
> SAO Registry 实例化 pip skill 时会传入 `channel.get_skill_deps()` 中的所有键值对。
> 飞书 channel 会传 `lark_client=...`，未来其他 channel 可能传其他依赖。
> `**kwargs` 保证不管 channel 传什么，skill 都不会因签名不匹配而崩溃。

### 3.2 `execute` 方法

```python
    async def execute(self, tool: str, args: dict, ctx: SkillContext) -> str | None:
        if tool == "set":
            return await self._set(args, ctx)
        if tool == "list":
            return await self._list(args, ctx)
        if tool == "cancel":
            return await self._cancel(args, ctx)
        return f"❌ 未知操作: {tool}"
```

### 3.3 SkillContext 可用字段

```python
ctx.sender_id    # str  — 消息发送者 ID
ctx.chat_id      # str  — 目标会话 ID
ctx.channel      # BaseChannel — 可调用 await ctx.channel.send(ctx.chat_id, "消息")
ctx.long_term    # LongTermMemory | None — 长期记忆（需 skill.memory.long_term = true）
ctx.user_profile # UserProfile | None   — 用户档案
ctx.skill_memory # SkillMemory | None   — skill 专属记忆（自动隔离命名空间）
```

### 3.4 返回值约定

- 返回 `str`：SAO 会经 CEO 包装层润色后发送给用户
- 返回 `None`：skill 已自行通过 `ctx.channel.send()` 发送，SAO 不再重复发

---

## 四、pyproject.toml entry_points

```toml
[project.entry-points."sao.skills"]
reminder = "sao_skill_reminder:ReminderSkill"
```

entry point key（`reminder`）必须与 `SKILL.toml` 中的 `skill.name` 一致。

---

## 五、SKILL.toml 放置位置

SAO 用以下逻辑查找 pip skill 的 SKILL.toml（优先级从高到低）：

1. `<package_dir>/SKILL.toml`（包根目录，推荐）
2. `<package_dir>/../SKILL.toml`（包的上一级）

**推荐结构**（SKILL.toml 放包根目录）：

```
sao-skill-reminder/
├── pyproject.toml
├── SKILL.toml              ← 放这里
└── sao_skill_reminder/
    └── __init__.py
```

---

## 六、Gating 机制说明

SAO 启动时对每个 skill 做 Gating 检查，不满足条件的 skill **不加载、不报错**，只写 WARNING 日志。

| 检查项 | 配置字段 | 不满足时的行为 |
|--------|----------|----------------|
| 环境变量 | `requires.env` | 跳过加载，日志提示缺少变量 |
| 系统命令 | `requires.bins` | 跳过加载，日志提示缺少命令 |
| 功能开关 | `requires.features` | 跳过加载，日志提示功能未启用 |
| SAO 版本 | `requires.sao` | 跳过加载，日志提示版本不符 |
| config.toml 禁用 | — | 跳过加载 |

---

## 七、完整最小示例

**SKILL.toml**
```toml
[skill]
name = "dice"
version = "2.0.0"
description = "掷骰子 / 抛硬币"
author = "yourname"
keywords = ["骰子", "随机", "抛硬币", "dice"]
weight = 1

[[tools]]
name = "roll"
description = "掷骰子"

[[tools.args]]
name = "sides"
type = "integer"
required = false
description = "骰子面数，默认 6"
default = 6

[[tools]]
name = "flip"
description = "抛硬币，正面或反面"

[[examples]]
user = "帮我掷个骰子"
tool = "roll"

[[examples]]
user = "抛个硬币"
tool = "flip"
```

**sao_skill_dice/\_\_init\_\_.py**
```python
import random
from sao.skills import BaseSkill, SkillContext


class DiceSkill(BaseSkill):
    name = "dice"
    description = "掷骰子 / 抛硬币"

    def __init__(self, **kwargs):
        pass

    async def execute(self, tool: str, args: dict, ctx: SkillContext) -> str | None:
        if tool == "roll":
            sides = int(args.get("sides") or 6)
            result = random.randint(1, sides)
            return f"🎲 {result}（{sides} 面骰）"
        if tool == "flip":
            result = random.choice(["正面 ⬆️", "反面 ⬇️"])
            return f"🪙 {result}"
        return f"❌ 未知操作: {tool}"
```

**pyproject.toml**
```toml
[project.entry-points."sao.skills"]
dice = "sao_skill_dice:DiceSkill"
```
