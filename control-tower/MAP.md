# tower-dsh 控制塔地图 / 画像

> 生成者：`ctl-yingxian-qa-001`（接续 controller）· 生成时刻：2026-10-19T23:5x +08:00
> 性质：**只读快照**。不替代 `tower-dsh/primary/CURRENT_STATE.json`，不构成状态。
> 修订：2026-10-20T00:5x —— §6 由"漂移"改为"已闭合"，§1 phase 按实值更正，§8 口径同步。
> 修订：2026-10-20T02:2x —— PILOT-011 落地（authority drift 可观测）；§3/§5/§6/§7 同步，新增 §6.2 排序陷阱。
> 修订：2026-10-22T00:4x —— PILOT-022/023/024/025 落地（状态重放收紧、证据完整性、门禁解码、测试计数门）；§4.2 ∅10/∅11、§5、§6.9–6.11 同步。
> 修订：2026-10-22T15:3x —— PILOT-026 落地（塔套件计数入闸）；∅11、§5、§6.11 同步。
> 修订：2026-10-22T20:5x —— RUN-2026-10-22-B 批跑（027 runner/TMP、028 迁移合法性、029 baseline 必填）；∅10–∅12、§5、§6.12 同步。
> 修订：2026-10-23T03:0x —— RUN-2026-10-23-C 批跑（030 queue-add 门、031 单调锚点、032 完成卡禁止重置）；∅10/∅11、§5、§6.13 同步。
> 修订：2026-10-23T08:0x —— PILOT-033（队列/信封 unbacked 显形 + ledger-backed 合并门）；∅10/∅11、§5、§6.14 同步。
> 修订：2026-10-23T17:1x —— RUN-2026-10-23-D 批跑（034 合并门自验、035 半写修复）；∅11、§5、§6.15 同步。
> 修订：2026-10-23T18:4x —— PILOT-036 落地（信任边界收口：缺失/不可读 ledger 在合并门 fatal、命令级 identity 精确到类型、`ENVELOPE_NEW` 同一条事件绑 task+head）；∅11、§5、新增 §6.16。
> 修订：2026-10-24T19:4x —— PILOT-037 落地（授权态单写者：`state/AUTHORITY.json` ⇄ ledger `AUTHORITY_SET`、merge 身份钉死、primary 链校验、真实塔 backfill）；∅7、∅10/∅11、§5、§7、新增 §6.17。
> 修订：2026-10-25T00:4x —— PILOT-038 落地（授权必需标记：`shared/AUTHORITY_POLICY.json` + `AUTHORITY_REQUIRED`、required 塔禁止退 legacy、ledger append 失败 fail-closed、真实塔 armed）；∅7、∅10/∅11、§5、§7、新增 §6.18。
> 修订：2026-10-25T14:3x —— PILOT-039 落地（policy⇄event 逐字段同构、authority 写跨锁、merge 前置链「缺失=致命」；v1 因 missing-ledger 绕过被复核 FAIL → 作废重建 v2）；∅7、∅10/∅11、§5、§7、新增 §6.19。
> 修订：2026-10-26T13:5x —— PILOT-040 落地（空账本守卫：configured/required 塔的 0 字节 supervision ledger 不再掩护 legacy merge；authority-require 回显真实 decision；卡面矛盾按 §6.11 播种夹具）；∅7、∅10/∅11、§5、§7、新增 §6.20。
> 修订：2026-10-26T20:0x —— PILOT-041 落地（deliver 范围门：diff ⊆ allowed_paths、`--no-renames`、linked-worktree 身份；dispatch 记录 kind/model/parent；bootstrap 例外与 completion-list 复发问题）；∅10/∅11、§5、§7、新增 §6.21。
> 修订：2026-10-27T05:4x —— PILOT-042 落地（授权完成清单 completion list：record+ledger、deliver 并集、三种 drift；dispatch base_sha 锚定 deliver 基线；记录层成为新的信任边界）；∅10/∅11、§5、§7、新增 §6.22。
> 修订：2026-10-28T02:0x —— PILOT-044 落地（shape-check ratchet：全部 def 含方法/嵌套、塔根基线、不可篡改/删除、parse 干净失败；REVIEW Structure 五问；043 暂缓 ready）；∅10/∅11、§5、§7、新增 §6.23。
> 修订：2026-10-28T18:3x —— PILOT-045 落地（命令层 v1：STRATEGY + campaigns + campaign-check + brief；VOID 归档修复；§6.24）；∅10/∅11、§5、§7、新增 §6.24。
> 修订：2026-10-29T13:0x —— PILOT-046 落地（状态历史：snapshot/index/rollup/archive；E7/R3–R5/W3 硬化；§6.25）。
> 修订：2026-10-29T13:1x —— PILOT-047 落地（双视图位置图：roadmap/current + where --json|--md + 注入；§6.26）。
> 修订：2026-10-29T15:5x —— PILOT-048 落地（架构脊柱：ARCHITECTURE + ADR-0001 + GATES/INVARIANTS + EVENT_CATALOG + arch-check/arch-graph；§6.27）。
> 修订：2026-10-30T01:0x —— PILOT-049 落地（objective 硬门：spec@2 + task-new 零写入 + spec-lint @2 + ADR-0002；§6.28）。
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
| ∅7 | **授权态单写者** | `SeeMake-Control-Tower-Authority-State.md`：Active Tower / Single Writer / 保留闸 / repo+queue 锚点 | **已实现并收尾**（PILOT-037/038/039/040）：`state/AUTHORITY.json` 与 primary ledger 最后一条 `AUTHORITY_SET` 互为锚（9 字段 + `tower_id` + 严格类型），`merge --supervisor` 必须等于登记 `merge_authority`；038 加必需标记（`AUTHORITY_POLICY` + `AUTHORITY_REQUIRED` 双侧互锚）；039 加 policy⇄event 逐字段同构、`authority-set/require` 跨锁、`merge` 前置链（缺失/不可读/坏行一律致命）；040 再补**空账本守卫**：configured/required 塔上 supervision ledger 为 0 事件且有 envelopes/queue/merge-ledger 工件时拒绝 merge（legacy 塔保持旧行为），并修正 `authority-require` 的 already/repaired 回显（输出真实 decision + `requested_decision`）。真实塔 armed：`revision=2`、pin `sup-phase2-pilot`、`requirement=required` | 仍窄：守卫按“可解析 JSON 对象”计事件，截成 `{"seq": 1}`（11 字节）可绕过（需写 ledger，本质仍是 036 无密钥链残余）；legacy 塔清空 primary ledger 仍按 036 放行；`--by` 是字符串非认证；policy+event 双写并重算整链是 TOFU 残余（policy 的 git 追踪是外部锚） |
| ∅8 | **判例集** | `rules-ref/治理判例集.md`：一次裁决 → 以后可引用的规则 | 5 条散在 `HANDOFF.md §6` | ledger 增加 `PRECEDENT` 事件 + `towerctl precedent --list` |
| ∅9 | **包号防呆** | `_k3-ops/CURRENT`：包号比你所持新即停手 | `handoff-check` 只在 claim 时跑一次 §0 漂移 | 根目录 `CURRENT` + `startup` 强制比对 |
| ∅10 | **状态重放** | （K3 也没有） | **已实现并持续收紧**（PILOT-021/022/023/028/032/033）：ledger 折叠状态并与 record/board/queue/envelope 比对；坏文件算 drift，合法跳过显式 `skipped`，board 取重放值；证据逐条校验 SHA-256/字节数，spec 校验冻结哈希；状态迁移按真实历史表校验；`TASK_NEW` 只允许未完成状态重建；无事件的信封/队列条目记 `envelope_unbacked`/`queue_unbacked`，不再隐形。真实塔 49 任务/48 信封、420 条证据、drift 0（skipped 4 个 VOID 归档） | 仍窄：`ready→TASK_NEW` 仍合法；未来新增生命周期事件若漏表会默认放行；关闭卡无正式 reopen 流程；TOCTOU/hardlink 不在范围 |
| ∅11 | **测试计数门** | （K3 也没有） | **已实现并合围**（PILOT-025/026/029/030/031/033/034/035/036）：`post-merge` 解析 `Ran N tests`；根/塔套件按 baseline 设门；`envelope-new`/`queue-add` 都强制 baseline；baseline 不得低于 ledger 已验证最大值；merge-check/merge 对新式信封自验 `ledger chain intact` + `ENVELOPE_NEW` + `QUEUE_ADD` + 身份绑定；`queue-add` 可修复半写条目；036 让链检查对缺失/不可读 **fatal**（缺失=错、不可读=干净 exit 2，不 traceback）、命令级 identity 精确到类型、`ENVELOPE_NEW` 同一条事件绑 `envelope+task+head`。真实塔：根 `2/2`、塔 `552/536`、anchor `536`，7/7 | 仍窄：legacy（无 baseline）信封仍可降级绕过新检查；哈希链无密钥，可被“追加一行正确 prev_hash/hash”伪造（tamper-evident 非防篡改）；`envelope_head_sha` 两边同时缺失时 `None==None` 可过绑定检查（git 检查仍拦 merge）；任意坏行会阻塞全部新式合并；链校验 O(ledger)；验证与读取之间的 TOCTOU 未吞 OSError（有意“宁可红”） |
| ∅12 | **证据可复现** | — | **已实现切片**（PILOT-027）：`tools/run_tests.py` 把 `TMP/TEMP/TMPDIR` 指向仓内 `.test-tmp/run-*`，post-merge 与根门禁都走 runner；`REPRODUCE.md` 给出干净环境复跑清单；全套件 287 绿 | 仍窄：`.test-tmp` 不自动清理；运行器依赖 Windows 下的 core.longpaths 注入；直接 discovery 不走沙箱 |

---

## 5. 已证明 / 仅声明 / 未做（用数字说话）

| 能力 | 判定 | 证据 |
|---|---|---|
| spec 冻结（改 spec 即失效） | `[证]` | `spec_gate_errors` 每次实时复算 SHA-256（`towerctl.py:442-470`） |
| `dispatch` 前置 spec 门 | `[证]` | `cmd_dispatch:932-934`；PILOT-002 回归测试 |
| accept / close 强证据 | `[证]` | `cmd_accept:1022`、`cmd_close:1046` 内联 `check_evidence` |
| reviewer 非空且 ≠ executor | `[证]` | `cmd_checkback:992-996` |
| merge 分支断言 | `[证]` | `cmd_merge:1919-1936`，不符即 `CORRECTION_REQUIRED` |
| merge 身份由登记状态裁决 | `[证]` | PILOT-037/038/039：`authority-check` 13 项（9 字段绑定 + `tower_id` + 严格类型 + primary 链 + requirement）失败即 `exit 2`；`merge --supervisor` 必须等于 `merge_authority`；required 塔缺失/无背书报 `required_unconfigured`；039 起 policy⇄event 逐字段同构、authority 写跨锁；旧码 rogue supervisor / policy 篡改实测 MERGED，新码 exit 2 且队列保持 WAITING |
| deliver 范围门（P1-1） | `[证]` | PILOT-041/042：`deliver` 在复制证据前校验 `git diff --name-only --no-renames <base>..HEAD ⊆ 映射后的 allowed_paths ∪ record.completions`；越界/已跟踪脏 → `exit 2` 且零写入；worktree 必须是本仓库 linked worktree（toplevel==worktree、gitdir 在仓内）；非 git 夹具输出 `skipped`；dispatch 记录 `kind/model/parent/base_sha`。042 的 completion 由 owner 签名（`completion-add --by mac`，record + `COMPLETION_ADDED`，三种 drift 可审计），deliver 输出 `scope_completions`；base_sha 非 HEAD 祖先即 exit 2。旧码越界 0 / rename 0 / 改写 main ref 后 0，新码均 exit 2 |
| shape-check（形状预算） | `[证]` | PILOT-044：零依赖 AST ratchet，扫描全部 `def`（module-level + class 方法 + 嵌套，限定名）；新函数 >80 行/12 分支、新文件 >600 行、新 ≥15 行重复块、新未使用 import → `exit 2`；基线 `state/SHAPE-BASELINE.json`（1,114 条，可字节复现）冻结 16 个既有长函数；deliver 固定读塔根基线，worktree 改/删基线 → `exit 2`；parse error 干净 `exit 2`。旧码新长函数 deliver 0，新码 2；main `shape-check` 31 文件/1,192 函数 exit 0 | 
| 命令层（战略/战役/简报） | `[证]` | PILOT-045：`command/STRATEGY.md` + `command/campaigns/*.md` 为 front-matter 可机读的地图；`campaign-check` 校验 E1–E6（缺失/goal 不存在/过期/WIP 超限/卡不存在/id 重复）与 W1/W2（孤儿卡/临近预算），错误 exit 2、`--strict` 升级；`brief` 只读生成 23 行七节（战略/战役/WIP/阻塞/下一步/待决/约束）。修掉 VOID 归档被当活卡的 bug（`read_task_records` 只收规范目录且 `record.id == 目录名`）；真实塔根 exit 0、wip 0/1、W1 44（048 回填前 `--strict` 必红）。旧码无两命令 |
| 状态历史（追加/重算） | `[证]` | PILOT-046：`status-snapshot` 同日多次**只追加**；`status-index` 生成 `status/index.json`（days.entries + sha256），删掉可重算、两次字节相同；`status-rollup --week` 字节稳定；`status-archive` 只压缩不删原件。复核在 868 个非 status 文件上零改动；E7（board 形状）、R3（空 task_forces）、R4（单引号）、R5（budget 中英文/周数）、W3（spec-only）全部硬化。残余：写失败仍是 Traceback（R-1）、损坏快照被静默跳过（R-2） |
| 位置图（双视图） | `[证]` | PILOT-047：campaign `roadmap/current` + `where --json`（schema `tower/position@1`、枚举 done/active/blocked/planned/skipped、顺序=roadmap、无时间戳）与人视图（7 行，位置条 + 位置 x/y + 下一站 + 为什么/交付/风险/建议）；E8（roadmap 缺失/空/重复/current 不在）与 E9（无 active campaign）干净 exit 2；注入 checkback/close/post-merge/status-snapshot/brief。index 语义=done 计数（spec 文字“第一个非 done”属笔误，需 errata）；campaign-check 对缺 roadmap 保持 legacy 绿、where 严格 E8 |
| 架构脊柱（可证伪） | `[证]` | PILOT-048：`ARCHITECTURE.md` 六节 + `arch/GATES.json`（16 门，command/test 全存在）+ `arch/INVARIANTS.json`（C-01..C-16 → 真实 probe）+ `EVENT_CATALOG.json`（29 事件 ↔ 代码字面 type 双向）+ `adr/ADR-0001`（DESIGN 归档，正文逐字节不变）；`arch-check` 六项对账、`arch-graph` 35 nodes/21 edges 字节稳定；`related_files` 盘符/`..`/出塔根拒绝、duplicate stem 拒绝；旧码无两命令。首轮/二轮 FAIL（文档不实、CI 归属错、证据 UTF-16）→ 修复后 PASS；DESIGN 路径笔误用 completion `D-PILOT-048` 兜底 |
| objective 硬门 | `[证]` | PILOT-049：`tower/spec@2` + `objective.problem/outcome/approach/non_goals_and_done`；`task-new` 对所有新 spec 在写 record/TASK/ledger **之前**校验，缺项/非字符串/空串/<8/整值 `__FILL__`/整值 `<...>` → exit 2 零写入（64 夹具 + 已有卡不覆盖）；`spec-lint` 只扫顶层 `pilot/*.spec.json`，@2 强制、@1 冻结跳过、6/6 文档校验不变；`GATE-SPEC-OBJECTIVE`（gates 16）+ `ADR-0002`；旧码接受无 objective 并建卡、不扫 pilot，新码均拒。残余：`TODO __FILL__`、`补充 <待填写>` 可过；长度按 code point；模板测试用子串而门口用整值 |
| merge 前置链（缺失=致命） | `[证]` | PILOT-039/040：`merge` 在 authority 之后、读信封/队列/git 之前对 primary+supervision **无条件** `verify_ledger_file`；缺失/不可读/坏行一律 `exit 2`（`merge precondition: <name> ledger chain missing/broken`），队列 WAITING、无 MERGE_START、ledger 不重建；040 再加空账本守卫：configured/required 塔 supervision 0 事件 + 有 envelopes/queue/merge-ledger 工件 → `ledger history present` 失败（legacy 塔保持旧行为）。旧码删 supervision+legacy 信封 MERGED 并重建 ledger、0 字节截断也 MERGED，新码均拒绝 |
| post-merge 七检 | `[证]` | 测试 / 根套件计数 / 塔套件计数 / baseline 不回退 / 实现是祖先 / 信封在 base / 工作树干净（RUN-C 后；count 检查对旧信封 opt-in） |
| 路径越界防护 | `[证]` | `ensure_within` 覆盖 evidence / worktree / package / envelope / repository |
| ledger 哈希链 | `[证]` | `verify-ledger` → primary 448 事件、supervision 250，0 error；legacy 未哈希 53 / 26（按 INV-05 只计不判）；缺失/不可读现为验证失败（PILOT-036/039）；`AUTHORITY_SET`/`AUTHORITY_REQUIRED`/`COMPLETION_ADDED` 也在链上（PILOT-037/038/042） |
| 条款→测试绑定 | `[证]` | `spec-coverage`：6 份规范 / 56 条款 / tool-check 27 / covered **27** / gaps 0 |
| 测试全绿 | `[证]`（有条件） | `Ran 552 tests / OK（skipped=1）`（本地 2026-10-30，PILOT-049 后）；GitHub Actions 在 PR #18–#33 上绿，v7 后零注解。**建议跑法**：`python -B tools/run_tests.py`（TMP 在仓内，避受限沙箱 ACL）；直接 discovery 仍可用，但受限模式下 `%TEMP%` 仍会让 134/134 在 0.05 s 内全 ERROR |
| 29 条条款靠人 | `[声]` | 12 `review-check` + 17 `owner-gate`（`spec-coverage.manual` / `.owner`） |
| "每次迭代全局正确" | `[无]` | 无对象层不变量、无趋势锚点、无状态重放 |
| 49 个任务 / 48 个信封 | `[证]` | 全部 `closed` + `POST_MERGE_VERIFIED`（011 `6a849b9`；012 `bc4be88`；013 `10bf606`；014 `4ef0695`；015 `ae4eb4f`；016 PR #1 `29d8ec6`；017 PR #2 `6796d1d`；018 PR #3 `46e946c`；019 PR #4 `474cfb3`；020 PR #5 `63aa31d`；021 PR #6 `10fae79`；022 PR #7 `6a920a5`；023 PR #8 `a88388b`；024 PR #9 `c4fb58f`；025 PR #10 `f265847`；026 PR #11 `e73f1f5`；027 PR #12 `223b10b`；028 PR #13 `188f122`；029 PR #14 `ef72400`；030 PR #15 `aa88f76`；031 PR #16 `c9a7da6`；032 PR #17 `da5a25c`；033 PR #18 `eb8f03b`；034 PR #19 `7f122b8`（7/7，塔 `291/287`）；035 PR #20 `a7e429d`（7/7，塔 `293/291`，anchor `291>=291`）；036 PR #21 `d8ef20f`（7/7，塔 `305/293`，anchor `293`）；037 PR #22 `895141c`（7/7，塔 `328/305`，anchor `305`）；038 PR #23 `7cb9e0b`（7/7，塔 `341/328`，anchor `328`）；039 PR #24 `c4efe6d`（7/7，塔 `363/341`，anchor `341`；v1 FAIL → VOID 后 v2）；040 PR #25 `2bd870f`（7/7，塔 `371/363`，anchor `363`；0 字节截断守卫 + §6.11 夹具播种）；041 PR #26 `cc7c55a`（7/7，塔 `387/371`，anchor `371`；v1 映射措辞错误 VOID 后 v2，首轮 FAIL 后返工 `fa84fbe`；bootstrap 交付）；042 PR #27 `01213ce`（7/7，塔 `419/387`，anchor `387`；completion list + base_sha）；044 PR #28 `129dd4e`（7/7，塔 `441/419`，anchor `419`；shape-check ratchet + REVIEW 五问；v1 文字重建、首轮 FAIL 后返工 `5cc933e`；门引入 bootstrap；043 暂缓 ready 未派）；045 PR #29 `99b61a1`（7/7，塔 `467/441`，anchor `441`；命令层 v1 + brief VOID 修复；R1 真实根 campaign-check/brief 已闭合）；046 PR #30 `63d7b47`（7/7，塔 `487/467`，anchor `467`；状态历史 + E7/R3–R5/W3）；047 PR #31 `b4c7859`（7/7，塔 `518/487`，anchor `487`；双视图位置图；首轮 merge GitHub GraphQL EOF → MERGE_BLOCKED → 重试成功）；048 PR #32 `aaa4dfe`（7/7，塔 `536/518`，anchor `518`；架构脊柱 + ADR-0001 + arch-check；首轮/二轮 FAIL 后修 3 处文档事实 + CI 归属 + 证据编码；DESIGN 路径笔误用 completion）；049 PR #33 `7d8ca4a`（7/7，塔 `552/536`，anchor `536`；spec@2 + objective 零写入门 + ADR-0002；test_arch 计数字面量用 completion），其余 post-merge 均 4/4） |

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

### 6.14 判例：让手写状态"显形"（PILOT-033）

`PILOT-033` 收官 ∅11：`state-verify` 不再把无事件的信封/队列条目当 `skipped`，而是记 `envelope_unbacked` / `queue_unbacked`；`merge-check`/`merge` 对新式信封新增 `queue entry backed by ledger`，要求 `QUEUE_ADD` 事件存在。真实塔 33/33、287 tests、drift 0。

独立复核给出的四条残余值得直接当下一批的输入：

1. **R1 哈希链不在合并门前**：手写一行 `QUEUE_ADD` 可通过 `merge-check`（`verify-ledger` 能抓，但合并门不跑它）。合并门要么跑一次轻量链校验，要么拒绝非工具写入的队列条目。
2. **R2 只认 `QUEUE_ADD`，不认 `ENVELOPE_NEW`**：手写信封 + 真 `queue-add` 会以 `illegal_transition` 被 state-verify 抓，但 merge 不看 state-verify。
3. **R3 身份取自文件内容**：`envelope_checks` 用 `env["envelope_id"]` 而不是请求的 id；复制一个已背书信封改成新 id 即可通过。修法是 `env["envelope_id"] == args.envelope`。
4. **R4 半写窗口**：`envelope-new`/`queue-add` 先写文件/队列再追加事件，中途失败会留下持久 drift 且不可重试；要么先事件后写文件，要么把半写识别成可恢复状态。

**判例**：让隐藏状态"显形"只是第一步；**一个检测门不进入合并路径，就只是事后审计**。下一批应把 R1–R3 并入 `merge-check`，把 R4 变成可恢复事务，而不是再记一条残余。

### 6.15 判例：把审计门搬进合并路径（RUN-2026-10-23-D）

`PILOT-034` 把 6.14 的 R1–R3 搬进合并门：新式信封（带两个 baseline）的 `merge-check`/`merge` 现在自验 `ledger chain intact`（primary + supervision）、`envelope_new recorded`、身份绑定（请求 id ≠ 文件内容 id 即命令级失败）。`PILOT-035` 把 R4 变成自愈：`queue-add` 发现“队列条目在、`QUEUE_ADD` 缺失”时补一条事件并返回 `repaired: true`，不重写队列。两卡均 7/7、零 rework，最终 35/35、293 tests。

可复用判据：

- **检测与拦截是两个工程**：033 让手写状态显形，034 才让它无法进合并；`state-verify` 是审计器，`merge-check` 是门。两者都要，但不能互相替代。
- **修复要放在写者手里**：半写窗口由 `queue-add` 自己修（补事件、不重写队列），比让 owner 手改状态安全；修复前仍要过 baseline 门，不能借修复洗白坏信封。
- **链是“可发现篡改”，不是“防篡改”**：SHA-256 无密钥，能重算；真正的边界是“只有 towerctl 写 ledger + 锁串行化 + verify-ledger 可审计”。034 的残余（legacy 降级、重算伪造、缺失/不可读 ledger）应作为下一批输入，而不是当成已解决。

**判例**：门禁成熟的标志不是“检查更多”，而是**审计器与门分工明确、修复由写者负责、并清楚写下哪些残余仍靠信任而非机制**。

### 6.16 判例：信任边界的三个“以为链成立”（PILOT-036）

`PILOT-036` 收掉 034/035 留下的三个口：**缺失/不可读 ledger 不再算链 ok**（缺失=错、不可读=干净 `exit 2` 单 JSON、已存在空文件仍 intact）、**命令级 envelope identity 精确到类型**（不再 `str(... or "")`，JSON 的 `42` 不能冒充请求的 `"42"`）、**`ENVELOPE_NEW` 同一条事件绑 `envelope + task + head`**（只绑 id 的事件不继承历史）。实测：`Ran 305 / OK`、10/10 证据哈希、PR #21 `d8ef20f`、post-merge 7/7（塔 `305/293`）；独立 reviewer 用自建 `%TEMP%` 塔复现旧码对照 4/4：缺账本旧 `verify-ledger` exit 0、目录账本旧码 traceback、整数 id 旧码命令级放行、错 head 的旧 `merge` **真的 MERGED**——新码四项全拒。

可复用判据：

- **“文件不在”不是“链完整”**：空文件与缺失是两件事——存在但空=合法空链，不存在/不可读=验证失败。凡“读一个东西再判断它干净”的审计器，都必须先把缺/空/坏三种输入分开裁决；否则消失会被读成清白（036 之前，删掉整个 ledger 反而让链检查 `ok`）。
- **归一化比较就是隐式放宽类型**：`str(env.get("envelope_id") or "")` 让 `42` 与 `"42"` 等价。identity 这类“谁是谁”的判断必须精确到类型；且失败要落在**命令级字符串 `errors`**，不能混进 check 字典列表——门与审计的边界一糊，`merge` 与 `merge-check` 的失败形状就会分叉。
- **绑定要绑到不可复制的字段**：只绑 id 的 `ENVELOPE_NEW` 能被“名字对、内容不对”的事件满足；绑 `task + head` 之后，同一 id 的复用不再继承历史，且 detail 必须点名哪一项不符（运维不必猜）。
- **消歧不是削弱，但前提要写死**：`supervision_available` 只在 supervision ledger 缺失/不可读时跳过两个依赖它的 lifecycle 检查（否则会额外误报 `ENVELOPE_NEW missing`），前提是链检查 fatal。**允许跳过的前提，是“被跳过项依赖的失败已经致命”**——这个前提必须成为不变量测试，否则未来把链降级成 warning 时，检查会静默消失。
- **残余要按“攻击成本”写，不按“已关门”写**：无密钥链仍可“追加一行正确 prev_hash/hash”伪造（比“重算整链”更弱的前提），036 只是把成本从“手写信封”抬到“手写信封+写一行账”；`envelope_head_sha` 两边同时缺失时 `None==None` 可过绑定检查（git 检查仍拦 merge，属“靠兜底”，应改显式失败）；legacy（无 baseline）路径按设计不查链/绑定；验证与读取之间 ledger 变不可读仍可能 traceback（`ledger_events_in_seq_order` 有意不吞 OSError：宁可红，不可静默当空）。

**判例**：门禁的可信度不取决于检查条数，而取决于**每条检查对“输入不存在”和“输入不可读”都有明确裁决**；把这两种输入留给异常处理，等于把门交给 traceback。

### 6.17 判例：把“谁有权 merge”变成可重放状态（PILOT-037）

`PILOT-037` 收掉 ∅7：`state/AUTHORITY.json` 与 primary ledger 最后一条 `AUTHORITY_SET` 互为锚——文件必须与该事件**9 个字段逐字段一致**（`owner/primary_id/supervision_id/merge_authority/revision/set_by/decision/set_at/note`，缺失与空串分开判定）、`tower_id` 必须与 primary state 一致、类型严格（`revision` 必须 `type is int`，bool/float 全拒）；`authority-check` 在事件存在时**额外校验 primary 链**；`merge` 的 `--supervisor` 必须等于登记的 `merge_authority`，缺失/无背书/不一致一律 `exit 2`。实测：328 tests、PR #22 `895141c`、post-merge 7/7（塔 `328/305`）、真实塔 backfill 后 `revision=1`、pin `sup-phase2-pilot`、`authority-check` 12/12 configured；旧码 `merge --supervisor rogue` **实测 MERGED**，新码 exit 2 且队列保持 `WAITING`、无 `MERGE_START`。

这张卡最值得记的是**复核真的判了 FAIL**：第一轮独立复核抓出“只比 5 字段（改 `decision` 不报）”“`revision: true` 被 Python 相等放过”“目录挡路 traceback”三个契约缺陷，返工一个 commit、补 5 个测试后才 PASS。这说明“实现 + 自测全绿”仍然会漏掉**类型与审计字段**这类边界，独立复核不是流程装饰。

可复用判据：

- **参数不是身份**：`--role` / `--supervisor` 是调用者自述。身份必须来自“登记状态 + 账本事件”双侧一致；凡是“传个字符串就能行使权力”的门，都不是门（旧码唯一约束是 `supervisor != primary.id`）。
- **状态文件必须被账本背书**：文件可改、账本有链。只比“文件存在且 schema 对”等于没验；必须和最后一条事件逐字段比对，否则“改 decision 不改账本”就能把授权痕迹抹掉。
- **审计字段也是契约字段**：`set_by/decision/set_at/note` 不是注释；漏绑它们 = 允许“谁批的、为什么批”被静默改写，而这正是事后追责要用的字段。
- **兼容口必须有截止日**：legacy（无文件无事件）保留旧行为是必要的迁移窗口，但它等价于“删掉配置就回到任意 supervisor”。backfill 必须紧跟合并；长期要 `authority_required` 标记或截止日关闭 legacy merge，否则这就是后门。
- **门要连链一起验**：`authority-check` 只在事件存在时跑链校验。若不跑，“伪造一条 hash 正确的 `AUTHORITY_SET` + legacy 信封”就能 rogue merge（旧码实测 MERGED，新码被 `primary ledger chain broken` 拦下）。
- **残余按删什么写**：删文件 + 截掉 ledger 尾部唯一 `AUTHORITY_SET` → `verify-ledger` 0、`state-verify` 0、`authority-check` legacy，可退回任意 supervisor。这需要本地写 ledger/state 的攻击者，属 036 已记录的 `tamper-evident` 威胁模型；防删/防截断要塔级持久标记，不是再加一条检查。

**判例**：身份不是参数，是可重放的状态；状态不是文件，是被账本背书的那一行。

### 6.18 判例：让“必须配置”不能靠删文件回退（PILOT-038）

`PILOT-037` 的假 legacy 是：删 `state/AUTHORITY.json` + 截掉 primary 尾部唯一 `AUTHORITY_SET`（前缀仍是合法链）→ `verify-ledger` 0、`state-verify` 0、`authority-check` legacy、`merge --supervisor rogue` MERGED。038 加**双侧必需标记**：`shared/AUTHORITY_POLICY.json`（git 跟踪）+ primary ledger 更早处的 `AUTHORITY_REQUIRED`，`required = 策略 true 或事件在`；required 塔上“文件与事件都缺”不再是 legacy，而是 `required_unconfigured`（`exit 2`）。同时把 `authority-set` 的 ledger append 失败（`OSError`/`LedgerLockTimeout`）改成单 JSON `exit 2`（037 是 traceback exit 1）。实测：341 tests、PR #23 `7cb9e0b`、post-merge 7/7（塔 `341/328`）、真实塔 `authority-require` + `authority-set` revision 2 后 `configured + required`；旧码同夹具 `merge --supervisor rogue` **MERGED**，新码 exit 2、队列 `WAITING`、无 `MERGE_START`。

可复用判据：

- **“从未有过”与“被删掉了”是两种事实**：只验“现在有没有”的审计器，会把删除读成清白。必须有独立于被保护物的“曾经要求过”记录，才能把缺失命名为故障而不是默认。
- **标记要冗余，且早于被保护物**：`AUTHORITY_REQUIRED` 写在 `AUTHORITY_SET` 之前；截尾只能截掉 SET，截不到 REQUIRE，除非截得更深（同时丢掉大量审计行）。冗余不是浪费，是让“一次删除”不够用。
- **失败要落在“不可通过”，不是“好看”**：`required_unconfigured` 是第三种状态，不是 `configured` + warning；append 失败宁可留 unbacked（merge 拒绝），也不自动重试掩盖。状态机的诚实比错误信息的美观重要。
- **兼容口的代价要写死**：非 required 旧塔仍是 legacy——为了不砸既有测试与旧仓；真实塔 armed 之后，这个口只对“从未 require 的塔”开放。迁移必须紧跟合并（038 在信封前完成迁移，post-merge 用新码验证）。
- **旧码对照是唯一能证明“门更严”的证据**：旧码 required 夹具直接 MERGED；新码 exit 2。没有旧码对照，只能证明“新码有检查”，不能证明“新码拦住了旧码放过的东西”。

**判例**：控制塔必须能分别命名“从未有过”和“被删掉了”；否则删除本身就是一次合法的降级。

### 6.19 判例：门要验“文件的缺席”，不只是“文件的内容”（PILOT-039）

`PILOT-039` 收三件：**policy⇄event 逐字段同构**（`tower_id/set_by/decision/set_at` 被改即 `authority_policy_mismatch`）、**authority 写跨锁**（`state/.authority.lock`，锁序 authority→ledger，并发 revision 严格递增）、**merge 前置链**（primary+supervision 无条件 `verify_ledger_file`，缺失/不可读/坏行一律致命）。v1 已实现同构与跨锁，但前置链对缺失文件 `continue`：删 `ledger/supervision.jsonl` 后 legacy 信封仍 MERGED、ledger 被重建、事后 `verify-ledger` 全绿——独立复核 **FAIL**。按 spec 冻结规则作废重建 v2（`tasks/PILOT-039-VOID` + `pilot/PILOT-039.spec.v1.json`），扩 allowed_paths 并明确 missing=fatal；返工中又发现 `test_merge_pr_mode.py` 缺 `primary.jsonl`，按 §6.11 只加 1 行 fixture（numstat `1 0`，commit body 写明前提错误）。实测：363 tests、PR #24 `c4efe6d`、post-merge 7/7（塔 `363/341`）；旧码「删 supervision+legacy」MERGED 且重建 ledger，新码 exit 2、队列 WAITING、ledger 不重建。

可复用判据：

- **“缺失”是内容检查之外的独立维度**：`verify_ledger_file` 早就把 missing 当 error，但调用方一句 `if not path.exists(): continue` 把语义吞了。**门只要绕过验证函数，就等于没有验证**——036 修的是验证函数，039 修的是调用方；同一个缺口会在两层各出现一次。
- **空文件 ≠ 不存在**：0 字节是合法空链（036 语义），删文件不是；两者不能互相掩护。审计器必须能区分“从未有记录”和“记录被删”，否则删除就是合法降级（038 的续集）。
- **检测与拦截是两个工程（6.15 的续集）**：`merge-check` 对新式信封的链检查，不能替代 `merge` 写操作前的无条件链校验；审计器覆盖的路径 ≠ 门覆盖的路径。把“检查在审计器里”当成“门已经拦了”，是这次 FAIL 的直接原因。
- **并发是写者语义的一部分**：文件写与事件追加不在同一临界区，revision 必重复；锁序固定（authority→ledger）比“随便加把锁”更重要，否则死锁比竞态更难查。
- **允许 FAIL 两次的流程才是真流程**：v1 FAIL → VOID → v2 返工 → PASS，中间没有原地改 spec、没有把 FAIL 记成“观察项”。复核的价值不在“通过”，在“敢不通过”。
- **最小补齐要有编号**：`test_merge_pr_mode.py` 的 1 行 fixture 按 §6.11 记录（numstat `1 0`、commit body 写明“spec v2 allowed_paths 未含该文件”），复核据此判可接受。偏离可以存在，但必须唯一、最小、可核。

**判例**：验证函数正确，不等于调用它的门正确；门必须对“文件不在”有自己的裁决。

### 6.20 判例：计数口径就是语义（PILOT-040）

`PILOT-040` 收 039 的最后一层：**0 字节截断**。039 让缺失致命，但把 `supervision.jsonl` 截成空文件后，前置链仍判“合法空链”。040 加 `ledger_empty_guard`：**configured/required** 塔上，supervision ledger 0 事件且有 envelopes / 队列 / merge-ledger 工件 → `merge` 与 `merge-check` 都 `exit 2`（失败项 `ledger history present`），队列 WAITING、无 MERGE_START、ledger 不重建；legacy 塔保持旧行为（兼容边界由测试 pin 住）；fresh 塔（无工件）不触发。同一张卡还修了 `authority-require` 的 already/repaired 回显：输出真实 `decision`，请求值单列 `requested_decision`。实测：371 tests、PR #25 `2bd870f`、post-merge 7/7（塔 `371/363`）；旧码同夹具 MERGED 并重建 ledger，新码 exit 2。

这张卡还暴露了一次**卡面自相矛盾**：040 的攻击夹具与 038/039「configured 塔应通过 merge-check」的夹具字节等同——旧测试手写 envelope+队列却绕过 `queue-add`，留下 0 事件 supervision ledger；040 的守卫会把它们全部判红。处置不是窄化守卫，而是按 §6.11 在三个测试文件各播种 1–2 行 `QUEUE_ADD`（numstat 8/0、11/0、10/0，零删除、零断言改动），并把“spec allowed_paths 未含这两个文件”写进 commit body。

可复用判据：

- **“0 事件”是可以被一行合法 JSON 重开的盾**：守卫按“可解析 JSON 对象”计事件，把 ledger 写成 `{"seq": 1}`（11 字节）就能让 0 字节守卫失效（039 仍判链合法，merge 成功）。**你数什么，就等于你承认什么**；计数口径必须等于语义（应限定“含非空 `type` + dict `payload`”或做 per-envelope 背书）。
- **空文件 / 缺失 / 空+工件是三种输入**：036 定“空=合法空链”，039 定“缺失=错”，040 定“空+工件=不一致”。审计器（state-verify 的 `unbacked`）早就看见第三种，门只是补上**同一谓词**——审计器与门共用一个判据，才不会分叉。
- **兼容边界要能一句话说清**：守卫只对 configured/required 生效、legacy 塔保持旧行为——这句话必须写进卡面并在测试里 pin 住，否则下一个人不知道边界在哪。
- **卡面矛盾要早发现、按 §6.11 处理**：新门与旧测试共用同一场景时，修夹具（只加事件、不改断言）比窄化门更诚实；前提错误必须写进 commit body 与报告，让复核能判。
- **回显也是契约**：`already=true` 却回显请求的 `--decision`，是输出撒谎；修法是把持久化值当唯一事实，请求值单列。
- **门比审计严时要说明**：仅 merge-ledger 工件时守卫失败而 state-verify ok；这种“门严于审计”必须显式记录，否则运维会以为工具自相矛盾。

**判例**：你统计什么，就等于你承认什么；门禁的语义藏在它的计数口径里。

### 6.21 判例：范围门要防“改名”，也要防“门拦自己”（PILOT-041）

`PILOT-041` 把 `allowed_paths` 从“只存不验”变成门：`deliver` 在复制证据前校验 `git diff --name-only --no-renames <merge-base>..HEAD ⊆ 映射后的 allowed_paths`，越界或已跟踪脏即 `exit 2` 且零写入；worktree 必须通过 linked-worktree 身份检查（toplevel == worktree、gitdir 属于本仓）；`dispatch` 记录 `kind/model/parent/at`。首轮独立复核 **FAIL**：用默认 rename 检测时，`git mv 外部 tracked 文件 → allowed 路径` 只列出新路径，门放行；第二轮修 `--no-renames` 并加 git-dir 身份检查后才 PASS。实测：387 tests、PR #26 `cc7c55a`、post-merge 7/7（塔 `387/371`）；旧码越界与 rename 两种夹具都 exit 0，新码都 exit 2。

这张卡还暴露了两个结构性问题：**门会拦自己**（本卡分支 3 文件 vs spec allowed_paths 2 文件，新门无法验证“引入它的 commit”，交付回退到 pre-gate 工具，作为一次性 bootstrap 记录）；**§6.11 复发**（039/040/041 三连都出现“卡面 allowed_paths 与授权补齐不一致”）。

可复用判据：

- **“移动”在 git 里是删除+新增**：`git diff --name-only` 默认开启 rename 检测，R 条目只输出新路径——`git mv 外部 → allowed` 就伪装成“只新增一个 allowed 文件”。门必须用 `--no-renames`（或 `--name-status` 检查 R 两侧）。**diff 的名字集合不等于变更的语义**。
- **路径归属要验身份，不只看存在**：只要求 `rev-parse --show-toplevel` 成功，嵌套 checkout 或把 `.git` 指向别的仓库都能让 diff 为空。必须比较 toplevel == worktree，并确认 gitdir 属于本仓（linked worktree）。
- **门会拦自己**：新门无法验证“引入它的那个 commit”（授权补齐的文件不在 spec allowed_paths 里）。bootstrap 可以接受，但必须写成**一次性、有记录的例外**，且不能成为先例；根因是“授权补齐”没有进入门的数据模型。
- **§6.11 是人的裁决，门只认字符串**：三连复发说明要么重建卡（把补齐写进 allowed_paths），要么把授权写进 record/ledger 让门识别（completion-list）。“最小补齐”本身不是机制，只是记账。
- **测试要复现攻击，不是复现实现**：作者自测覆盖了“多改一个文件”，但 rename、嵌套 checkout、换 `.git` 都是复核者找出来的——**范围门的测试集应按“攻击类别”写，不按“代码分支”写**。
- **兼容边界要注记**：独立 clone、塔仓本身是 linked worktree 会被身份检查拒绝；当前部署可接受，换形态时要改谓词（common-dir / 已注册 worktree）。

**判例**：diff 的名字不是变更的事实；范围门的第一课，是它可能先拦住自己。

### 6.22 判例：把“例外”变成记录，把“基线”变成锚（PILOT-042）

`PILOT-042` 补 041 的两个结构性窟窿：**授权完成清单**——`completion-add --by mac --reason … --decision …` 把“这条越界被 owner 批准过”写进 `record.completions` 与 primary ledger 的 `COMPLETION_ADDED`（幂等、双向半写可修），`deliver` 的允许集变成 `allowed_paths ∪ completions` 并输出 `scope_completions`，`state-verify` 新增 `completion_unbacked/missing/invalid` 三种 drift；**base_sha 锚定**——dispatch 记录 `base_sha`，deliver 用它（而非当前 `main`）做 diff 基线并校验它是 HEAD 祖先，`update-ref refs/heads/main HEAD` 再也不能把 diff 掏空。实测：419 tests、PR #27 `01213ce`、post-merge 7/7（塔 `419/387`）；旧码 A（completion 路径）exit 2 / 新码 0，旧码 B（改写 main ref 后越界）0 / 新码 2。

可复用判据：

- **例外必须进数据模型**：041 的 §6.11 补齐只能 bootstrap，因为“授权”只存在于人的对话里。042 把它变成 `completion-add`（record + ledger），门才知道“这条越界被批准过”。**人的裁决不落账，就等于没有裁决。**
- **基线要锚在 dispatch，不是锚在“现在”**：deliver 用 `merge-base main` 等于信任“当前 main 没被动过”；`update-ref` 一行就能让 diff 为空。base_sha 在派单时固化，交付时校验祖先关系。
- **记录层成为新的信任边界**：completion 与 base_sha 都存在 record/ledger；deliver 只信 record，`state-verify` 才交叉校验。能写 record 的人可以“伪造授权”——这不是门被绕过，是威胁模型上移；下一层要做“deliver 反查 backing 事件”。
- **卡面文字也是契约**：acceptance 写“恰四个 allowed_paths”、实际交付 2 个；诚实做法是承认文字缺陷、不凑数。**测试文件数不是质量指标**；`allowed_paths` 是上限，diff 是真子集即合格。
- **对称的半写修复**：completion-add 对“只有事件/只有记录”两个方向都可修且幂等；任何“两侧写”的新机制，先回答半写怎么办，再谈正常路径。
- **冗余授权会污染统计**：path 已在 allowed 时仍可 add；deliver 把 union 命中的都列进 `scope_completions`——口径要写清，否则“用了哪条授权”会被误读。

**判例**：例外不落账，等于没有例外；基线不在派单时锚定，等于没有基线。

### 6.23 判例：门要看见它声称覆盖的全部对象（PILOT-044）

`PILOT-044` 把“代码形状”变成机器门：零依赖 AST 的 `shape-check` ratchet——新函数 >80 行/12 分支、新文件 >600 行、新 ≥15 行重复块、新未使用 import 即 `exit 2`，基线 `state/SHAPE-BASELINE.json`（1,114 条，可字节复现）冻结 16 个既有长函数；`deliver` 固定读**塔根**基线，worktree 改/删基线 → `exit 2`；`checkback --structure` 把 Structure 五问写进 REVIEW.md。实测：441 tests、PR #28 `129dd4e`、post-merge 7/7（塔 `441/419`）、main `shape-check` 31 文件/1,192 函数 exit 0。

首轮复核按卡面夹具判 PASS，但 controller 判 **FAIL**：`shape-check` 只扫 module-level 函数——worktree 1,178 个 `def` 只覆盖 312 个（26.5%），新 91 行 TestCase 方法 `exit 0`；且 `deliver` 读 worktree 自己的 baseline，把长函数写进 baseline 或删除 baseline 即可关掉门。返工后方法/嵌套以限定名纳入（覆盖 1,192），基线锚到塔根，第二轮回 PASS。

可复用判据：

- **“函数”要按字面覆盖所有 `def`**：只扫 `tree.body` 会漏掉 class 方法与嵌套函数，而测试方法正是 AI 最容易写长的地方。**门必须能看见它声称覆盖的全部对象**，否则覆盖率数字（26.5%）比没有门更危险。
- **基线是记录层，必须不可自关**：让被判者读/写自己的基线，等于让他改判据。基线要锚在门外（塔根/main），worktree 的副本只能逐字节相等，改/删都 fail closed。
- **引入新门的一次性 bootstrap 要记录**：新门要求它自己引入的基线，pre-merge 必然无法自我验证；这不是绕过，但要按 041 先例写成一次性例外，并说明“merge 后所有交付走新门”。
- **skip 条件是门的一部分**：为兼容 pre-state 夹具而设的“两侧无 `state/` 即 skip”，留下一条“先删 state 再 deliver”的潜在路径；兼容豁免必须写清适用条件并尽快收紧。
- **阈值是启发式，口径要钉死**：80 行/12 分支是代理指标；分支计数口径（7 类节点各 1）要用测试锁定，否则同一函数不同人算出 44/49。
- **dogfooding 是唯一可信的验收**：044 自己的新函数全部 ≤80 行/≤12 分支、基线不含 044 代码，才证明这套预算可执行；做不到就说明设计该拆。

**判例**：门必须能看见它声称覆盖的全部对象；基线必须锚在门外。

### 6.24 判例：地图要可校验，状态要可重算（PILOT-045）

`PILOT-045` 落命令层 v1：`command/STRATEGY.md` + `command/campaigns/*.md` 是 front-matter 可机读的地图；`campaign-check` 校验 E1–E6（缺失、goal 不存在、`review_by` 过期、WIP 超限、`task_forces` 卡不存在、id 重复）与 W1/W2（孤儿卡、临近预算），错误 exit 2、`--strict` 升级；`brief` 只读生成七节一页纸。实测：467 tests、PR #29 `99b61a1`、post-merge 7/7（塔 `467/441`）、真实塔根 `campaign-check` exit 0（wip 0/1、W1 44）、`brief` 23 行。

首版有一个真 bug：`brief` 把 `tasks/PILOT-025-VOID`、`PILOT-039-VOID` 当活卡（内部 id 仍是原 id），输出"在飞 025、阻塞 039"。修法：只收规范目录名（不以 `-VOID` 结尾）且要求 `record.id == 目录名`；补 VOID 回归测试。

可复用判据：

- **地图必须可校验**：STRATEGY/campaign 不是散文；front-matter + E1–E6 + W1/W2 让"目标→战役→卡"可机读；没有校验的地图是海报。
- **状态视图必须排除归档**：`*-VOID` 目录里的 record 内部 id 仍是原 id，通配读 `tasks/*/record.json` 会把归档当活卡；目录名与内部 id 必须双重校验。
- **只读生成物要证明只读**：静态无写调用 + 运行前后哈希不变 + ACL 禁写目录仍可跑，三者缺一不可。
- **pre-merge 的结构性缺口要显式**：worktree 无 `tasks/<id>` 时 E5 用 `pilot/<id>.spec.json` 兜底；可接受，但应发 W3 级 finding，不能静默（048 前）。
- **接 CI 前先处理 strict**：44 条 W1 让 `--strict` 必红；048 要么先回填 44 卡，要么 CI 先跑非 strict，否则门一接就挂。
- **brief 是投影，不是新状态源**：一页纸从 STRATEGY/campaign/board/record 生成，手改即伪造。

**判例**：地图不校验就是海报，状态不重算就是传说。

### 6.25 判例：状态不是文档，是投影（PILOT-046）

`PILOT-046` 给状态加历史：`status-snapshot` 同日多次**只追加**；`status-index` 生成 `status/index.json`（days.entries + 文件 sha256），删除后可重算且字节相同；`status-rollup --week` 字节稳定；`status-archive` 只压缩不删原件。同卡硬化 045 的五个边界：E7（board 形状）、R3（空 `task_forces`）、R4（单引号）、R5（budget 中英文/周数）、W3（spec-only）。实测 487 tests、PR #30 `63d7b47`、7/7（塔 `487/467`）；复核在 868 个非 status 文件上零改动。

可复用判据：

- **状态只追加**：同日多条不覆盖；重写历史等于伪造。
- **摘要必须可重算**：删掉 index 重建字节相同，sha256 钉的是原始字节；生成物手改即失效。
- **归档只压缩、不删除**：删历史是另一个决定，必须 owner 拍板。
- **只读边界要证明**：status 命令只写 `status/`，运行前后 primary/ledger/tasks 哈希不变。
- **写失败也要干净**：R-1 的 Traceback 是缺口——写路径的 `OSError` 必须变成 exit 2 单 JSON。
- **双分母要统一**：`campaign`（task_forces）与 `position`（roadmap）并存时，人一定会问“到底几比几”；下一卡统一或改名。

**判例**：状态不是文档，是投影；投影不可重算，就是传说。

### 6.26 判例：地图要标“你在这”，还要标对分母（PILOT-047）

`PILOT-047` 给塔加双视图位置图：campaign `roadmap/current` + `where --json`（schema `tower/position@1`、枚举 `done/active/blocked/planned/skipped`、顺序=roadmap、无时间戳）与人视图（7 行：位置条、x/y、下一站、为什么/交付/风险/建议）；E8/E9 干净 exit 2；注入 checkback/close/post-merge/status-snapshot/brief。实测 518 tests、PR #31 `b4c7859`、7/7（塔 `518/487`）；首轮 merge 遇 GitHub GraphQL EOF → `MERGE_BLOCKED` → `CORRECTION_REQUIRED` 重试成功，未产生重复 PR。

可复用判据：

- **机器视图要枚举化**：状态只有五个值、顺序=roadmap、无时间戳、非法即 exit 2；机器不读人视图，人不读 JSON。
- **人视图回答五问**：我在哪、下一站、为什么、风险、该不该继续；只画图不标“你在这”是海报。
- **同一模型、两个渲染器**：`where`/`where --json`/`brief`/`status position` 必须同一 `position` 计数，否则两边打架。
- **index 语义要写死**：`index` 是 done 计数还是 1-based 偏移，必须测试锁定；spec 文字与验收冲突时写 errata，不靠猜。
- **E8 严格、campaign-check 兼容**：位置是 opt-in，老塔没有 roadmap 不能假装有；`where` 严格拒绝，`campaign-check` 保持 legacy 绿。
- **瞬断可重试**：`MERGE_BLOCKED` + `CORRECTION_REQUIRED` 是重试语义，不是终态；重试不得产生重复 PR/重复账本事件。

**判例**：地图不标“你在这”是海报；标了但分母算错是误导。

### 6.27 判例：架构文档必须能被代码证伪（PILOT-048）

`PILOT-048` 建架构脊柱：`ARCHITECTURE.md` 六节（上下文/组件/数据流/契约/扩展点/不变量）；`arch/GATES.json` 把每道门绑到真实 command 与**拒绝路径**测试；`arch/INVARIANTS.json` 把 RED-LINES C-01..C-16 绑到真实 probe；`EVENT_CATALOG.json` 与代码字面事件 type 双向一致（29 条）；`adr/ADR-0001` 归档 DESIGN（正文逐字节不变）；`arch-check` 六项对账、`arch-graph` 35 nodes/21 edges 字节稳定。048 自身经历首轮/二轮 FAIL：ARCHITECTURE 的 CI 行、C-12 分类、行数三处当天就与 workflow/RED-LINES/HEAD 不符；修完才 PASS。

可复用判据：

- **每条声明要有执行点**：门 → command+test，不变量 → probe，事件 → 代码 type，ADR → related_files；找不到执行点的句子是散文，不是架构。
- **文档不实就是缺陷**：reviewer 要拿 CI workflow、RED-LINES、`HEAD` 行数逐条对照，不能只看六节标题在不在。
- **门表的 test 必须指向拒绝路径**：正例只能证明“能过”，不能证明“会拦”。
- **冻结 spec 的笔误用 completion 兜底**：DESIGN 实际在 `control-tower/` 而 spec 写成 `tower-dsh/`；owner 签名 `D-PILOT-048` 授权移动，不重开卡、正文不改。
- **路径围栏 fail-closed**：绝对路径、盘符、`..`、出塔根、duplicate stem 一律拒绝；`related_files` 只接受塔内真实文件。
- **边界要写全**：事件只扫字面量（变量/f-string 会逃逸）、arch-check 只证引用存在、C-12/C-15 无自动化 proof——不藏。

**判例**：架构文档不是“写给人看的”，是“写给门核对的”。

### 6.28 判例：目标门要拦在写卡之前（PILOT-049）

`PILOT-049` 落 objective 硬门：`tower/spec@2` + `objective.problem/outcome/approach/non_goals_and_done`；`task-new` 对**所有新 spec** 在创建 `tasks/<id>/`、写 record/TASK、append `TASK_NEW` **之前**校验，缺项/占位/过短 → exit 2 且零写入；`spec-lint` 只扫顶层 `pilot/*.spec.json`，@2 强制、@1 冻结跳过；`GATE-SPEC-OBJECTIVE` 进门表；`ADR-0002` 记录决策。测试 552、PR #33 `7d8ca4a`。

可复用判据：

- **校验在写之前**：零写入要能被证明——无 tasks 目录、无 ledger 事件、board 不变；已有卡不覆盖。
- **旧卡冻结**：@1 跳过，不回溯、不改哈希；新卡 @2。
- **双层必须是两层真实执行点**：task-new（创建入口）+ spec-lint（@2 扫描）；只写一层是假双层。
- **机器检查只证结构与最低内容量**：8 字符、整值占位都能被空洞文本绕过；目标真实性仍靠 reviewer。
- **占位规则要防“前缀占位”**：049 实现为整值 `__FILL__`，因此 `TODO __FILL__`、`__FILL__x`、`补充 <待填写>` 仍能过——这是已记录残余，下一卡可加“前缀 marker + 混合占位”规则。
- **卡面自相矛盾时停下报告**：GATES 加门会打破 `test_arch` 的 `gates=15` 字面量，用 completion `D-PILOT-049` 授权改一行；`__FILL__` 子串语义会让 049 自己过不了门，reviewer 裁决为整值。

**判例**：目标门不是“多一个字段”，是“没有目标就不许建卡”。

---

## 7. 与 K3 塔的能力对照（一页）

| 维度 | K3 / SeeMake 塔 | tower-dsh | 谁更强 |
|---|---|---|---|
| 项目状态 | `CURRENT`（包号禁令）+ Authority State + v37 包 | `CURRENT_STATE.json` + handoff 包 + **`authority_dirty`**（011）+ **`AUTHORITY.json`/`authority-check`/merge pin**（037）+ **required 标记**（038） | **木塔**：身份可判定，且“必须配置”有独立记录 |
| 系统事实冻结 | 画像族：DB / 队列 / 存储 / 部署 / 多用户 / 实施 | **无** | K3 |
| 不变量可执行性 | 画像多为散文 + 基线与采集脚本 | 27/27 tool-check 有测试、门是 `exit 2` | **木塔** |
| 趋势治理 | 锚点 + 周测 diff + 熔断 + 重锚 | **无** | K3 |
| 版本控制 | `_k3-ops/` **永不入 git** | 塔在 `Control-Tower-Kit` 仓（199 文件） | **木塔** |
| 独立性 | 四重**同身份**评审 | 独立 subagent reviewer，`reviewer != executor` 硬断言；037 首轮 FAIL 抓到 3 个契约缺陷 | **木塔** |
| 决策证据 | owner 向量 + 题包 SHA-256 | 证据 SHA-256 + ledger 哈希链 | 平（木塔链更强，K3 题包公理化更强） |
| 交接 | v37 包 + CURRENT 防呆 | v2.1 五步状态机 + 21 项 check | 木塔流程更严，K3 防呆更实用 |
| 判例 | `治理判例集.md` | 28 条在 `MAP.md` §6.1–§6.28 | 平（K3 更成体系，木塔已可引用） |

---

## 8. 这张图自己的边界

- **只读快照**：生成期间不写状态、不 merge、不碰生产、不外部调用；唯一写入是本文件。其后按 owner 逐次授权提交了 handoff 状态（`26d2f6f`，见 §6）——那是状态的提交，不是地图的改写。
- **数字口径**：任务/信封数来自 `status`；条款数来自 `spec-coverage`；账本数来自 `verify-ledger`；测试结论来自 2026-10-19 23:3x 的一次复跑（环境异常，已如实记录，不伪装成绿）。
- **会过期的部分**：§5 的测试结论、§6 的漂移清单——两者都应在下一次 `startup` 时重算。
- **刷新触发**：phase 变更 / 新增任务卡 / 门禁代码（`towerctl.py`）变更 / 新 handoff 包 / 接入真实项目 —— 任一发生即重画。
- **不做什么**：不代替 `CURRENT_STATE.json`，不充当授权记录，不作为"完成"证据。地图是投影，不是真相。
