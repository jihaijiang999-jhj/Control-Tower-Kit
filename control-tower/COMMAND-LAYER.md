---
schema: tower/design@1
id: DESIGN-COMMAND-LAYER
title: "命令层蓝图：让塔从发号施令变成全局总指挥"
owner: mac
status: draft
version: 0.1
created: 2026-10-28
review_by: 2026-11-30
---

# 命令层蓝图

> 目标：塔不只回答"做了什么、做得对不对"，还能回答"**为什么做、现在打到哪、该停还是该加码、框架怎么改**"。
> 本文件是设计蓝图，不是卡；每张卡的 spec 只引用本文对应章节，避免把五张卡塞进一个 spec。

## 1. 目标与非目标

**目标**

1. 塔能像架构师一样回答四问：产品要成为什么、现在结构是什么、为什么这么设计、以后怎么改。
2. 每张卡能追溯到"战役 → 战略目标"，不再"为做卡而做卡"。
3. 状态只追加、摘要自动生成、旧内容压缩归档，不再维护一份越写越大的状态文档。

**非目标（本期）**

- 不做多写者 / 并行战役；仍保持单写者 + 串行合并。
- 不接生产、不做自动部署。
- 不做"日报/周报/月报/战术地图"四套文档；四本账封顶。
- 不把 `AI-Teacher` 知识库当权威；仓库内文档才是。

## 2. 四本账

| 账 | 文件 | 回答 | 变更频率 | 谁写 |
|---|---|---|---|---|
| **WHY** | `tower-dsh/command/STRATEGY.md` | 产品要成为什么：目标、赌注、非目标、指标 | 季度 | owner + primary |
| **HOW** | `tower-dsh/ARCHITECTURE.md` + `tower-dsh/adr/` | 当前结构、契约、扩展点、关键决策 | 结构变时 | primary + reviewer |
| **NOW** | `tower-dsh/command/campaigns/*.md` + `tower-dsh/status/` | 当前战役、进度、阻塞 | 每卡/每周 | primary（生成）+ owner（定方向） |
| **RULES** | `RED-LINES.md`、`CHANGE-LEVELS.md`、`MAP.md` | 红线、变更分级、判例 | 少改 | owner |

生成物（可重算、不手改）：

- `towerctl brief` → 一页纸（不落盘；`--write` 留到 046）。
- `towerctl campaign-check` → 链接/WIP/过期校验。
- 046 起：`status/index.json`、周 rollup。
- 047 起：`arch-graph`、`arch-check`。

## 3. 目录与 schema

```text
tower-dsh/
  command/
    STRATEGY.md
    campaigns/
      C-2026-Q4-01.md
  status/                  # 046
  ARCHITECTURE.md          # 047
  adr/                     # 047
```

### 3.1 STRATEGY

```yaml
---
schema: tower/strategy@1
id: S-2026-Q4
horizon: 2026-Q4
owner: mac
status: active          # draft | active | archived
review_by: 2026-12-31
goals:
  - id: G1
    text: "可信交付：记录层缺口关闭"
    metric: "0 个未关闭记录层缺口；drift=0"
non_goals:
  - "多写者并行"
bets:
  - "先把控制面做可信，再谈对象层"
---
```

### 3.2 CAMPAIGN

```yaml
---
schema: tower/campaign@1
id: C-2026-Q4-01
goal: G1
status: active          # planned | active | closed | aborted
owner: mac
objective: "..."
key_results:
  - "..."
task_forces:
  - PILOT-045
sequence: "045 → 046；不并行"
stop_conditions:
  - "drift != 0 立即停"
  - "连续 2 卡 FAIL 则复盘战役设计"
budget: "3 张卡 / 2 周"
wip_limit: 1
review_by: 2026-11-11
---
```

## 4. 校验规则（campaign-check）

**错误（exit 2）**

| ID | 规则 |
|---|---|
| E1 | `STRATEGY.md` 缺失/front-matter 非法/无 goals |
| E2 | campaign 的 `goal` 不在 strategy 的 goals 里 |
| E3 | strategy 或 active campaign 的 `review_by` 已过期 |
| E4 | active campaign 的在飞卡数 > `wip_limit` |
| E5 | `task_forces` 引用的卡在 `tasks/` 不存在 |
| E6 | goal id 或 campaign id 重复 |

**警告（exit 0，`--strict` 时升级为错误）**

| ID | 规则 |
|---|---|
| W1 | board 里的卡没有被任何 campaign 引用（未回填） |
| W2 | campaign 已过 `budget` 或 `review_by` 临近（7 天内） |

在飞定义：record 状态 ∈ `dispatched / delivered / reviewed / accepted`。

## 5. brief（一页纸）

```text
# BRIEF — YYYY-MM-DD
## 战略一句话
## 当前战役（目标 / 进度 x/y）
## 在飞（WIP）
## 阻塞 / 返工
## 下一步 3 件
## 待决
## 架构约束（本战役的非目标/停止条件）
```

来源：`STRATEGY.md`、`campaigns/*.md`、`TASK_BOARD.json`、`tasks/*/record.json`、`CURRENT_STATE.json`。只读，不改状态。目标 ≤60 行。

## 6. 阶段（卡序）

| 卡 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| **045** | 命令层 v1：`STRATEGY.md` + `campaigns/` + `campaign-check` + `brief` | — | campaign-check exit 0；brief ≤60 行含七节；E1–E6/W1 夹具全绿 |
| **046** | 状态历史：`status/` 追加快照 + 周 rollup + `index.json` | 045 | 快照只追加；rollup 可重算；旧快照归档 |
| **047** | 架构脊柱：`ARCHITECTURE.md` + `adr/` + `EVENT_CATALOG` + `arch-check` | 045 | arch-check 五条全绿；`DESIGN.md` 归档 |
| **048** | 接线：dispatch 必填 `campaign`；`campaign-check`/`arch-check` 进 post-merge/CI；回填 44 卡 | 045–047 | 孤儿卡 dispatch 被拒；CI 含两个 check |
| **049** | 对象层：`PROFILE` + `profile-check`（∅5） | 047 | 每条不变量有 probe；profile-check exit 0 |
| **050** | shape-check 接 CI + `towerctl` 模块化 | 048 | CI 含 shape 步；单文件 <3000 行 |

`PILOT-043`（记录层纵深）保持 ready，独立轨道，不阻塞 045；建议 045/046 后插回。

## 7. 设计变更规则（补 CHANGE-LEVELS）

- 改 **schema / 事件类型 / 命令接口** = L1 设计变更 → 必须 ADR + 兼容性说明 + 迁移计划。
- 新事件类型必须进 `EVENT_CATALOG`（047 建），否则 `state-verify` 默认放行（已知洞）。
- 弃用：旧路径保留 N 个版本 + 警告；删除需 ADR。
- 手改生成物（brief/index/graph）视为伪造。
- 地图与卡必须双向可查：卡写 `campaign`，campaign 写 `task_forces`。

## 8. 与现有文档的关系

| 现有 | 处理 |
|---|---|
| `DESIGN.md` | 047 归档为 `adr/ADR-0001-initial-design.md`（标注历史提案），不再冒充当前架构 |
| `NEXT-WINDOW.md` | 046 起由 `brief` 生成替代；手写部分只留"待决" |
| `SESSION-CLOSEOUT-*.md` | 作为 status archive 的历史样本保留 |
| `MAP.md` | 保留判例，不混入架构描述 |
| `RED-LINES.md` / `CHANGE-LEVELS.md` | 保留；047 给每条加 probe 链接 |

## 9. 反模式

1. **地图写成散文**：没有指标、非目标、停止条件，无法指挥。
2. **状态大文档**：手写、重写历史、与 ledger 分叉；必须追加快照 + 自动 rollup。
3. **地图与卡两套叙述**：卡不写 campaign，战役不写 goal。
4. **架构文档不可证伪**：没有 arch-check 的架构描述半年后必过期。
5. **层数膨胀**：四本账封顶，不再加"战术/日报/周报/月报"。
6. **手改生成物**：brief/index/graph 必须可重算。

## 10. 开放问题

- Q1：卡是否必须在 `record` 里新增 `campaign` 字段（048 决定），还是只在 campaign 侧列 `task_forces`（045 先用后者）？
- Q2：回填 44 张卡的工作量（048），是否允许"历史卡不追溯、只要求新卡"？
- Q3：`review_by` 过期是警告还是错误（045 先错误，避免地图静默过期）。
