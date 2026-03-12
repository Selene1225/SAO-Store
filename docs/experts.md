# SAO Chat Expert 框架设计

> 版本: 1.0.0 | 日期: 2026-03-11 | 状态: ✅ 已实现

## 1. 背景与动机

SAO 的 Router 将消息分为 `chat` / `skill` / `meta` / `delegate` 等路由。其中 `chat` 路由覆盖最广泛——闲聊、天气、编程、翻译、新闻……都走同一个 System Prompt + 同一套参数。

**问题**：
- **Token 浪费**：所有 chat 都开 `enable_search`，闲聊白费 ~1300 token 的搜索注入
- **Prompt 臃肿**：天气卡片格式、编程风格、翻译规则……全塞一个 prompt，互相干扰
- **质量打折**：通用 prompt 什么都管 = 什么都管不好

**解决方案**：`Chat Expert` 模式——Router 输出一个 `chat_mode` 字段，Agent 按 mode 选择专属 Prompt + 搜索策略。

---

## 2. 架构概览

```
用户消息
    │
    ▼
┌──────────┐  {"route":"chat", "chat_mode":"weather", "needs_search":true,
│  Router  │   "resolved_query":"明天青岛天气"}
└────┬─────┘
     │
     ▼
┌──────────────────────────┐
│   Agent._exec_chat()     │
│                          │
│   mode = route["chat_mode"]
│   expert = EXPERTS[mode] │  ◄── experts/__init__.py 中注册
│                          │
│   system_prompt = expert.system
│   enable_search = expert.search
│   temperature   = expert.temperature
└────┬─────────────────────┘
     │
     ▼
┌──────────┐
│  LLM     │  只在 needs_search=true 的专家才开搜索
└──────────┘
```

---

## 3. Expert 定义

每个 Expert 在 `sao/experts/` 子包中独立定义，基类在 `base.py`：

```python
@dataclass
class ChatExpert:
    """一个 Chat Expert 的完整配置。"""
    system: str          # System Prompt
    search: bool         # 是否默认开启联网搜索
    temperature: float   # LLM 温度（创意型高、事实型低）
```

### 3.1 Expert 注册表

```python
# sao/experts/__init__.py

EXPERTS: dict[str, ChatExpert] = {
    "general":   _general,    # from experts/general.py
    "weather":   _weather,    # from experts/weather.py
    "code":      _code,       # from experts/code.py
    "translate": _translate,  # from experts/translate.py
    "search":    _search,     # from experts/search.py
}
```

### 3.2 Fallback 规则

- Router 输出的 `chat_mode` 不在 `EXPERTS` 中 → 使用 `"general"`
- Router 未输出 `chat_mode` → 使用 `"general"`

---

## 4. Expert Prompt 设计原则

| 原则 | 说明 |
|---|---|
| **单一职责** | 每个 Expert 只管一类任务，prompt 只描述该类的行为和格式 |
| **极致精简** | 用最少 token 传递最多信息，避免冗余说明 |
| **格式明确** | 有固定输出格式的（天气卡片、代码块），在 prompt 中给出极简模板 |
| **不重复** | 通用人设（"你是 SAO"）由 Agent 层统一注入，Expert prompt 只管领域差异 |

---

## 5. 内置专家列表

### 5.1 `general` — 通用助理（默认）

```
search: false | temperature: 0.7
```

覆盖：闲聊、知识问答、帮助说明、无法归类的请求。

**Prompt 要点**：
- 简洁高效，中文回复
- 不确定就坦诚说明

### 5.2 `weather` — 天气专家

```
search: true | temperature: 0.3
```

覆盖：天气查询、气温、降雨、空气质量。

**Prompt 要点**：
- 卡片格式：🌤城市 🌡温度 ☁天况 📅近3日趋势
- 数据来自搜索结果，缺字段省略，不编造
- 低温度（factual）

### 5.3 `code` — 编程专家

```
search: false | temperature: 0.2
```

覆盖：代码生成、debug、解释、重构。

**Prompt 要点**：
- 代码用 markdown 代码块
- 先给结论/代码，再简要解释
- 参考最佳实践，不过度解释

### 5.4 `translate` — 翻译专家

```
search: false | temperature: 0.3
```

覆盖：中英互译、多语言翻译。

**Prompt 要点**：
- 直接输出译文，不加前缀说明
- 保持原文风格和格式
- 专业术语准确

### 5.5 `search` — 搜索专家

```
search: true | temperature: 0.5
```

覆盖：新闻、实时信息、股价、热搜等需联网的查询。

**Prompt 要点**：
- 标注信息来源和时间
- 区分事实和观点
- 承认信息可能有时效性

---

## 6. Router 集成

### 6.1 Router 输出变更

在 `RouterResult` 中新增 `chat_mode` 字段：

```python
@dataclass
class RouterResult:
    route: str = "chat"
    resolved_query: str = ""
    needs_search: bool = False
    chat_mode: str = "general"    # ← 新增
    skill: str | None = None
    tool: str | None = None
    args: dict | None = None
    ...
```

### 6.2 Router Prompt 变更

在 Router System Prompt 中增加 `chat_mode` 规则：

```
route=chat 时必须输出 chat_mode，可选值：
- general: 闲聊、知识问答
- weather: 天气查询
- code: 编程相关
- translate: 翻译
- search: 需要联网的实时信息查询（新闻、股价等）

示例：
{"route":"chat","chat_mode":"weather","needs_search":true,"resolved_query":"明天青岛天气"}
{"route":"chat","chat_mode":"general","needs_search":false,"resolved_query":"你好"}
{"route":"chat","chat_mode":"code","needs_search":false,"resolved_query":"Python 快排实现"}
```

### 6.3 needs_search 与 chat_mode 的关系

`needs_search` 仍由 Router 显式输出，但 Expert 的 `search` 属性作为 **默认值**：

```python
# Agent._exec_chat() 中的逻辑
expert = EXPERTS.get(chat_mode, EXPERTS["general"])
# Router 的 needs_search 优先；若 Router 未输出，用 Expert 默认值
enable_search = route.get("needs_search", expert.search)
```

这样即使 Router 误判 mode（比如天气分到了 general），`needs_search=true` 仍然能保证搜索开启。

---

## 7. Agent 执行流程

```python
async def _exec_chat(self, route, session_id, chat_id, token):
    resolved = route.get("resolved_query", "你好")
    chat_mode = route.get("chat_mode", "general")
    needs_search = route.get("needs_search", False)

    expert = EXPERTS.get(chat_mode, EXPERTS["general"])

    messages = [
        Message(role="system", content=expert.system),
        Message(role="user", content=resolved),
    ]

    enable_search = needs_search or expert.search
    resp = await self.llm.chat(
        messages,
        temperature=expert.temperature,
        enable_search=enable_search,
    )
    ...
```

---

## 8. 投机执行适配

当前 SAO 使用投机并行（Router ∥ Chat 同时发起）。Expert 模式下：

| 场景 | 处理 |
|---|---|
| 投机 Chat（Router 未完成时） | 使用 `general` Expert（无搜索、通用 prompt） |
| Router 返回 `chat` + `chat_mode=general` | 投机命中，直接用投机结果 |
| Router 返回 `chat` + `chat_mode≠general` | 投机未命中，按对应 Expert 重新调用 LLM |
| Router 返回非 `chat` | 投机未命中，走正常 Executor |

**投机命中条件更新**：

```python
if (route_result.route == "chat"
    and route_result.chat_mode == "general"
    and not route_result.needs_search
    and spec_resp is not None):
    # 投机命中
```

---

## 9. Token 节省预估

| 场景 | 之前（全 chat 开搜索） | 之后（Expert 按需） | 节省 |
|---|---|---|---|
| "你好" | ~1,700 input | ~100 input | **94%** |
| "明天天气" | ~2,100 input | ~2,100 input | 0%（仍需搜索） |
| "Python 快排" | ~1,700 input | ~100 input | **94%** |
| "翻译这段话" | ~1,700 input | ~80 input | **95%** |

根据实际使用，~70% 的消息是闲聊/问答，预计整体 input token **下降 60-70%**。

---

## 10. 扩展指南

### 添加新 Expert

1. 新建 `sao/experts/summary.py`：
   ```python
   from sao.experts.base import ChatExpert
   SYSTEM = "你是总结专家。输入长文，输出3-5条要点摘要。"
   expert = ChatExpert(system=SYSTEM, search=False, temperature=0.3)
   ```

2. 在 `sao/experts/__init__.py` 导入并注册：
   ```python
   from sao.experts.summary import expert as _summary
   EXPERTS["summary"] = _summary
   ```

3. 在 Router Prompt 的 `chat_mode` 可选值中添加 `summary`

4. 完成——只需新建一个文件 + 两行注册代码

### 性能建议

- Expert 的 System Prompt 控制在 **2 行以内**（< 100 token）
- `search=true` 的 Expert 会额外注入 ~1300 token，谨慎使用
- `temperature` 事实型用 0.2-0.3，创意型用 0.7-0.9

---

## 11. 文件变更清单

| 文件 | 变更 |
|---|---|
| `sao/experts/` | 独立子包（与 skills 对称）：`base.py`（ChatExpert）、`general/weather/code/translate/search.py`（各 Expert）、`__init__.py`（注册表） |
| `sao/core/prompts.py` | 移除 Expert 定义，仅保留 Router/Status 模板（向后兼容 re-export） |
| `sao/core/router.py` | `RouterResult` 新增 `chat_mode` 字段, Router Prompt 新增 chat_mode 规则 |
| `sao/core/agent.py` | `_exec_chat()` 按 `chat_mode` 选 Expert；投机命中条件更新 |
| `docs/experts.md` | 本文档 |
