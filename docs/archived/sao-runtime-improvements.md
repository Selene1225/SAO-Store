# SAO 运行时改进清单（借鉴 OpenClaw）

> 日期: 2026-03-11 | 面向: Super-Agent-OS 主仓库
>
> 以下改进均来自对 OpenClaw/ClawHub 技能系统的研究。OpenClaw 的 Skill 是纯 Markdown 指令（教 Agent 用 bash/browser 执行），
> SAO 的 Skill 是 Python 代码（确定性执行），两者路线不同，但 OpenClaw 在运维层面有多项成熟设计值得借鉴。
>
> 参考来源:
> - [OpenClaw Skills 文档](https://docs.openclaw.ai/skills)
> - [ClawHub 注册表](https://clawhub.ai)
> - [self-improving-agent](https://clawhub.ai/pskoett/self-improving-agent)（1.8k stars）

---

## 一、Gating 机制 — 加载时依赖检查

### 问题

当前 Skill 加载时不检查运行环境。如果缺少环境变量（如 `FEISHU_BITABLE_APP_TOKEN`）或二进制依赖，
会在 `execute()` 调用时才报错，用户体验差。

### OpenClaw 做法

```yaml
# SKILL.md frontmatter
metadata:
  openclaw:
    requires:
      env: ["GEMINI_API_KEY"]        # 环境变量必须存在
      bins: ["curl", "jq"]           # PATH 上必须有这些命令
      config: ["browser.enabled"]    # 配置项必须为 truthy
    primaryEnv: "GEMINI_API_KEY"
```

加载时自动跳过不满足条件的 Skill，不注入 Router prompt。

### SAO 实现方案

**SAO-Store 侧**（已规划，见 `docs/implementation-plan.md`）：SKILL.toml 增加声明

```toml
[skill.requires]
sao = ">=2.0.0"
env = ["FEISHU_BITABLE_APP_TOKEN", "FEISHU_BITABLE_REMINDER_TABLE_ID"]
bins = []                    # 无外部二进制依赖
features = ["feishu"]        # SAO 功能开关
```

**SAO 侧实现**：

```python
# sao/skills/loader.py

import os
import shutil

def check_skill_gating(skill_toml: dict) -> tuple[bool, str]:
    """检查 Skill 运行环境是否满足要求。
    
    Returns:
        (eligible, reason) — eligible=False 时 reason 说明原因
    """
    requires = skill_toml.get("skill", {}).get("requires", {})
    
    # 1. 检查环境变量
    missing_env = [v for v in requires.get("env", []) if not os.environ.get(v)]
    if missing_env:
        return False, f"缺少环境变量: {', '.join(missing_env)}"
    
    # 2. 检查二进制依赖
    missing_bins = [b for b in requires.get("bins", []) if not shutil.which(b)]
    if missing_bins:
        return False, f"缺少命令: {', '.join(missing_bins)}"
    
    # 3. 检查 SAO 功能开关
    # features 对应 ~/.sao/config.toml 中的 [features] 段
    for feat in requires.get("features", []):
        if not is_feature_enabled(feat):
            return False, f"功能未启用: {feat}"
    
    return True, ""
```

**集成到 Skill Loader**：

```python
# sao/skills/registry.py — discover_and_register()

for ep in entry_points(group="sao.skills"):
    toml = load_skill_toml(ep.name)
    eligible, reason = check_skill_gating(toml)
    
    if not eligible:
        logger.warning(f"Skill '{ep.name}' 跳过加载: {reason}")
        continue  # 不注入 Router prompt，不实例化
    
    skill_cls = ep.load()
    # ... 正常注册
```

### 预估工作量

1-2 小时。改动集中在 `sao/skills/loader.py` + `registry.py`。

---

## 二、Token 预算感知 — Router Prompt 开销跟踪

### 问题

每个 Skill 的 tools + examples 注入 Router prompt 会消耗 token。随着 Skill 增多，
Router prompt 会膨胀，增加延迟和成本，且可能超过上下文窗口。

### OpenClaw 做法

精确公式：`total = 195 + Σ (97 + len(name) + len(description) + len(location))`

### SAO 实现方案

```python
# sao/skills/prompt_builder.py

MAX_ROUTER_SKILL_TOKENS = 2000  # Router prompt 中技能描述的 token 上限

def build_router_prompt(skill_tomls: list[dict]) -> str:
    """构建 Router 的技能描述段，带 token 预算控制。"""
    sections = []
    total_chars = 0
    
    for toml in skill_tomls:
        section = format_skill_for_router(toml)
        section_chars = len(section)
        
        # 粗估: 1 token ≈ 2 中文字 ≈ 4 英文字符
        estimated_tokens = section_chars // 2  # 中文为主
        
        if total_chars + section_chars > MAX_ROUTER_SKILL_TOKENS * 2:
            logger.warning(f"Router prompt token 预算超限，跳过后续技能")
            break
        
        sections.append(section)
        total_chars += section_chars
    
    prompt = "\n\n".join(sections)
    logger.info(f"Router 技能 prompt: {len(sections)} 个技能, ~{total_chars // 2} tokens")
    return prompt
```

**日志输出示例**：
```
INFO  Router 技能 prompt: 3 个技能, ~450 tokens
WARN  Skill 'huge_tool' 跳过加载: Router prompt token 预算超限
```

### 预估工作量

0.5-1 小时。纯新增代码，不影响现有逻辑。

---

## 三、三级优先级覆盖 — Skill/Expert 加载优先级

### 问题

当前只有一个加载来源（pip entry points + `~/.sao/experts/`），没有覆盖机制。
用户无法用自定义版本替换 SAO-Store 的默认 Skill/Expert。

### OpenClaw 做法

```
workspace/skills (最高) → ~/.openclaw/skills (中) → bundled skills (最低)
```

同名冲突时高优先级覆盖低优先级，不报错。

### SAO 实现方案

**Skill 三级优先级**：
```
~/.sao/skills/          (最高) 用户自定义 / Forge 生成
pip entry points        (中)   SAO-Store pip install 的
sao/skills/内置         (最低) StoreManager / Forge 等内置技能
```

**Expert 三级优先级**：
```
~/.sao/experts/user/    (最高) 用户手工修改的版本
~/.sao/experts/         (中)   从 SAO-Store 安装的
sao/experts/内置        (最低) SAO 自带的 general.toml
```

```python
# sao/skills/registry.py

def discover_skills_with_priority() -> dict[str, SkillEntry]:
    """三级优先级发现 Skill。"""
    registry = {}
    
    # 1. 最低优先级: 内置技能
    for name, cls in BUILTIN_SKILLS.items():
        registry[name] = SkillEntry(cls=cls, source="builtin", priority=0)
    
    # 2. 中优先级: pip entry points
    for ep in entry_points(group="sao.skills"):
        registry[ep.name] = SkillEntry(cls=ep.load(), source="pip", priority=1)
    
    # 3. 最高优先级: ~/.sao/skills/ 本地覆盖
    local_dir = Path.home() / ".sao" / "skills"
    for skill_dir in local_dir.iterdir():
        if (skill_dir / "SKILL.toml").exists():
            # 动态加载本地技能
            entry = load_local_skill(skill_dir)
            if entry:
                registry[entry.name] = SkillEntry(cls=entry.cls, source="local", priority=2)
    
    return registry
```

### 预估工作量

2-3 小时。需要重构 skill discovery 逻辑 + expert loader。

---

## 四、热重载 — 文件变更自动刷新

### 问题

修改 Expert TOML 或 SKILL.toml 后需要重启 SAO 才能生效。
开发调试时体验差。

### OpenClaw 做法

```json
{ "skills": { "load": { "watch": true, "watchDebounceMs": 250 } } }
```

基于 file watcher 监听 SKILL.md 变更，自动刷新 skill list。

### SAO 实现方案

```python
# sao/skills/watcher.py

import asyncio
from watchfiles import awatch  # pip install watchfiles

class SkillWatcher:
    """监听 Skill/Expert 文件变化，触发热重载。"""
    
    def __init__(self, registry, expert_loader):
        self._registry = registry
        self._expert_loader = expert_loader
        self._watch_dirs = [
            Path.home() / ".sao" / "experts",
            Path.home() / ".sao" / "skills",
        ]
    
    async def start(self):
        """后台协程：监听文件变化。"""
        async for changes in awatch(*self._watch_dirs, debounce=500):
            for change_type, path in changes:
                path = Path(path)
                if path.suffix == ".toml":
                    if "experts" in path.parts:
                        await self._reload_expert(path)
                    elif path.name == "SKILL.toml":
                        await self._reload_skill(path)
    
    async def _reload_expert(self, path: Path):
        logger.info(f"Expert 热重载: {path.name}")
        self._expert_loader.reload(path)
    
    async def _reload_skill(self, path: Path):
        logger.info(f"SKILL.toml 热重载: {path.parent.name}")
        self._registry.reload_skill_toml(path)
```

**配置**：

```toml
# ~/.sao/config.toml
[skills.load]
watch = true
watch_debounce_ms = 500
```

### 预估工作量

2-3 小时。新增 watcher.py + 注册为启动后台任务。需安装 `watchfiles`。

---

## 五、集中配置覆盖 — Per-Skill 开关与环境注入

### 问题

当前无法在不卸载 Skill 的情况下禁用它，也无法从配置文件注入 API key/环境变量。

### OpenClaw 做法

```json
{
  "skills": {
    "entries": {
      "reminder": { "enabled": true, "env": { "BITABLE_TOKEN": "xxx" } },
      "weather":  { "enabled": false }
    }
  }
}
```

### SAO 实现方案

```toml
# ~/.sao/config.toml

# 全局开关
[skills.load]
watch = true

# Per-Skill 配置
[skills.entries.reminder]
enabled = true
env = { FEISHU_BITABLE_APP_TOKEN = "cli_xxx", FEISHU_BITABLE_REMINDER_TABLE_ID = "tbl_xxx" }

[skills.entries.programming]
enabled = true

[skills.entries.weather_api]
enabled = false   # 禁用但不卸载

# Per-Expert 配置
[experts.entries.weather]
enabled = true

[experts.entries.translate]
enabled = false
```

**SAO 侧实现**：

```python
# sao/config.py

def load_config() -> SaoConfig:
    config_path = Path.home() / ".sao" / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    return {}

# sao/skills/registry.py — 加载时检查 enabled

def is_skill_enabled(skill_name: str, config: dict) -> bool:
    entry = config.get("skills", {}).get("entries", {}).get(skill_name, {})
    return entry.get("enabled", True)  # 默认启用

def inject_skill_env(skill_name: str, config: dict):
    """将 per-skill env 注入 os.environ（仅在 skill 运行期间）。"""
    entry = config.get("skills", {}).get("entries", {}).get(skill_name, {})
    for key, value in entry.get("env", {}).items():
        if key not in os.environ:  # 不覆盖已有的
            os.environ[key] = value
```

### 预估工作量

1-2 小时。新增 config.toml 解析 + 注入逻辑。

---

## 六、自我改进框架 — 学习日志系统

### 问题

SAO 每次对话结束后知识就消失了。没有跨会话的学习积累机制。

### OpenClaw 做法（self-improving-agent）

```
.learnings/
├── LEARNINGS.md     # 纠正 + 知识 + 最佳实践
├── ERRORS.md        # 错误日志
└── FEATURE_REQUESTS.md  # 用户需求

规则：
1. 错误/纠正自动记录
2. 反复出现(≥3次) → promote 到 AGENTS.md 永久化
3. 每次会话开始时回顾相关学习
```

### SAO 实现方案（Phase 6 Memory 系统）

```python
# sao/memory/learnings.py

class LearningStore:
    """学习日志存储，参考 self-improving-agent 模式。"""
    
    base_dir = Path.home() / ".sao" / "memory" / "learnings"
    
    async def log_error(self, error: str, context: str, suggested_fix: str):
        """记录错误。"""
        entry = LearningEntry(
            id=self._next_id("ERR"),
            category="error",
            priority="high",
            summary=error,
            details=context,
            suggested_action=suggested_fix,
        )
        self._append("ERRORS.md", entry)
    
    async def log_correction(self, what_was_wrong: str, what_is_correct: str):
        """用户纠正 → 记录学习。"""
        entry = LearningEntry(
            id=self._next_id("LRN"),
            category="correction",
            summary=what_was_wrong,
            details=what_is_correct,
        )
        self._append("LEARNINGS.md", entry)
    
    async def check_promotion(self):
        """检查是否有学习需要 promote 到系统规则。
        
        条件：出现 ≥3 次，跨 ≥2 个不同上下文，30 天内。
        """
        recurring = self._find_recurring(min_count=3, window_days=30)
        for learning in recurring:
            await self._promote_to_rules(learning)
    
    async def get_relevant(self, query: str, limit: int = 5) -> list[str]:
        """检索与当前对话相关的历史学习。"""
        # 简单关键词匹配，后期可换 embedding
        ...
```

**三层记忆架构**：

```
短期: 对话历史（内存，随会话清除）
  ↓ 摘要
中期: 会话摘要（~/.sao/memory/sessions/YYYY-MM-DD.md）
  ↓ 提炼
长期: 学习日志 + 系统规则（~/.sao/memory/learnings/ + ~/.sao/rules/）
```

### 预估工作量

5-7 天。含三层记忆 + 学习日志 + promotion 逻辑 + 斜杠命令。属于 Phase 6。

---

## 总结：实施优先级

| # | 改进项 | 优先级 | 工作量 | 依赖 | Phase |
|---|--------|--------|--------|------|-------|
| 5 | 集中配置覆盖 | **P0** | 1-2h | 无 | 立即 |
| 1 | Gating 依赖检查 | **P0** | 1-2h | SAO-Store TOML 更新 | 立即 |
| 2 | Token 预算感知 | **P1** | 0.5-1h | 无 | Phase 1 |
| 3 | 三级优先级覆盖 | **P1** | 2-3h | 无 | Phase 1 |
| 4 | 热重载 | **P2** | 2-3h | watchfiles | Phase 1 |
| 6 | 自我改进框架 | **P2** | 5-7d | Memory 系统 | Phase 6 |

**建议执行顺序**：5 → 1 → 2 → 3 → 4 → 6

先做 config.toml（因为 Gating 和其他功能都依赖它），再做 Gating（最直接改善用户体验），
Token / 优先级 / 热重载可以随 Phase 1 StoreManager 一起做，自我改进属于 Phase 6。
