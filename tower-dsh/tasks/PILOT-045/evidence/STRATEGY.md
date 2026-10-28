---
schema: tower/strategy@1
id: S-2026-Q4
horizon: 2026-Q4
owner: mac
status: active
review_by: 2026-12-31
goals:
  - id: G1
    text: "可信交付：记录层缺口关闭"
    metric: "0 个未关闭记录层缺口；drift=0"
  - id: G2
    text: "全局指挥：命令层 v1"
    metric: "campaign-check exit 0；brief ≤60 行"
  - id: G3
    text: "形状可持续：CI 接 shape-check + towerctl 模块化"
    metric: "CI 含 shape 步；单文件 <3000 行"
  - id: G4
    text: "对象层：PROFILE + profile-check"
    metric: "每条不变量有 probe"
non_goals:
  - "多写者并行"
  - "生产接入"
  - "日报/周报/月报"
  - "战术地图"
bets:
  - "先把控制面做可信，再谈对象层"
---

# S-2026-Q4 — 2026 Q4 战略

## 一句话

把塔从"记录发生了什么"推进到"知道为什么做、现在打到哪、该停还是该加码"：先让控制面可信（G1/G2/G3），再碰对象层（G4）。

## 目标

- **G1 可信交付**：`state-verify` drift 保持 0，记录层缺口全部关闭；这是其他一切目标的前提。
- **G2 全局指挥**：命令层 v1 上线——`command/STRATEGY.md` + `command/campaigns/` + `campaign-check` + `brief`，让每张卡都能追溯到战役与战略目标。
- **G3 形状可持续**：把 `shape-check` 接到 CI，并把 `towerctl.py` 拆到单文件 3000 行以内，避免控制面本身腐化。
- **G4 对象层**：`PROFILE` 与 `profile-check` 落地，保证每条不变量都有可执行的 probe。

## 非目标（本期）

- 不做多写者并行 / 并行战役：仍是单写者 + 串行合并。
- 不接生产、不做自动部署、不读凭据。
- 不做日报 / 周报 / 月报 / 战术地图：四本账封顶。
- 本期不把 `AI-Teacher` 知识库当权威，仓库内文档才是。

## 本期赌注

**先把控制面做可信，再谈对象层。** 控制面（记录、门禁、信封、形状）如果不可信，对象层的每一条不变量都会建在流沙上；所以 G1–G3 优先于 G4，048（接线）与 050（模块化）不得越过 045–047 的顺序。

## 复盘

`review_by: 2026-12-31`。到期前由 owner + primary 复盘：哪个 goal 没有指标支撑、哪个 non_goal 被悄悄突破，并把结论写回本文件（季度级变更）。
