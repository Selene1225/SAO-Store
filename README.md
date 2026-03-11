# SAO Skill Store

SAO（Super-Agent-OS）的技能仓库，包含所有可共享的技能包。

## 仓库结构

```
SAO-Skill-Store/
├── sao-skill-reminder/       # 提醒技能
│   ├── pyproject.toml
│   ├── SKILL.toml
│   └── sao_skill_reminder/
│       ├── __init__.py
│       └── skill.py
└── ...                       # 后续新增技能
```

## 安装技能

```bash
# 开发模式安装（本地修改即时生效）
pip install -e sao-skill-reminder/

# 从 GitHub 安装
pip install "sao-skill-reminder @ git+ssh://git@github.com/Selene1225/SAO-Skill-Store.git#subdirectory=sao-skill-reminder"
```

## 开发新技能

1. 创建目录 `sao-skill-{name}/`
2. 继承 `sao.skills.BaseSkill`
3. 实现 `get_definition()` 和 `execute()` 方法
4. 添加 `pyproject.toml` + `SKILL.toml`
5. `pip install -e sao-skill-{name}/` 本地测试
6. Push 到 GitHub 共享

## 依赖

所有技能依赖 `super-agent-os` 主包提供的 `BaseSkill` / `SkillContext` 基类。
