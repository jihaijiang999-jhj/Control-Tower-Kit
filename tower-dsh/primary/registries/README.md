# Registries — 实际状态（2026-10-19 审计后更新）

Phase 1/2 实际只有最小机器状态，没有 BI CODE UP 那套完整 registry 集。

## 已存在

| 文件 | 所属 | 作用 |
|---|---|---|
| `primary/TASK_BOARD.json` | Primary | 任务摘要 |
| `tasks/<id>/record.json` | Primary | 任务详情、dispatch、证据、review、decision、closeout |
| `ledger/primary.jsonl` | Primary | 追加式事件账本（无哈希链） |
| `ledger/supervision.jsonl` | Supervision | 监督塔事件账本（无哈希链） |
| `supervision/registries/merge-ledger.json` | Supervision | 合并审计记录 |
| `supervision/MERGE_QUEUE.json` | Supervision | 唯一串行合并队列 |

## 未建（Phase 2 原计划的完整集）

| 文件 | 状态 | 说明 |
|---|---|---|
| `gate-registry.yaml` | 未建 | 门禁决策历史目前只在 `ledger/*.jsonl` |
| `evidence-registry.yaml` | 未建 | 证据索引目前靠 `record.json.evidence` |
| `evidence-acceptance-registry.yaml` | 未建 | — |
| `decision-registry.yaml` | 未建 | owner 裁决目前内嵌在 `record.json.decision` |
| `model-routing-registry.yaml` | 未建 | 路由靠 DSH subagent，无登记 |
| `work-package-orchestration.yaml` | 未建 | — |

## 为什么不急着建

当前只有 1 个任务、1 个 envelope，registry 的收益在多任务并发时才出现。
提前建 6 个空壳会增加"看起来有治理、实际没人写"的假象——与塔的"证据优先"相反。
**触发条件**：真实项目 pilot 出现第 2 个并发任务，或 owner 要求按 BI 模板对齐时再建。
