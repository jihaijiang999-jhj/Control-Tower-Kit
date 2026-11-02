# PILOT-052 Evidence Exception

**状态**：受控例外（不是未验）
**记录时间**：2026-11-02

## 事实

052 的 9 份 evidence 快照取自 `07efc9c`（PROFILE 对象层实现）。随后 CI 抓出 `WIRING` probe 依赖本地环境，052 在 `0a8bf31` 修复（换 `SPEC-COVERAGE`）。因此：

- evidence 里的 `towerctl.py` 是 `07efc9c` 版本，不是最终 `0a8bf31`；
- 052 的 envelope `implementation_head_sha` 仍是 `07efc9c`；
- 052 post-merge 曾失败，053 的 re-envelope 修复后于 2026-10-31 重跑 9/9（609/609）。

## 为什么不回填

- 回填会改 052 的 evidence 哈希、record、envelope，等于重写已合并卡；
- 052 的真实修复由 053 的 CI + post-merge 兜底，052 最终代码 `0a8bf31` 已在 main；
- 按 ADR-0005/053 的“不重写历史”原则，保留原快照并记录例外。

## 覆盖

- 052 的最终代码由 `PILOT-053` 的 PR #37 + 052 post-merge 重跑覆盖；
- 052 的 609 基线已由 053 的 609 继承；
- 后续以 `state-verify`、CI、post-merge 为准，不把 052 evidence 当最终代码快照。

## 结论

**接受为受控例外，不重新生成 052 evidence。** 任何引用 052 evidence 的审计必须同时读本文件与 053 的 MERGE/post-merge 记录。
