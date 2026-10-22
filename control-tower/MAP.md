# tower-dsh 控制塔地图 / 画像

> 生成者：`ctl-yingxian-qa-001`（接续 controller）· 生成时刻：2026-10-19T23:5x +08:00
> 性质：**只读快照**。不替代 `tower-dsh/primary/CURRENT_STATE.json`，不构成状态。
> 修订：2026-10-20T00:5x —— §6 由"漂移"改为"已闭合"，§1 phase 按实值更正，§8 口径同步。
> 修订：2026-10-20T02:2x —— PILOT-011 落地（authority drift 可观测）；§3/§5/§6/§7 同步，新增 §6.2 排序陷阱。
> 修订：2026-10-22T00:4x —— PILOT-022/023/024/025 落地（状态重放收紧、证据完整性、门禁解码、测试计数门）；§4.2 ∅10/∅11、§5、§6.9–6.11 同步。
> 修订：2026-10-22T15:3x —— PILOT-026 落地（塔套件计数入闸）；∅11、§5、§6.11 同步。
> 修订：2026-10-22T20:5x —— RUN-2026-10-22-B 批跑（027 runner/TMP、028 迁移合法性、029 baseline 必填）；∅10–∅12、§5、§6.12 同步。
> 修订：2026-10-23T03:0x —— RUN-2026-10-23-C 批跑（030 queue-add 门、031 单调锚点、032 完成卡禁止重置）；∅10/∅11、§5、§6.13 同步。
> 依据：`startup` / `wiring` / `status` / `handoff-check` / `spec-coverage` / `verify-ledger` 实跑输出 + 代码通读 + git 实值 + 一次测试复跑。
> 标注约定：`[证]` 有可执行证据 / `[声]` 仅文档或口头声明 / `[无]` 未做 / `⊙` 单点 / `∅` 空白。

---

## 0. 一句话读数

**木塔能证明"发生过什么"，能查"现在是什么"，但不能推导"现在必须成立什么"。**

- 过程层已经硬化（spec 冻结、证据强制、merge 分支断言、账本哈希链都是真门，`exit 2` 不是建议）；
- 对象层是空的（56 条条款全是"塔怎么管自己"，没有一条是"被迭代系统必须永远成立什么"）；
- 账本只有一个读消费者（`check --phase spec` 查 `SPEC_APPROVED`），其余全是写——历史存在，但不约束现在。

---

## 1. 主图：组件与权威归属

```text
                    ┌──────────────────────────────────────────────────────────┐
                    │  OWNER  mac          四闸：merge / 外部调用 /             │
                    │                     部署·生产数据 / L0 文档写 main       │
                    │                            ⊙O                             │
                    └───────┬──────────────────────────────┬───────────────────┘
              E1 授权(口头)  │                              │  E2 裁决/接受(口头)
              无命令、无签名  ▼                              ▼  无命令、无签名
        ┌───────────────────────────────┐        ┌────────────────────────────────┐
        │ PRIMARY                       │        │ SUPERVISION                    │
        │ id: ctl-yingxian-qa-001       │  E7    │ id: sup-phase2-pilot           │
        │ phase: HANDOFF_ACTIVE         │───────▶│ phase: PHASE_2_PILOT_VERIFIED  │
        │ 职责: spec/routing/gates/     │信封 +  │ 职责: 独立验收/串行队列/       │
        │       evidence/closeout       │入队    │       merge/post-merge/纠正    │
        │ 工具: tools/towerctl.py ⊙T    │        │ 队列: MERGE_QUEUE.json ⊙Q      │
        └──┬────────┬────────┬──────────┘        └────┬─────────────────┬─────────┘
     E3    │   E4   │   E5   │                        │ E8 merge        │ E9
   spec冻结│ 三写    │ 事件    │                        ▼                 ▼
           ▼        ▼        ▼                  ┌──────────────┐  ┌──────────────┐
    ┌──────────┐ ┌────────┐ ┌──────────┐        │ pilot/repo   │  │ merge-       │
    │ spec     │ │ record │ │ ledger   │        │ main (base)  │  │ ledger.json  │
    │ *.spec   │ │ board  │ │ *.jsonl  │        └──────┬───────┘  └──────────────┘
    │ .json    │ │ state  │ │ 哈希链 ⊙L│               │ E10 post-merge
    └──────────┘ └────────┘ └──────────┘               ▼
                                     ┌──────────────────────────────┐
                                     │ supervision/reviews/*.txt    │
                                     │ tasks/<id>/MERGE.md          │
                                     └──────────────────────────────┘

    旁路（横向，不属于主脊）：
    ┌────────────┐   E11 handoff    ┌──────────────────────────────┐
    │ handoffs/  │◀────────────────▶│ handoff-new/claim/receipt/   │
    │ <pkg>/     │                  │ accept/activate              │
    └────────────┘                  │ 写 CURRENT_STATE + ledger    │
                                    └──────────────────────────────┘
    ┌────────────────────────────────────────────────────────────────────────────┐
    │ GIT：workspace 根 = Control-Tower-Kit 仓（origin: github/…/Control-Tower-   │
    │ Kit.git），跟踪 199 个 tower-dsh 文件；但 towerctl 不提交 ⊙C（见 §4）      │
    └────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 边表（每条边：方向 / 触发 / 失败后果）

| # | 从 → 到 | 流动的东西 | 触发命令 | 失败后果 | 门 |
|---|---|---|---|---|---|
| E1 | owner → primary | 授权（口头） | 无 | 越权即红线 `C-01`/`C-04`，但**无法证伪** | `[声]` owner-gate |
| E2 | owner → primary | 接受裁决 | `accept --decision <id>` | `--decision` 只是字符串，无人签名，可自填 | `[声]` |
| E3 | `pilot/<ID>.spec.json` → `record.spec_sha256` | 冻结的 spec 哈希 | `task-new` | 改 spec 即 gate 失效（每次实时复算，`towerctl.py:442-470`） | `[证]` |
| E4 | spec 批准 → `ledger` | `SPEC_APPROVED` 事件 | `spec-approve --by <name>` | `--by` 是裸字符串；事件行可手写伪造（P1-11 仍在） | `[声]` |
| E5 | `check` → `record.spec_gate` → `dispatch` | PASS 字段 | `check --phase spec` → `dispatch` | 未 PASS 时 `dispatch` exit 2（PILOT-002 已修 P0-1） | `[证]` |
| E6 | primary → record / board / ledger | 三处并行写 | `dispatch`/`deliver`/`checkback`/`accept`/`close` | 中途异常则三处漂移；**无重建、无比对、无自愈** | `[无]` |
| E7 | primary → supervision | 信封 + 入队 | `envelope-new` / `queue-add` | primary 写 supervision 账本（`towerctl.py:1846`）——**单写者破口**；设计上 primary 不 merge 但能写对方账本 | `[证]` 有断言 `supervisor != primary` |
| E8 | supervision → pilot/repo | 真 `git merge --no-ff` | `merge --role supervisor --envelope` | 当前分支 ≠ base → `CORRECTION_REQUIRED`（P0-3 已修，`1919-1936`） | `[证]` |
| E9 | merge → 队列 / 信封 / 合并账本 | 状态 + merge commit | 同上 | merge 成功后写三处；若写错，队列与账本分叉 | `[证]` 部分 |
| E10 | post-merge → reviews / MERGE.md / queue | 验证结论 | `post-merge --result PASS` | 4 项检查；**测试只看 exit code，空测试集也 PASS** | `[证]` + `[无]` 计数门 |
| E11 | handoff 命令 → 包 / CURRENT_STATE / ledger | 交接状态机 | `handoff-new/claim/receipt/accept/activate` | 写 state 后**不提交**（本次实例：3 M + 4 ??，见 §6） | `[证]` 21 项 check |
| E12 | executor → worktree 文件 | 实现 | 人工 / subagent | `allowed_paths` 只存不验（P1-1 仍未做 `git diff` 校验） | `[无]` |
| E13 | executor → `tasks/<id>/evidence/` | 证据副本 + SHA-256 | `deliver` | CRLF / git blob 语义未定；复核者可能误报 | `[证]` 哈希，`[声]` 语义 |
| E14 | ledger → ??? | 历史 | — | 只有 `check --phase spec` 读一次；**其余无消费者** | `[无]` |
| E15 | 塔 → git | 提交 | **无命令，靠人** | 真相可不在历史里（见 §6） | `[无]` |

---

## 3. 单点（只有一个人 / 一个文件 / 一个命令的地方）

| # | 单点 | 位置 | 为什么是单点 | 断了会怎样 |
|---|---|---|---|---|
| ⊙O | owner `mac` | `primary/CURRENT_STATE.json:owner` | 四闸全归一人，且授权是口头 | 无人可批 = 全塔只读 |
| ⊙T | `tools/towerctl.py` | 2 394 行 / **33 个子命令** | 唯一状态写者；没有任何第二实现 | 工具坏 = 全塔停摆，且状态无法恢复 |
| ⊙Q | `supervision/MERGE_QUEUE.json` | `supervision/` | 唯一合并队列 | 丢失即无法判断在途合并 |
| ⊙L | `ledger/.lock` | `ledger/` | 串行化并发写 | 竞争写 = 断号/丢事件 |
| ⊙S | `sup-phase2-pilot` | `supervision/CURRENT_STATE.json` | 只有一个 supervisor 会话；`--role supervisor` 是字符串 | 任何人带参数即可 merge（P1-6） |
| ⊙C | 手工 commit | 无 | 状态写完后无自动提交步骤 | 本次 handoff 产生 7 个未提交改动，已由 `26d2f6f` 人工闭合（§6）；**PILOT-011 起 `status`/`startup` 报 `authority_dirty`、`handoff-activate` 报 `commit_required`——能看见，但仍要人提交** |
| ⊙E | `%TEMP%` ACL | `%TEMP%\dsh-*\` | 134 个测试先在临时目录建塔 | ACL 一变，全套回归 0.056 s 全 ERROR（§5） |
| ⊙P | Python 3.12.10 + Windows | `HANDOFF.md §3` | 唯一已验环境 | 换环境即"绿"不可复现 |
| ⊙G | `spec_gate` 单字段 | `record.json` | 一个字段决定 `dispatch` 放行 | 该字段被误写 = 绕过第一道闸 |

---

## 4. 空白（`∅` 未做 / 没有）

### 4.1 本塔已知（`NEXT-WINDOW.md` backpack + `AUDIT`）

| # | 空白 | 现状证据 | 后果 |
|---|---|---|---|
| ∅1 | 远端 PR / 分支保护 | main 已保护（禁强推/禁删分支/要求 `tower gate`）；`merge --mode pr` 已**真实跑通**：PILOT-016 经 GitHub PR #1 合并（merge `29d8ec6`），PR 上 `tower gate` 绿后由 `gh pr merge --merge` 合入并本地 ff；`enforce_admins=false` | 门对非管理员是硬的；owner 仍可直推。全锁需要状态提交也走 PR（不做，理由见 §6.5） |
| ∅2 | Console / presets（Phase 4） | 无代码 | 操作全靠 CLI |
| ∅3 | 多任务并发 | 队列只校验 `entry.status`，不排斥并发 `MERGING`（P1-14） | 并发合并可能写坏 base |
| ∅4 | 真实项目 pilot | 只有 `pilot/repo` 玩具项目（10 个 worktree） | 未证过接第二个项目 |

### 4.2 本次新增（对照 K3 控制塔后识别，按重要性排序）

| # | 空白 | K3 塔有什么 | 木塔现状 | 补法（可执行物，非文档） |
|---|---|---|---|---|
| ∅5 | **对象层画像**（系统事实冻结） | `_k3-ops/db-profile/database-profile-v1.md`：冻结 PG 18.x 精确 minor、Prisma Rust-free、池化位置、唯一迁移路径、`db push` 禁止；状态行明写"不授权依赖/schema/迁移/供给" | 只有元层 spec（塔怎么管自己）；没有一条关于被迭代系统 | `state/PROFILE-<object>.md`，每条不变量配一个 `probe` 命令，`towerctl profile-check` 失败 exit 2 |
| ∅6 | **锚点 + 趋势 diff + 熔断** | `architecture-trend-governance.md`：逻辑超长 266 / 页面 3 / CLI 4 / 已知环 2 / 🟡 2；周测只报 diff；新增环>0 或 🟡>10 即停新功能 | 只有"134 测试全绿"一个快照，无趋势、无阈值、无熔断 | `state/BASELINE.json` + `towerctl trend-diff`（每周/每 merge 出 diff）+ 阈值与"停新功能"动作 |
| ∅7 | **授权态单写者** | `SeeMake-Control-Tower-Authority-State.md`：Active Tower / Single Writer / 保留闸 / repo+queue 锚点 | `--role supervisor` 是参数，不是身份；`CURRENT_STATE.primary` 只有一个字符串 | `state/AUTHORITY.json` + `towerctl authority-check`（写者≠活性塔即拒写） |
| ∅8 | **判例集** | `rules-ref/治理判例集.md`：一次裁决 → 以后可引用的规则 | 5 条散在 `HANDOFF.md §6` | ledger 增加 `PRECEDENT` 事件 + `towerctl precedent --list` |
| ∅9 | **包号防呆** | `_k3-ops/CURRENT`：包号比你所持新即停手 | `handoff-check` 只在 claim 时跑一次 §0 漂移 | 根目录 `CURRENT` + `startup` 强制比对 |
| ∅10 | **状态重放** | （K3 也没有） | **已实现并持续收紧**（PILOT-021/022/023/028/032）：ledger 折叠状态并与 record/board/queue/envelope 比对；坏文件算 drift，合法跳过显式 `skipped`，board 取重放值；证据逐条校验 SHA-256/字节数，spec 校验冻结哈希；状态迁移按真实历史表校验，跳步/乱序记 `illegal_transition`；`TASK_NEW` 只允许未完成状态重建，accepted/closed 重置判红。真实塔 32 任务/32 信封、237 条证据、drift 0 | 仍窄：`ready→TASK_NEW` 仍合法；未来新增生命周期事件若漏表会默认放行（建议完整性断言）；关闭卡无正式 reopen 流程；TOCTOU/hardlink 不在范围 |
| ∅11 | **测试计数门** | （K3 也没有） | **已实现并合围**（PILOT-025/026/029/030/031）：`post-merge` 解析 `Ran N tests`；根/塔套件按 baseline 设门；`envelope-new` 与 `queue-add` 都强制两个 baseline；baseline 不得低于 ledger 里已验证 `tower_tests_count` 的最大值。真实塔：根 `2/2`、塔 `281/281`、anchor `281>=277`，7/7 | 仍窄：直接手改 `MERGE_QUEUE.json` 可绕过入队门；伪造/错误 verified 事件可抬高锚（fail-closed DoS）；锚不追溯旧事件；只校数量不校质量 |
| ∅12 | **证据可复现** | — | **已实现切片**（PILOT-027）：`tools/run_tests.py` 把 `TMP/TEMP/TMPDIR` 指向仓内 `.test-tmp/run-*`，post-merge 与根门禁都走 runner；`REPRODUCE.md` 给出干净环境复跑清单；全套件 281 绿 | 仍窄：`.test-tmp` 不自动清理；运行器依赖 Windows 下的 core.longpaths 注入；直接 discovery 不走沙箱 |

---

## 5. 已证明 / 仅声明 / 未做（用数字说话）

| 能力 | 判定 | 证据 |
|---|---|---|
| spec 冻结（改 spec 即失效） | `[证]` | `spec_gate_errors` 每次实时复算 SHA-256（`towerctl.py:442-470`） |
| `dispatch` 前置 spec 门 | `[证]` | `cmd_dispatch:932-934`；PILOT-002 回归测试 |
| accept / close 强证据 | `[证]` | `cmd_accept:1022`、`cmd_close:1046` 内联 `check_evidence` |
| reviewer 非空且 ≠ executor | `[证]` | `cmd_checkback:992-996` |
| merge 分支断言 | `[证]` | `cmd_merge:1919-1936`，不符即 `CORRECTION_REQUIRED` |
| post-merge 七检 | `[证]` | 测试 / 根套件计数 / 塔套件计数 / baseline 不回退 / 实现是祖先 / 信封在 base / 工作树干净（RUN-C 后；count 检查对旧信封 opt-in） |
| 路径越界防护 | `[证]` | `ensure_within` 覆盖 evidence / worktree / package / envelope / repository |
| ledger 哈希链 | `[证]` | `verify-ledger` → primary 292 事件、supervision 168，0 error；legacy 未哈希 53 / 26（按 INV-05 只计不判） |
| 条款→测试绑定 | `[证]` | `spec-coverage`：6 份规范 / 56 条款 / tool-check 27 / covered **27** / gaps 0 |
| 测试全绿 | `[证]`（有条件） | `Ran 281 tests / OK`（本地 2026-10-23，RUN-C 后）；GitHub Actions 在 PR #15–#17 上绿，v7 后零注解。**建议跑法**：`python -B tools/run_tests.py`（TMP 在仓内，避受限沙箱 ACL）；直接 discovery 仍可用，但受限模式下 `%TEMP%` 仍会让 134/134 在 0.05 s 内全 ERROR |
| 29 条条款靠人 | `[声]` | 12 `review-check` + 17 `owner-gate`（`spec-coverage.manual` / `.owner`） |
| "每次迭代全局正确" | `[无]` | 无对象层不变量、无趋势锚点、无状态重放 |
| 32 个任务 / 32 个信封 | `[证]` | 全部 `closed` + `POST_MERGE_VERIFIED`（011 `6a849b9`；012 `bc4be88`；013 `10bf606`；014 `4ef0695`；015 `ae4eb4f`；016 PR #1 `29d8ec6`；017 PR #2 `6796d1d`；018 PR #3 `46e946c`；019 PR #4 `474cfb3`；020 PR #5 `63aa31d`；021 PR #6 `10fae79`；022 PR #7 `6a920a5`；023 PR #8 `a88388b`；024 PR #9 `c4fb58f`；025 PR #10 `f265847`；026 PR #11 `e73f1f5`；027 PR #12 `223b10b`（塔 `252/246`）；028 PR #13 `188f122`（塔 `261/252`）；029 PR #14 `ef72400`（塔 `266/261`）；030 PR #15 `aa88f76`（塔 `271/266`）；031 PR #16 `c9a7da6`（7/7，塔 `277/277`，anchor `277>=271`）；032 PR #17 `da5a25c`（7/7，塔 `281/281`，anchor `281>=277`），其余 post-merge 均 4/4） |

---

## 6. 生成时刻的漂移（已闭合）

**观测（23:5x）**：`handoff-activate` 成功后，权威状态**未提交**——

```text
 M tower-dsh/ledger/primary.jsonl
 M tower-dsh/primary/CURRENT_STATE.json
 M tower-dsh/handoffs/HANDOFF-PILOT-002/package.json
?? tower-dsh/handoffs/HANDOFF-PILOT-002/CLAIM.json
?? tower-dsh/handoffs/HANDOFF-PILOT-002/RECEIPT.md
?? tower-dsh/handoffs/HANDOFF-PILOT-002/ACCEPTANCE.json
?? tower-dsh/handoffs/HANDOFF-PILOT-002/ACTIVATION.json
```

含义：那一刻的"真相"只在工作区；任何人 clone `Control-Tower-Kit` 得到的仍是 `ctl-phase3-receiver-001` 当 controller。

**闭合（00:5x，owner 逐次授权）**：`26d2f6f` `state: HANDOFF-PILOT-002 ACTIVE (ctl-yingxian-qa-001)`，7 files / +401 / −10，内容恰为上述三改四增，无手改、无夹带。ledger 以 seq 100–103 接入哈希链（`fd132d…` → `fbe0ae…` → `75fb59…` → `a26a211…` → `a5622e4…`），`verify-ledger` 0 error。

**残余**：闭合靠的是人记得提交，不是工具保证（⊙C / ∅10 仍未解）。本文件以独立 `docs:` 提交入库——地图是投影，不与状态混在一次提交里。

### 6.1 PILOT-011 的闭合（2026-10-20）

把"靠人记得"变成"工具会喊"：`status` / `startup` 新增 `authority_dirty` / `authority_dirty_count`，`handoff-activate` 新增 `commit_required` 与可直接执行的 `commit_hint`；**工具仍不自动 commit**（commit 边界归人）。

全闭环实跑：`task-new → spec-approve → check spec/ready → dispatch → deliver(5 证据) → 独立 reviewer FAIL（AC-8：整个 `handoffs/`/`ledger/` 目录被删时漏报）→ rework → 复验 PASS → accept/close → envelope → queue → merge `6a849b9` → post-merge 4/4`，146 tests。

值得记的两点：返工不是走过场——独立 reviewer 找到的漏报（watched 被 `exists()` 过滤）是真的，executor 自己写的 9 个测试没覆盖它；修复顺带解决了中文路径被 `core.quotepath` 转义的问题。

### 6.2 协议陷阱：状态提交会把 base 推离分支点

`envelope-new` 要求 `main` 是 `implementation_head` 的祖先。若在**建分支之后、建信封之前**把塔状态提交到 `main`，这条立刻不成立：

```
main:              f65b9f2 → 03889d3 (state: PILOT-011 closed)   ← 我先做了这一步
pilot/PILOT-011:   f65b9f2 → 5ec4443 (实现) → 608d082 (信封)
envelope-new → FAIL: "base main is ancestor of implementation"
```

处置：`git reset --mixed HEAD~1` 撤回**我自己刚做、尚未推送**的状态提交（文件原样保留），让 `main` 回到分支点，再建信封 → 合并 → 最后统一提交状态。没有改写已推送历史，也没有丢文件。

**应写进 `WF-MERGE` 的结论**：状态提交只能在 `merge` 之后（或至少不早于 `envelope-new`）。这是工具没拦、只能靠顺序纪律的地方——正是 ⊙C 想消灭的那类隐式约束。

### 6.3 PILOT-012：门从"人跑"变成"平台跑"（但还没接上锁）

`PILOT-012` 新增 `.github/workflows/tower-gate.yml`：`pull_request` / `push: main` / 手动触发，`windows-latest` + Python 3.12，在 `tower-dsh` 下跑全量测试 + `spec-lint --strict` + `spec-coverage` + `verify-ledger`，`status` 只记录不判红。另加 `.github/CODEOWNERS` 与 10 个回归测试（把 workflow 契约钉死，变异测试可证：删命令/换 runner/去 working-directory/降 Python/移动 `continue-on-error`/去掉 `--strict` 都会红）。

闭环：`cde8f1d`（实现，156 tests）→ `7f600bc`（信封）→ `bc4be88`（merge）→ post-merge 4/4。

**但它现在是"未通电"的**：没有 push，GitHub 上不跑；没有 branch protection，本地 merge 也拦不住。已知盲区（reviewer 记录）：测试只断言"命令文本出现"，注释掉 `run:`、加 `if: false`、接 `|| true` 都抓不到；这类语义必须靠"真的跑一次"来兜底——所以 push + 首次 CI 结果才是这张卡的最终证据。

（后续：PILOT-013/014 修完两个由 CI 发现的缺陷后，run 39346811217 九步全绿、零 `##[error]`。"通电"这一半已经成立；缺的只剩 branch protection。）

### 6.4 判例：绿 ≠ 正确——`continue-on-error` 吞掉真崩溃

run 39344018538 整体显示 success，但 `Status` 步骤其实 **exit 1**：

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 244-253
```

原因是 GitHub Windows runner 的控制台不是 UTF-8，而 `status` 要打印中文任务标题。`continue-on-error: true` 本意是"权威状态脏了不要判红"，却把"工具坏了"也一起吞了。

处置（PILOT-014）：`towerctl` 启动时把 stdout/stderr 重配为 UTF-8；同时**删掉该步骤的 `continue-on-error`**，因为 `status` 对脏状态本来就 `exit 0`，会失败只可能是真异常。

**判例**：容错设置必须区分"预期内的坏结果"（脏状态）与"工具坏了"（异常）。把两者都设成 `continue-on-error`，等于给自己发一张"永远绿"的假证书。

### 6.5 判例：计划限制不是实现缺陷

`gh api PUT .../branches/main/protection` 首次返回：

```
403 Upgrade to GitHub Pro or make this repository public to enable this feature.
```

私有仓 + 免费计划下，服务端分支保护**不可用**。处置：owner 决定把仓库转为 public（公开前已扫描工作树与全部 81 个提交，无密钥/令牌/私钥模式命中），随后保护成功开启。

**归因教训**：MAP 早先把 ∅1 写成"没做"，实际有一半是"做不了"。**把限制误记为欠账，会让人以为再努力一点就行**——这类错误比漏记更贵。

### 6.6 判例：桩比真实环境宽容，就是在测想象

PILOT-015 给 `merge` 加了 `--mode pr`。首轮实现 + 11 个测试全绿，独立 reviewer 判 **FAIL**，理由只有一句：

> 真实 `gh` 2.96 **没有** `gh pr create --json`；真实行为是只打印 URL。桩接受了 `--json` 并返回 JSON，所以测试测的是想象。

而这句 `--json` 是**我自己写进 spec 的**——spec 与实现同源错误，两轮自动化检查都没抓到，靠独立复核抓到了。

同轮还暴露两个真实缺口：`TOWERCTL_GH` 指向"存在但不可执行"的文件时 `Popen` 抛 `OSError` 未捕获，队列**永久卡在 `MERGING`**；以及 PR 已在远端合并、本地 ff 失败时，塔里连 PR 号都没落盘，重试会撞"PR already exists"。后者已改为"合并后先落盘 `pr_number`/`remote_merged`，再 ff；重试跳过远端半程"。

**判例**：桩必须模拟真实工具的**缺陷**（拒绝它不支持的 flag、只输出它真的会输出的东西），否则测试只证明"我的假设自洽"。另：**spec 也会写错**，冻结的是契约不是真理——错了要按证据改实现，并在 REVIEW 里记明偏离，而不是让测试去迁就错的 spec。

**同时更正**：`handoff-activate` 把 phase 从 `READY_FOR_PRACTICE` 改为 `HANDOFF_ACTIVE`、`next_action` 改为 `resume from handoffs/HANDOFF-PILOT-002/HANDOFF.md`；§1 主图已按实值更新。

### 6.7 第一次真实 PR 合并（2026-10-20）

`merge --mode pr` 第一次在真机上跑完整条链，用的是**被合并分支里的新 towerctl**（`--root .`，即用待合并的代码合并它自己）：

```
push pilot/PILOT-016 → gh pr create → PR #1 出现
→ gh pr checks --watch（GitHub 上 tower gate 跑绿）
→ gh pr merge --merge → merge 29d8ec6
→ git fetch + merge --ff-only → 本地 main 跟上
→ post-merge 4/4 → POST_MERGE_VERIFIED
```

信封实值：`merge_mode=pr`、`pr_number=1`、`pr_url=.../pull/1`、`check_conclusion=success`、`remote_merged=true`、`merge_commit=29d8ec6`。

这一步的意义不是"多了一条合并路径"，而是：**代码进 main 的门第一次由 GitHub 服务端裁决，而不是由本地说"我跑过了"。** 剩下的软处只有 owner 直推（§6.5 已说明为何不锁死）。

---

### 6.8 小卡四连（2026-10-20 晚）：修 backlog，而不只是记 backlog

| 卡 | 修了什么 | 判据 |
|---|---|---|
| 017 | `authority_dirty` 覆盖 `tasks/` 与 `pilot/`（原来漏了任务卡与 spec） | 删/改任务卡与 spec 会被计入；被 gitignore 的 worktree 不计入 |
| 018 | `deliver` 重投递导致证据 ID 全同 | 真实 record 从 5×`E-006` 变成 `E-001..E-006`；旧代码上同一探针失败 |
| 019 | checks pending 判定从"猜文本"改为 **gh 退出码 8** | 真实失败输出含 `no checks` 时立即 block（calls=1），旧代码要重试到 timeout |
| 020 | Actions `v4/v5` → `v7` | PR #5 用 v7 跑自己，全绿且**注解区为空**（Node 20 告警消失） |

两张卡的方法值得记：018 和 019 都做了**旧代码上的对照实验**（同一探针跑 main 版工具），证明"测试有鉴别力"，而不是"测试和实现一起写的"。019 还顺带暴露一个通用原则：**CLI 集成优先读退出码，不要读文案**——文案会误伤，退出码是契约。

排序上仍然串行：四张卡依次 PR #2→#5。并行会撞 `base` 祖先断言（§6.2）。

### 6.9 状态第一次可以"重算"（PILOT-021）

`towerctl state-verify` 把两份 ledger 按 `seq` 折叠成期望状态，再与 `record` / `board` / `queue` / `envelope` 比对。真实塔首跑：**21 任务 / 21 信封 / drift 0**。

意义：此前"状态是真的"依赖两个假设——工具不半途失败、没人手改。现在多了一条可执行判据：**如果状态是假的，重放会对不上**。它和 `verify-ledger`（历史不可篡改）、`authority_dirty`（状态未提交）合起来，构成了 A 层（全局一致）的三件套。

**PILOT-022 收紧（2026-10-20 23:5x）**：坏文件不再被当跳过——record/envelope 缺失或坏 JSON 各报 `record_missing`/`record_unreadable`/`envelope_missing`/`envelope_unreadable`；board/queue 坏文件各报一条 `board_unreadable`/`queue_unreadable`（不再逐实体静默跳过）；`board_status` 的 expected 改用重放值，record 与 board 同错时两条 drift 都报；合法跳过显式进 `skipped`/`skipped_count`（exit-neutral）。214 tests；独立探针在 main 版工具上让 15 个新用例失败；真实塔 22 任务/22 信封 drift 0。

**PILOT-023 继续收紧（2026-10-21 04:xx）**：证据不再只信记录——逐条校验 `record.evidence` 的文件存在、SHA-256 与字节数，坏条目/越界路径/不可解析路径分别成 drift；`spec_sha256` 对冻结 spec 复核。越界判定先做纯词法 containment（不触盘），再对根内候选做符号链接检查与 realpath 复核；路径访问异常一律转 drift，绝不 traceback。236 tests；真实塔 `evidence_checked=154`、drift 0。

已知边界（reviewer 实测，不是推测）：

- 重放是"最后写入者胜"，不校验迁移合法性（`TASK_NEW → CLOSEOUT` 也接受）；
- 带生命周期的**非法信封 id** 既不进 drift 也不进 skipped（安全选择：绝不作路径打开）；
- 证据路径词法前缀大小写敏感、根内符号链接一律保守按 escape；TOCTOU/hardlink 不在范围。

用法：真塔上 `python tools/towerctl.py state-verify`，exit 0 = 状态与历史自洽。

### 6.10 判例：post-merge 的假红来自解码契约（PILOT-024）

PILOT-023 首次 post-merge 判红：

```text
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbf in position 31994: invalid start byte
TypeError: can only concatenate str (not "NoneType") to str
```

原因不是实现：塔套件子进程按本地代码页（cp936）写 stderr，被跳过的 symlink 用例带出本地化 WinError 文本；根门禁却按严格 UTF-8 解码，reader 线程死掉后 `stdout`/`stderr` 变成 `None`。修复（PILOT-024）：子进程注入 `PYTHONIOENCODING=utf-8`，父进程以 UTF-8 + `errors="replace"` 解码，输出归一到 `str`，并加 raw `0xbf` 回归测试。旧策略下同一 236 套件稳定复现 31994 字节错误；修复后 post-merge 4/4，PILOT-023 重试转 `POST_MERGE_VERIFIED`。

**判例**：门禁的失败信号必须来自被测对象，而不是门禁自己的解码器。本地化输出是环境事实，不是产品缺陷——把两者混在一起，就会得到一张"永远红"或"永远绿"的假证书（对照 §6.4）。

### 6.11 判例：exit 0 不等于跑对，卡漏文件不等于可以原地改（PILOT-025）

`post-merge` 过去只认退出码：`tests/` 为空、套件缩水都 PASS。PILOT-025 让门禁解析 `Ran N tests`，并要求 `N >= envelope.tests_baseline`（无 baseline 的旧信封按 legacy `>= 1`）；空测试目录现在判红。真实塔首跑：`ran 2, baseline 2`，post-merge **5/5**。

同一张卡还暴露了一个流程冲突：新增第 5 项检查会让 `MERGE.md` 从 `4/4` 变 `5/5`，而 `test_hardening2.py` 写死了 `4/4`；v1 卡的 `allowed_paths` 只列两个文件，**按卡面执行必然要么红、要么越界**。处置不是原地改 spec（spec 冻结），而是重建任务卡：v1 归档为 `tasks/PILOT-025-VOID/` + `pilot/PILOT-025.spec.v1.json`，v2 把第三个文件写进 `allowed_paths`，ledger 留下第二组 `TASK_NEW/SPEC_APPROVED`。判例：**卡面与验收冲突时，先修卡，再改代码；作废要留痕，不能悄悄放宽。**

（副作用：`state-verify` 会把 `PILOT-025-VOID` 报进 `skipped`（`no_lifecycle_events`），这是留痕的可见代价，不是 drift。）

**续篇（PILOT-026）**：塔套件计数也入闸——根套件按 `tests_baseline`、塔套件按 opt-in 的 `tower_tests_baseline` 各设一道。真实塔首跑 6/6：根 `ran 2, baseline 2`、塔 `ran 246, baseline 241`。同一张卡再次出现"卡面前提错"：写死"只改 hardening2 一行"在新检查 opt-in 时不成立（该 fixture 无 baseline，仍是 5/5），执行者用 13 行 fixture opt-in 让 `6/6` 真实成立，reviewer 判 ACCEPT。教训升级为：**卡面冲突要么修卡，要么在验收项内做最小可证明的补齐，并在记录里写明前提错误**——两条都允许，但都不能悄悄改断言。

### 6.12 判例：批授权跑三张卡（RUN-2026-10-22-B）

第一次按"批授权 + 固定卡序 + 硬停"跑：`PILOT-027`（runner/TMP 沙箱）→ `028`（迁移合法性）→ `029`（baseline 必填）。三张卡全部一次复核通过、零 rework、零硬停，耗时约 1.5 小时；owner 只批了一次。批授权机制本身有效：**loop 没有自行选题**，reviewer 每卡都核对"是否仍是章程里的下一步"。

三条可复用判据：

- **预批准物必须在 post-merge 前入库或不进塔根**：027 首次 post-merge 因 `PILOT-028/029.spec.json` 还是 untracked 而判"工作树脏"——这是自伤，不是实现缺陷；把两份已批准 spec 先提交后重试即绿。批运行里"提前把未来卡的材料放进塔根"等于给 clean 检查埋雷。
- **审查者对环境 hack 的价值**：027 的三处偏差（runner 缺失时的窄回退、run 目录写 `.git` 哨兵、Windows `core.longpaths` 注入）都被 reviewer 逐条复现并判 ACCEPT；reviewer 还发现 fixture 只覆盖回退路径、runner 分支未被提交测试覆盖。没有独立复核，这些会被当成"绿了就行"。
- **残余是政策，不是 bug**：`028` 的 `TASK_NEW` 任意来源（重建先例的副作用）、`029` 的手写信封旁路与低值 baseline、`012` 的 `.test-tmp` 不清理——都是已知且记录在案的政策缺口，下一批应优先处理"手写信封 + queue-add 旁路"。

**判例**：批授权把注意力成本从"每卡一次"降到"每批一次"，但前提是**卡序锁定、验收可判定、硬停可执行、owner 可抽样**；任何一条缺失，批授权就退化成"无人看管的连跑"。

### 6.13 判例：把旁路一条条钉死（RUN-2026-10-23-C）

第二批三卡专门堵 RUN-B 复核留下的旁路：`030` 让 `queue-add` 也强制 baseline（堵手写信封入队）、`031` 让 baseline 不得低于 ledger 里已验证计数的最大值（单调锚点）、`032` 把 `TASK_NEW` 从"任意来源"收紧为"仅未完成状态"（完成卡不得静默重置）。三卡一次复核通过、零 rework、零硬停，约 1 小时 25 分钟；最终 32 任务/32 信封、281 tests、post-merge 七检全绿。

可复用判据：

- **旁路要逐个封，别指望一个门**：`envelope-new` 之后还有 `queue-add`，`envelope-new` 里能带假 baseline，`state-verify` 能看见重置但不能阻止它。每加一道门，reviewer 都会找下一道没关的门——这是特性，不是刁难。
- **锚点用已有证据，不造新状态**：`031` 没有引入 `BASELINE.json`，而是从 append-only + 哈希链的 supervision ledger 里取 `POST_MERGE_VERIFIED.tower_tests_count` 的最大值。少一个可被手改的状态文件，多一条可被 `verify-ledger` 保护的事实。
- **同一个错犯两次是流程问题**：RUN-B 与 RUN-C 的首次 post-merge 都因"提前放进塔根的后续 spec 仍未提交"判脏。第一次记了判例，第二次仍复现——说明"预批准物必须先入库"没有变成硬约束。下一批要么在 `run-charter` 里加一步“预批准 spec 先提交”，要么把未跟踪的 spec 视为 post-merge clean 检查的白名单（需权衡）。

**判例**：门禁的演进不是"加更多检查"，而是**沿着攻击面把每一条能绕过的路径变成一条可判定的规则**；当一条残余被写进判例却仍在下一批复现时，说明它需要工具化，而不是再记一次。

---

## 7. 与 K3 塔的能力对照（一页）

| 维度 | K3 / SeeMake 塔 | tower-dsh | 谁更强 |
|---|---|---|---|
| 项目状态 | `CURRENT`（包号禁令）+ Authority State + v37 包 | `CURRENT_STATE.json` + handoff 包 + **`authority_dirty` 检测**（PILOT-011） | K3：多一层窗防呆 |
| 系统事实冻结 | 画像族：DB / 队列 / 存储 / 部署 / 多用户 / 实施 | **无** | K3 |
| 不变量可执行性 | 画像多为散文 + 基线与采集脚本 | 27/27 tool-check 有测试、门是 `exit 2` | **木塔** |
| 趋势治理 | 锚点 + 周测 diff + 熔断 + 重锚 | **无** | K3 |
| 版本控制 | `_k3-ops/` **永不入 git** | 塔在 `Control-Tower-Kit` 仓（199 文件） | **木塔** |
| 独立性 | 四重**同身份**评审 | 独立 subagent reviewer，`reviewer != executor` 硬断言 | **木塔** |
| 决策证据 | owner 向量 + 题包 SHA-256 | 证据 SHA-256 + ledger 哈希链 | 平（木塔链更强，K3 题包公理化更强） |
| 交接 | v37 包 + CURRENT 防呆 | v2.1 五步状态机 + 21 项 check | 木塔流程更严，K3 防呆更实用 |
| 判例 | `治理判例集.md` | 5 条散在 handoff §6 | K3 |

---

## 8. 这张图自己的边界

- **只读快照**：生成期间不写状态、不 merge、不碰生产、不外部调用；唯一写入是本文件。其后按 owner 逐次授权提交了 handoff 状态（`26d2f6f`，见 §6）——那是状态的提交，不是地图的改写。
- **数字口径**：任务/信封数来自 `status`；条款数来自 `spec-coverage`；账本数来自 `verify-ledger`；测试结论来自 2026-10-19 23:3x 的一次复跑（环境异常，已如实记录，不伪装成绿）。
- **会过期的部分**：§5 的测试结论、§6 的漂移清单——两者都应在下一次 `startup` 时重算。
- **刷新触发**：phase 变更 / 新增任务卡 / 门禁代码（`towerctl.py`）变更 / 新 handoff 包 / 接入真实项目 —— 任一发生即重画。
- **不做什么**：不代替 `CURRENT_STATE.json`，不充当授权记录，不作为"完成"证据。地图是投影，不是真相。
