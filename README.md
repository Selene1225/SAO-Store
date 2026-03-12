# SAO-Store

SAO（Super-Agent-OS）的组件仓库，包含所有可共享的 **技能（Skill）** 和 **专家（Expert）**。

## 仓库结构

```
SAO-Store/
├── skills/                       # ── 技能（Python pip 包）──
│   ├── sao-skill-reminder/       # 提醒技能
│   │   ├── SKILL.toml
│   │   ├── pyproject.toml
│   │   └── sao_skill_reminder/
│   │       ├── __init__.py
│   │       └── skill.py
│   ├── sao-skill-programming/    # 编程技能（全周期开发）
│   │   ├── SKILL.toml
│   │   ├── pyproject.toml
│   │   └── sao_skill_programming/
│   │       ├── __init__.py
│   │       └── skill.py
│   └── sao-skill-{name}/        # 后续新增技能
│       └── ...
├── experts/                      # ── 专家（TOML 配置）──
│   ├── general.toml              # 通用助理（默认）
│   ├── weather.toml              # 天气专家
│   ├── search.toml               # 搜索专家
│   ├── code.toml                 # 编程专家
│   └── translate.toml            # 翻译专家
└── README.md
```

## 组件类型

| 类型 | 格式 | 安装方式 | 说明 |
|------|------|----------|------|
| **Skill** | Python 包 (`pyproject.toml`) | `pip install -e` | 重型插件，有代码逻辑和外部依赖 |
| **Expert** | TOML 配置文件 | 复制到 `~/.sao/experts/` | 轻量配置，定义 system_prompt + search + temperature |

## 安装技能

```bash
# 开发模式安装（本地修改即时生效）
pip install -e skills/sao-skill-reminder/
pip install -e skills/sao-skill-programming/

# 从 GitHub 安装
pip install "sao-skill-reminder @ git+https://github.com/Selene1225/SAO-Store.git#subdirectory=skills/sao-skill-reminder"
```

## 安装专家

将 TOML 文件复制到 SAO 配置目录，启动时自动加载：

```bash
cp experts/weather.toml ~/.sao/experts/
```

## 开发新技能

1. 在 `skills/` 下创建 `sao-skill-{name}/`
2. 继承 `sao.skills.BaseSkill`
3. 实现 `__init__(self, ctx: SkillContext)` 和 `execute(tool, args, ctx)` 方法
4. 在 `SKILL.toml` 中声明 `[[tools]]`、`[[examples]]`、`weight`、`[skill.requires]`
5. 添加 `pyproject.toml`（含 `[project.entry-points."sao.skills"]`）
6. 编写单元测试（`tests/test_skill.py`），**所有测试通过后才能上线**
7. `pip install -e skills/sao-skill-{name}/` 本地测试
8. Push 到 GitHub 共享

### 测试标准（必须）

每个 Skill 必须包含 `tests/test_skill.py`，覆盖以下内容：

| 测试类型 | 说明 |
|----------|------|
| **参数校验** | 每个 tool 的缺参/空参/非法参数分支 |
| **路由分发** | `execute()` 能正确路由到所有 tool + 未知 tool 返回警告 |
| **核心逻辑** | 纯函数/工具方法的单元测试（不依赖外部服务） |
| **成功路径** | mock 外部依赖后，验证正常执行返回正确结果 |
| **安全防护** | 路径穿越、危险命令等安全机制（如适用） |

运行测试：

```bash
# 单个 Skill
python -m pytest skills/sao-skill-{name}/tests/ -v

# 全部 Skill
python -m pytest skills/*/tests/ -v
```

外部依赖（SAO 主包、飞书 SDK 等）通过 `sys.modules` mock 处理，
无需安装即可运行测试。详见已有测试代码。

## 开发新专家

1. 在 `experts/` 下创建 `{name}.toml`
2. 填写 `name`、`description`、`system_prompt`、`search`、`temperature`
3. 复制到 `~/.sao/experts/` 测试
4. Push 到 GitHub 共享

## 依赖

- **Skill** 依赖 `super-agent-os` 主包提供的 `BaseSkill` / `SkillContext` 基类
- **Expert** 无代码依赖，纯 TOML 配置
