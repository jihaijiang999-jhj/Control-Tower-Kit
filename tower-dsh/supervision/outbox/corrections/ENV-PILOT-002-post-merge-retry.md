# 纠正单 — ENV-PILOT-002 post-merge retry

- 时间：2026-10-19
- 触发：`post-merge --result PASS` 因 `working tree clean` 检查失败，envelope 被置 `CORRECTION_REQUIRED`。
- 根因：主塔在提交根级测试夹具 `tests/test_tower_gates.py` 前就运行了 post-merge，工作树存在未跟踪目录 `tests/`。
- 实质检查：tests exit 0；implementation 是 base 祖先；envelope 文件存在于 base；仅 cleanliness 一项失败。
- 处置：用 `git checkout HEAD --` 把 `supervision/envelopes/ENV-PILOT-002.json` 与 `supervision/MERGE_QUEUE.json` 回滚到已提交的 `MERGED` 状态（不是手改 JSON），提交测试夹具后重跑 post-merge。
- 未做：未改写 ledger；`POST_MERGE_FAILED` 事件保留在 `ledger/supervision.jsonl`。
- 工具缺口（P1-13）：`post-merge` 失败后置 `CORRECTION_REQUIRED`，但命令要求 `MERGED` 才能重试 —— 失败即死锁，必须手工回滚。应在 PILOT-004 修：允许从 `CORRECTION_REQUIRED` 重试，或提供 `post-merge --retry`。
