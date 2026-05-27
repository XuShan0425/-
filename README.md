# Codex 开发环境模板

> 一条命令，为项目装上 Agent 优先的自动化工作流。

```bash
curl -sSL https://raw.githubusercontent.com/XuShan0425/-/main/install.sh | bash -s -- --profile generic
```

## 这是什么

一个可复用的 Codex 环境模板。安装后，你的项目自动获得：

- 任务规划 → 隔离执行 → 自动 PR 的完整链路
- Codex 每次停止时自动提交、推送、创建 PR（绝不碰 main）
- 版本化的任务文件和执行计划文档
- 零依赖，纯文件 + Python 脚本 + Git worktree

## 快速开始

```bash
# 1. 克隆模板
git clone git@github.com:XuShan0425/-.git /tmp/codex-template

# 2. 进入你的项目
cd /path/to/your-project

# 3. 安装
/tmp/codex-template/install.sh --profile generic

# 4. 在 Codex 中信任 hooks
# 打开 Codex，运行: /hooks
```

## Profile 选择

| Profile | 适用项目 | 自动检测 |
|---------|---------|---------|
| `generic` | 任意项目 | - |
| `node` | Node.js / TypeScript | eslint, tsc, vitest/jest |
| `python` | Python | ruff, mypy, pytest |

```bash
install.sh --profile node     # Node 项目
install.sh --profile python   # Python 项目
install.sh --profile python --force  # 覆盖已有文件
```

## 安装后的目录结构

```
your-project/
├── .codex/
│   ├── hooks.json                    # Stop hook 配置
│   └── hooks/stop_auto_pr.py         # 自动 PR Hook
├── .codex/orchestrator/
│   └── codex-team.py                 # 规划/执行/集成编排器
├── .codex-tasks/
│   ├── active/                       # 进行中的任务
│   ├── completed/                    # 已完成
│   ├── failed/                       # 失败
│   ├── running/                      # 执行中
│   └── pr-opened/                    # 已提 PR
├── .codex-runs/                      # 运行日志
├── docs/exec-plans/
│   ├── active/                       # 进行中的执行计划
│   └── completed/                    # 已完成的计划
├── tests/                            # 测试文件
└── AGENTS.md                         # (追加了 profile 专属规则)
```

## 三步工作流

### 1. 规划 → 2. 执行 → 3. 审查

```bash
# 规划：创建 Epic 和任务文件
python3 .codex/orchestrator/codex-team.py plan "添加用户认证功能"

# 执行：在隔离 worktree 中运行单个任务，自动提 PR
python3 .codex/orchestrator/codex-team.py run TASK-001

# 审查：在 GitHub 上查看 PR（系统绝不自动合并）
gh pr list --head codex/TASK-001
gh pr view <pr-number> --web

# 集成：查看当前 Epic 的所有 PR 状态
python3 .codex/orchestrator/codex-team.py integrate EPIC-001
```

## 自动化行为

当你使用 Codex 编辑代码并停止时，Stop Hook 自动：

1. 检测变更 → 无变更则跳过
2. 创建 `codex/...` 分支（绝不碰 main/master）
3. 运行 lint / typecheck / test
4. 验证失败 → 阻止完成，要求修复
5. 验证通过 → 提交、推送、创建 PR

## 安全底线

- 绝不自动合并
- 绝不提交到 `main`/`master`
- 拦截 `.env` 和密钥文件
- 不在 `shell=True` 下执行外部命令
- 所有 PR 需要人工审查后合并

## 环境要求

- Git / Python 3.10+ / GitHub CLI (`gh`)
- Codex CLI（支持 `codex exec`）
- 目标仓库已完成 `gh auth login`

## 内置 Skill

安装模板时会同步安装 10 个精选 Skill 到 `~/.codex/skills/` 和 `~/.agents/skills/`，Codex/Claude 按需自动调用：

| Skill | 类型 | 作用 |
|-------|------|------|
| `agent-planner` | Agent | 复杂需求拆解为 EPIC/TASK |
| `agent-worker` | Agent | 隔离执行单个任务 |
| `agent-reviewer` | Agent | 检查 PR 的 bug、边界、测试 |
| `agent-integrator` | Agent | 整合多个任务 PR |
| `gh-address-comments` | Codex | 处理 PR review 反馈 |
| `gh-fix-ci` | Codex | 诊断并修复 CI 失败 |
| `yeet` | Codex | 快速提交、推送、提 PR |
| `github` | Plugin | GitHub Issue/PR/仓库读写 |
| `find-skills` | Agent | 发现和推荐缺失的 skill |
| `auto-skill-installer` | Codex | 上下文感知的自动装 skill |

已安装的 skill 不会重复安装。用 `./install-skills.sh --dry-run` 预览安装计划。
