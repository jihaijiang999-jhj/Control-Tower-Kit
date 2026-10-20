# tower-dsh 控制塔地图 / 画像

> 生成者：`ctl-yingxian-qa-001`（接续 controller）· 生成时刻：2026-10-19T23:5x +08:00
> 性质：**只读快照**。不替代 `tower-dsh/primary/CURRENT_STATE.json`，不构成状态。
> 修订：2026-10-20T00:5x —— §6 由"漂移"改为"已闭合"，§1 phase 按实值更正，§8 口径同步。
> 修订：2026-10-20T02:2x —— PILOT-011 落地（authority drift 可观测）；§3/§5/§6/§7 同步，新增 §6.2 排序陷阱。
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
| ∅1 | 远端 PR / 分支保护 | CI 已通电并在 main 上跑绿（run 39346811217）；2026-10-20 仓库转 public 后已开 main 保护：**禁强推、禁删分支、要求 `tower gate` 检查**；但 `enforce_admins=false`，owner 仍可直推 | 门对"非管理员"是硬的；对 owner 仍是软的——全锁需要先把 merge 改成 PR 流程（PILOT-015） |
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
| ∅10 | **状态重放** | （K3 也没有；木塔本可领先） | 状态是并行写，不是 `f(ledger)` | `towerctl state-verify`：从 ledger 重放 → 与 board/record/state 逐字段比对 |
| ∅11 | **测试计数门** | （K3 也没有） | `post-merge` 只认 exit code，空 `tests/` 也 PASS | 解析 `Ran N tests`，要求 `N >= baseline`（baseline 存进 envelope） |
| ∅12 | **证据可复现** | — | 134 测试依赖 `%TEMP%` ACL 与 Windows | 测试强制 `TMPDIR` 沙箱内建塔 + 干净环境复跑清单 |

---

## 5. 已证明 / 仅声明 / 未做（用数字说话）

| 能力 | 判定 | 证据 |
|---|---|---|
| spec 冻结（改 spec 即失效） | `[证]` | `spec_gate_errors` 每次实时复算 SHA-256（`towerctl.py:442-470`） |
| `dispatch` 前置 spec 门 | `[证]` | `cmd_dispatch:932-934`；PILOT-002 回归测试 |
| accept / close 强证据 | `[证]` | `cmd_accept:1022`、`cmd_close:1046` 内联 `check_evidence` |
| reviewer 非空且 ≠ executor | `[证]` | `cmd_checkback:992-996` |
| merge 分支断言 | `[证]` | `cmd_merge:1919-1936`，不符即 `CORRECTION_REQUIRED` |
| post-merge 四检 | `[证]` | 测试 / 实现是祖先 / 信封在 base / 工作树干净（`2058-2070`） |
| 路径越界防护 | `[证]` | `ensure_within` 覆盖 evidence / worktree / package / envelope / repository |
| ledger 哈希链 | `[证]` | `verify-ledger` → primary 103 事件、supervision 54，0 error；legacy 未哈希 53 / 26（按 INV-05 只计不判） |
| 条款→测试绑定 | `[证]` | `spec-coverage`：6 份规范 / 56 条款 / tool-check 27 / covered **27** / gaps 0 |
| 测试全绿 | `[证]`（有条件） | `Ran 163 tests / OK`（本地 2026-10-20，PILOT-014 后）；GitHub Actions `Ran 163 tests in 68.271s`（run 39346811217，全绿）。**本地前提是完全权限**：受限模式下 `TMP` 被重定向到 `%TEMP%\dsh-*`，`tempfile.mkdtemp` 用 0o700 建的目录拿不到沙箱写权限，134/134 会在 0.05 s 内全 ERROR（∅12 仍在） |
| 29 条条款靠人 | `[声]` | 12 `review-check` + 17 `owner-gate`（`spec-coverage.manual` / `.owner`） |
| "每次迭代全局正确" | `[无]` | 无对象层不变量、无趋势锚点、无状态重放 |
| 14 个任务 / 14 个信封 | `[证]` | 全部 `closed` + `POST_MERGE_VERIFIED`（PILOT-011 `6a849b9`；012 `bc4be88`；013 `10bf606`；014 `4ef0695`，post-merge 均 4/4）；GitHub 门禁 run 39346811217 全绿 |

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

**同时更正**：`handoff-activate` 把 phase 从 `READY_FOR_PRACTICE` 改为 `HANDOFF_ACTIVE`、`next_action` 改为 `resume from handoffs/HANDOFF-PILOT-002/HANDOFF.md`；§1 主图已按实值更新。

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
