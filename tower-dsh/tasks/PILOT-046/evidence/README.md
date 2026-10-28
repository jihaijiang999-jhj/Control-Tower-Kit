# STATUS — 状态历史

塔的 NOW 账本：**只追加、不重写、生成物不手改**。

## 文件

- `YYYY-MM-DD.md` — 当天快照，一条事件一个 `## HH:MM · <卡> · <event>` 段；同日多次追加，不覆盖。
- `index.json` — `status-index` 生成：每天的日期/文件/条目数/sha256，每张卡的 `last_event`/`last_date`，以及 campaign 进度；键排序、无时间戳，可删除后重算。
- `weekly/YYYY-Www.md` — `status-rollup --week` 生成：本周事件数、closed 卡、blocked 计数、wip 变化、campaign 进度。
- `archive/YYYY-Qn.md` — `status-archive --before` 生成：旧快照每天一行摘要；**不删除原快照**。

## 命令

    python tools/towerctl.py status-snapshot --task PILOT-046 --event dispatched --note "..."
    python tools/towerctl.py status-snapshot --task PILOT-046 --event note --tests 486
    python tools/towerctl.py status-index
    python tools/towerctl.py status-rollup --week 2026-W44
    python tools/towerctl.py status-archive --before 2026-10-01

事件：`dispatched` / `delivered` / `reviewed` / `accepted` / `closed` / `note`；`--tests` 记录测试数，`--at` 仅供测试冻结时间。

## 口径

- `campaign`：active campaign 的 `closed/total`（按 `task_forces`），无 active campaign 写 `-`。
- `wip`：全塔在飞卡数 / active campaign 的 `wip_limit`；在飞 = `dispatched|delivered|reviewed|accepted`。
- `blocked`：`rework` 或 `review.verdict=FAIL` 的卡数。
- 四个命令只写本目录，不动 `primary/`、`supervision/`、`ledger/`、`tasks/`。
