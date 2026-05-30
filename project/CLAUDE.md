# 速卖通广告智能管理系统 — 项目规范
> 供 Claude Code 读取，用于规划 EPIC / TASK。所有开发决策以本文档为准。

---

## 项目概述

构建一套**全自动**的速卖通广告管理系统，通过 Playwright 采集后台数据，AI 分析后自动执行广告决策，人工仅需查看日志和处理警报。

**当前阶段**：聚焦广告模块（v1），不涉及其他店铺功能。  
**商品规模**：初期 11 个 SKU，架构需支持后续扩张。  
**货源模式**：上游供应商调货（无库存压力，无需库存预警）。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 浏览器自动化 | Playwright (Python) |
| 数据库 | PostgreSQL |
| AI 分析 | Claude API (claude-sonnet-4-20250514) |
| 后端 | Python (FastAPI) |
| 前端控制台 | React + Tailwind |
| 任务调度 | APScheduler 或 Celery |
| 容器 | Docker Compose |

---

## 系统架构

```
定时任务触发
    ↓
[1] Cookie 健康检查
    ├── 有效 → 继续
    └── 无效 → 停止所有操作 + 发送警报 + 等待人工修复
    ↓
[2] Playwright 采集数据
    └── 拦截速卖通后台 API 请求（不依赖截图/OCR）
    ↓
[3] 写入 PostgreSQL
    ↓
[4] AI 分析模块（Claude API）
    └── 结合：广告数据 + 商品成本 + 物流费率 + 平台佣金
    ↓
[5] 生成执行计划（JSON）
    ↓
[6] 边界条件检查
    ├── 硬边界 → 自动停止 + 生成报告
    ├── 软边界 → 暂停 + 通知人工确认
    └── 通过 → 进入执行
    ↓
[7] Playwright 执行操作
    ↓
[8] 写入操作日志
```

---

## 数据模型

### 手动录入数据（用户初始化时填写）

```
products
├── id
├── sku_id (速卖通商品ID)
├── name
├── cost_price (成本价，USD)
├── category
└── created_at

logistics_rates
├── id
├── destination_region (目的地区，如 US / EU / AU)
├── weight_range_min (g)
├── weight_range_max (g)
├── cost (USD)
└── updated_at

platform_fees
├── id
├── category
├── fee_rate (%)
└── updated_at
```

> `logistics_rates` 和 `platform_fees` 由 AI 从速卖通帮助中心页面解析，人工确认后存入。

### Playwright 采集数据

```
ad_snapshots
├── id
├── sku_id
├── snapshot_time
├── impressions (曝光量)
├── clicks (点击量)
├── ctr (点击率)
├── orders
├── conversion_rate (转化率)
├── ad_spend (广告花费 USD)
├── revenue (收入 USD)
├── ad_type (站内推广 / 联盟 / 营销活动)
└── buyer_region_breakdown (JSON，按地区分布)

price_snapshots
├── id
├── sku_id
├── snapshot_time
└── current_price (USD)
```

### 系统计算数据

```
profit_analysis
├── id
├── sku_id
├── calc_time
├── logistics_cost (加权平均，按买家地区分布)
├── platform_fee (按类目费率)
├── true_cost (成本 + 物流 + 平台费)
├── gross_margin (毛利率)
├── breakeven_ad_spend (盈亏平衡广告花费)
├── current_roi
└── roi_7d_trend (JSON，近7天ROI)
```

---

## 边界规则

### 硬边界（自动触发，无需人工确认）

| 条件 | 行为 |
|------|------|
| Cookie 失效 / 登录失败 | 停止**所有**商品操作，写警报日志，发通知 |
| 某 SKU ROI 连续 7 天为负 | 停止该 SKU 广告，生成数据分析报告（见报告规范） |
| Playwright 采集异常（非登录问题） | 跳过本次执行周期，写错误日志，发通知 |

### 软边界（暂停，等待人工确认）

| 条件 | 行为 |
|------|------|
| 关闭任何推广活动 | 暂停执行，生成说明文档（附原因 + 数据），人工在控制台确认后继续 |

### 系统自管理参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 单日广告花费上限 | 盈亏平衡花费 × 150% | 动态计算，随利润率变化 |
| 单次调价幅度 | ≤ 5% | 硬性上限 |
| 调价频率 | 24小时最多一次 | 每个 SKU 独立计算 |

---

## AI 分析模块规范

### 输入（每次分析传入）

```json
{
  "sku_id": "xxx",
  "cost_price": 5.00,
  "current_price": 12.00,
  "logistics_cost_weighted": 2.30,
  "platform_fee_rate": 0.05,
  "ad_snapshots_7d": ["..."],
  "current_ad_type": "standard",
  "breakeven_ad_spend": 3.20,
  "constraints": {
    "max_daily_ad_spend": 4.80,
    "max_price_change_pct": 0.05,
    "price_change_cooldown_hours": 24
  }
}
```

### 输出（结构化 JSON）

```json
{
  "decision_type": "adjust_bid | adjust_price | switch_ad_type | stop_ad | no_action | requires_confirmation",
  "action": {
    "field": "daily_budget | price | ad_type",
    "current_value": 3.00,
    "new_value": 3.40,
    "change_pct": 0.133
  },
  "reasoning": "近7天点击率上升12%，转化率稳定，ROI为正且改善中，建议提升预算扩大曝光",
  "confidence": 0.82,
  "risk_level": "low | medium | high"
}
```

---

## 数据初始化流程（一次性任务）

1. **AI 解析物流费率**
   - 目标页面：`https://helpcenter.aliexpress.com/s/SellerHelp?...`
   - AI 解析费率表 → 前端展示 → 人工确认 → 写入 `logistics_rates`
2. **AI 解析平台佣金**
   - 同上流程，写入 `platform_fees`
3. **手动录入商品成本**
   - 控制台提供批量导入（CSV）+ 单品编辑界面
4. **首次登录授权**
   - Playwright 启动浏览器，人工登录速卖通后台
   - 系统自动保存 Cookie
   - 完成后开始自动采集

---

## 前端控制台页面规划

### 必须实现的页面

| 页面 | 功能 |
|------|------|
| Dashboard | 所有 SKU 的状态总览（ROI、今日花费、警报数量） |
| 商品管理 | 成本录入、费率确认、单品开关 |
| 日志中心 | 按 SKU / 时间筛选操作日志，支持查看 AI reasoning |
| 警报中心 | 未处理警报列表，软边界确认操作入口 |
| 报告查看 | 查看 ROI 连续为负的分析报告，推广活动关闭说明 |
| 系统设置 | Cookie 状态、采集频率、全局开关 |

---

## 日志 / 报告规范

### 操作日志（每次执行写入）

```
[时间] [SKU名] [操作类型] [旧值→新值] [AI置信度] [执行结果]
示例：2026-05-30 14:32 | 蓝牙耳机 | 调整出价 | $2.80→$2.94 | 置信度82% | 成功
```

### ROI 连续为负分析报告（触发硬边界时生成）

报告需包含：
1. 近 7 天 ROI 趋势图数据
2. 每日广告花费 vs 收入对比
3. 各地区转化率分布
4. AI 推断的可能原因（价格竞争力 / 广告类型匹配度 / 受众定位）
5. 建议的人工干预方向

### 推广活动关闭说明（触发软边界时生成）

需包含：
1. 该活动的完整数据摘要
2. 关闭理由（数据驱动）
3. 预计影响（流量减少估算）
4. 替代方案建议

---

## 开发 EPIC 拆分建议

**EPIC-001**：项目基础设施
→ Docker Compose 搭建 + PostgreSQL 初始化 + FastAPI 骨架 + 基础鉴权

**EPIC-002**：Cookie 管理与健康检查
→ 首次登录流程 + Cookie 持久化 + 定时健康检查 + 失效警报

**EPIC-003**：Playwright 数据采集
→ API 请求拦截器 + 广告数据采集 + 定时任务调度 + 采集异常处理

**EPIC-004**：成本与费率初始化
→ AI 解析物流/佣金页面 + 人工确认流程 + 商品成本录入界面

**EPIC-005**：AI 分析引擎
→ 利润率计算 + Claude API 集成 + 决策生成 + 边界条件检查

**EPIC-006**：Playwright 执行层
→ 广告出价调整 + 价格调整 + 活动管理 + 软边界暂停确认流程

**EPIC-007**：前端控制台
→ Dashboard + 日志中心 + 警报中心 + 报告查看 + 系统设置

**EPIC-008**：报告与日志系统
→ 操作日志写入 + ROI 为负报告生成 + 活动关闭说明生成

---

## 注意事项

- Playwright 脚本需处理速卖通的反爬机制（随机延迟、User-Agent 轮换）
- 所有 Playwright 执行操作必须先通过边界检查，不允许绕过
- AI 分析结果必须记录原始 reasoning，用于日志溯源
- 数据库需对 `sku_id + snapshot_time` 建立联合索引
- 速卖通后台如有页面改版，采集模块需发出结构变更警报而非静默失败

---

## Claude Code 协作约定

> Claude Code 桌面版每次会话启动时自动加载本文件。以下为协作规范。

### 开工前

- 理解目标，明确改动范围。
- 涉及架构决策或超过 2 个文件改动时，使用 `EnterPlanMode` 制定方案，获得确认后再写代码。
- 复杂任务使用 `TaskCreate` 创建任务拆分、`TaskUpdate` 跟踪进度。

### 开发中

- 工作分支使用 `feature/` 前缀（如 `feature/epic-001-infra`）。
- 需要隔离环境时用 `EnterWorktree` 创建临时 worktree，完成后用 `ExitWorktree` 退出。
- 每次提交保持小且可验证的范围。
- 遵循现有架构边界，在外边界处校验外部数据。
- 优先复用已有工具函数，避免重复造轮子。

### 收工前

- 运行该任务的验证命令（测试、lint、typecheck）。
- 检查 `git diff` 确认改动符合预期。
- 汇总验证结果。

### Git / PR 约定

- 始终创建新 commit，不要 amend 已有 commit。
- 绝不在 `main` / `master` 上直接提交。
- 绝不要 force push 到 `main` / `master`。
- 不要自动合并 PR。
- PR 需包含：改动摘要 + 验证证据（或说明为何无法验证）。
- 使用 `gh` CLI 管理 PR。

### 项目配置

- `.claude/settings.json`：项目级权限与钩子配置。
- `.claude/skills/`：项目自定义技能。
- 数据库连接字符串、API Key 等敏感信息放在 `.env`，绝不提交。

### 可用技能

| 技能 | 触发场景 |
|------|---------|
| `agent-planner` | 将需求规划为 EPIC / TASK 文件 |
| `agent-worker` | 执行 `docs/exec-plans/active/` 中的任务 |
| `agent-reviewer` | 审查 PR / 任务实现 |
| `agent-integrator` | 合并多个任务 PR 到集成分支 |
| `gh-address-comments` | 处理 PR review 评论 |
| `gh-fix-ci` | 诊断和修复 CI 失败 |
| `yeet` | 一键 stage → commit → push → 开 PR |
| `github` | GitHub PR / Issue 分类和路由 |
| `find-skills` | 搜索和发现新技能 |
| `auto-skill-installer` | 根据描述自动安装技能 |
