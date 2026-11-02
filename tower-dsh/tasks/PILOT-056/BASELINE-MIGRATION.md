# PILOT-056 Baseline Migration Record

**状态**：受控迁移（不是普通 baseline-refresh）
**记录时间**：2026-11-02

## 事实

056 把 `tools/towerctl.py` 拆成 23 模块 + 246 行入口，22 个既有长函数从单文件迁移到新模块。`state/SHAPE-BASELINE.json` 的 22 条函数条目随之换文件：

- lines / branches **逐项不变**；
- 迁移前后净债务均为 **1080**；
- `test_shape_baseline_move` 校验 22 条 exact、towerctl 条目移除、无新增长函数、无放宽；
- 塔根与 worktree 的 baseline 字节一致（`665d6633…`）。

## 为什么塔根 baseline 被复制

056 的 deliver 门要求 worktree baseline 与塔根一致。为让迁移后的 23 模块通过 shape，controller 把迁移后的 `state/SHAPE-BASELINE.json` 从 056 worktree 复制到塔根；该路径在 056 spec 的 allowed_paths 内，属于**本次迁移的受控状态更新**，不是普通 refresh。

## 为什么不另开 baseline-refresh 卡

- 056 本身就是 baseline 迁移卡；
- 22 函数 metrics 不变、净债务 0，不需要放宽；
- 另开卡会把同一次迁移拆成两段，反而增加状态窗口。

## 覆盖与边界

- 056 PR 分支的 `shape-check` 0；post-merge 后塔根 `shape-check` 0；
- 若未来需要新增/放宽 baseline，仍必须走独立 baseline-refresh 卡；本文件不构成先例。

## 结论

**056 的 baseline 变更是受控迁移，净债务 0；已记录，不重复开卡。**
