# NEXT WINDOW — 木塔问答与画像

> 给新窗口的第一条消息用。本文件不是权威状态；权威状态在 `primary/CURRENT_STATE.json`
> 与 `handoffs/HANDOFF-PILOT-002/`。
>
> **快照声明**：下面"当前状态"一段是 HANDOFF-PILOT-002 收官时的值。之后已推进到
> PILOT-020（16+ 张卡、178+ 测试、CI 门 + 分支保护 + `--mode pr` 合并）。要拿实值，
> 读 `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`control-tower/MAP.md`，
> 不要读本文件的数字。

## 当前状态（2026-10-19 收官时）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-010` 全部 `closed`；10 个 envelope 全部 `POST_MERGE_VERIFIED` |
| 规范 | 6 份（4 workflow + 2 policy），`spec-lint --strict` 6/6 |
| 覆盖 | 56 条条款：27 条 tool-check（27/27 有测试）、12 条 review-check、17 条 owner-gate |
| 测试 | **134** 个 |
| 门禁 | spec 强制 / 证据强制 / merge 分支断言 / post-merge 可重试 / handoff 参数化 / ledger 哈希链 / 路径防护 |
| 阶段 | `READY_FOR_PRACTICE` |

## 新窗口要做的两件事

1. **控制塔问答**：回答现实的工程/开发问题，必须结合本塔现状（引用文件、命令、数字），不空谈。
2. **画一张控制塔地图/画像**：把组件关系、数据流、单点、空白画出来，产出 `control-tower/MAP.md`。

## 第一条消息（复制到新窗口）

```text
你是 tower-dsh 的接续 controller，代号 ctl-yingxian-qa-001。
工作区：C:\Users\mac\Documents\deepseek-harness\default-workspace
塔根：C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh

先读：
1. tower-dsh/NEXT-WINDOW.md
2. tower-dsh/handoffs/HANDOFF-PILOT-002/HANDOFF.md
3. tower-dsh/primary/CURRENT_STATE.json
4. tower-dsh/TOWER.md、START-HERE.md、RED-LINES.md、CHANGE-LEVELS.md
5. tower-dsh/specs/WF-TASK.md、WF-MERGE.md、WF-HANDOFF.md、WF-LEDGER.md

然后依次执行：
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py handoff-check --package HANDOFF-PILOT-002
python tools/towerctl.py handoff-claim --package HANDOFF-PILOT-002 --controller ctl-yingxian-qa-001
python tools/towerctl.py handoff-receipt --package HANDOFF-PILOT-002 --controller ctl-yingxian-qa-001
python tools/towerctl.py handoff-accept --package HANDOFF-PILOT-002 --controller ctl-yingxian-qa-001
python tools/towerctl.py handoff-activate --package HANDOFF-PILOT-002 --controller ctl-yingxian-qa-001

自检后报告一句结果，然后进入问答。
问答与画图阶段只读：不改状态、不 merge、不碰生产、不外部调用。
地图产出写到 control-tower/MAP.md。
```

## 问答纪律

- 每个回答分三截：**本塔现状**（文件/命令/数字）→ **一般工程判断** → **对本塔的影响**。
- 不确定就写“不确定”，不为了好听承诺未实现的能力。
- 区分“已实现 / 已测 / 仅文档 / 尚未做”。

## 停点格式（硬规则）

**任何一次停下来，必须给全这四段。缺任何一段等于没有交接。**

```text
① 现状    —— 现在到哪一步；用数字、哈希、状态值，不用形容词
② 下一步  —— 只给一步（默认），最多两步
③ 执行口令 —— 用户复制这一句就能推进：
              本窗口继续 -> 一句短语（如"继续 019"）
              换新窗口   -> 自包含的完整 prompt（路径 + 读序 + 当前卡 + 流程 + 约束）
④ 判据    —— 怎么算这一步做完了；可执行、可验证（命令 + 阈值）
```

反面例子（2026-10-20 之前的停点）：只报"019 执行中、018 已合并 + 测试数字"，
没有 ②③④ —— 用户无法判断下一步，也无法把工作交给另一个窗口。

配套约束：

- 停点时**不许**只说"进行中"；进行中也要说清"卡在谁身上、回来之后我做什么"。
- 给出的执行口令必须**可直接粘贴**，不要求用户补齐路径或参数。
- 判据必须能被第三方复算（命令 + 期望输出），不能写"看起来没问题"。

## 地图要求

- 一张主图（ASCII 或 Mermaid 均可）。
- 每条边标注：**数据流方向、触发命令、失败后果**。
- 标出**单点**：只有一个人/一个文件/一个命令的地方。
- 标出**空白**：远端 PR/分支保护、Console、多任务并发、真实项目 pilot。
- 标出**已证明**与**仅声明**的边界（用 `spec-coverage` 的数字说话）。

## 收官时的已知 backlog

- P1-6 程序性身份（`--role supervisor` 是字符串）；
- P1-14 合并队列只校验状态，不做真互斥；
- 远端 PR / 分支保护未接；
- Console / presets（Phase 4）未做；
- lint strict 只识别小写裸命令；根目录 md 丢 front matter 会被静默跳过；
- 覆盖提取器对非 TestCase / 继承方法有盲点（当前仓库未触发）。
