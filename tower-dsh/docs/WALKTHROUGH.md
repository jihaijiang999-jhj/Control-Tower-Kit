# WALKTHROUGH — 从 task-new 到 post-merge 的可执行路径

> 一张卡从 spec 到 `POST_MERGE_VERIFIED` 的完整命令序列，含每一步的 owner / reviewer / envelope / post-merge 判据。
> 命令都在 **tower 根**（`tower-dsh/`，包含 `tools/` 的目录）执行，除注明 `git -C` 的仓库操作。
> 仓库根（`Control-Tower-Kit`）是 tower 根上一级；`control-tower/`、`.github/` 在仓库根，`merge-envelopes/` 两侧各有一份（见 MAP §6.37）。
> 权威仍然是 `ledger/*.jsonl`；本文件只描述路径，不替代 `towerctl` 的判定。

## 0. 角色与四闸

| 角色 | 谁 | 能做什么 | 不能做什么 |
|---|---|---|---|
| Owner | `mac` | 四闸：merge / 外部调用 / 部署·生产数据 / L0 文档写 main；`accept`/`post-merge` 的 `--by` | 代替 reviewer 自批、绕过 ledger |
| Primary | 主控制塔 | spec、`task-new`、worktree、`dispatch`、`deliver`、envelope/queue、PR | **不 merge**、不改 supervision 账本以外的方式写队列 |
| Supervision | `sup-phase2-pilot` | 独立验收、串行队列、`merge`、`post-merge`、纠正单 | 改候选实现、自批 |
| Executor | DSH subagent | 只写 `allowed_paths` + `scratch/` | 写 `primary/`/`supervision/`/`ledger/`/`shared/`、merge |
| Reviewer | 另一个独立 DSH subagent（≠ executor） | 只读、亲跑证据、`checkback` | 改工作树、自审 |

判据总则：**每个完成声明都要有 sha256 证据 + ledger 事件**；`MERGED` ≠ 完成，只有 `POST_MERGE_VERIFIED` 是完成。

```powershell
$TOWER = (Get-Location).Path          # tower-dsh/
$REPO  = Split-Path $TOWER -Parent    # Control-Tower-Kit 仓库根
$ID    = "PILOT-079"                  # 本示例
$WT    = "pilot/worktrees/$ID"
```

## 1. 写 spec（primary / owner 批准）

`pilot/<ID>.spec.json` 必须是 `tower/spec@2`，`objective` 四要素齐全（`problem/outcome/approach/non_goals_and_done`），`allowed_paths` 写**塔根相对**路径。最小骨架：

```json
{
  "schema": "tower/spec@2",
  "id": "PILOT-079",
  "title": "一句话目标",
  "objective": {
    "problem": "为什么现在要改（可证伪）",
    "outcome": "完成后什么成立",
    "approach": "怎么改",
    "non_goals_and_done": "不做什么；何时算完成"
  },
  "authority": "workspace_write",
  "anchor": "ADR-00NN",
  "why_now": "为什么是这张卡",
  "scope": ["..."],
  "allowed_paths": [
    "pilot/worktrees/PILOT-079/tower-dsh/tools/example.py",
    "pilot/worktrees/PILOT-079/tower-dsh/tools/tests/test_example.py"
  ],
  "forbidden": ["network", "merge", "production access"],
  "acceptance": ["python -B tools/run_tests.py 全绿", "..."],
  "depends_on": ["PILOT-078"],
  "worktree": "pilot/worktrees/PILOT-079"
}
```

## 2. task-new（建卡，冻结 spec）

```powershell
cd $TOWER
python tools/towerctl.py task-new --spec pilot/$ID.spec.json
```

判据：

- 新建 `tasks/<ID>/{TASK.md,record.json}`，record.status=`ready`，`state/TASK_IDS.json` 登记 `active`；
- 写 `TASK_NEW` 事件；`objective` 缺项 / ID 复用 → **exit 2 且零写入**；
- **ID 不复用**：`python tools/towerctl.py task-new --spec pilot/PILOT-072.spec.json.parked`
  必须 exit 2（072 在 `TASK_IDS` 是 `void`），不得靠改目录名绕过。

## 3. spec-approve + check

```powershell
python tools/towerctl.py spec-approve --task $ID --by mac --note "owner approve"
python tools/towerctl.py check --task $ID --phase spec     # spec_gate=PASS
python tools/towerctl.py check --task $ID --phase ready    # 依赖已 closed、无环
```

判据：`spec-approve --by` 的批准人 ≠ executor；`check --phase spec` 复算 spec 的 sha256，改一个字节即失败；`ready` 要求 `depends_on` 每张卡 `closed`。

## 4. 建 worktree（primary）

```powershell
cd $REPO
git worktree add tower-dsh/$WT -b pilot/$ID main
git -C tower-dsh/$WT rev-parse --show-toplevel      # 必须等于 worktree 绝对路径
git -C tower-dsh/$WT rev-parse --git-common-dir     # 必须指向本仓库 .git/worktrees/...
git -C tower-dsh/$WT status --short                 # 开始前必须干净
```

判据：worktree 必须是**本仓库的 linked worktree**（`deliver` 会校验 toplevel 与 gitdir）；`pilot/worktrees/` 已被仓库根 `.gitignore` 忽略。

## 5. dispatch（primary）

```powershell
cd $TOWER
python tools/towerctl.py dispatch --task $ID `
  --executor "subagent:agent-x" `
  --worktree $WT `
  --kind subagent `
  --campaign C-2026-Q4-04
```

判据：

- 前置：`spec_gate=PASS`、依赖全部 `closed`、只有一个 active campaign（`--campaign` 必填）；
- 记录 `record.dispatch.base_sha = main HEAD` 与 `DISPATCH` 事件；**executor 不得移动 base**；
- worktree 落后时先 `git -C <WT> merge --ff-only <base_sha>`，让 base 成为 HEAD 祖先（否则 `deliver` 的 base 门 exit 2）；
- 若只是换 executor，可对 `dispatched` 再 dispatch；`delivered` 及以后拒绝。

## 6. 执行（executor：只写 worktree）

```powershell
cd $TOWER/pilot/worktrees/$ID/tower-dsh
# 只改 spec.allowed_paths；证据放 <WT>/scratch/（untracked，允许）
python -B tools/run_tests.py                 # Ran 844+N / OK
python -B -m unittest tools.tests.test_example -v
python tools/towerctl.py state-verify        # 只读，drift []
python tools/towerctl.py shape-check         # 新函数超预算会 exit 2
```

判据：`git -C <WT> status --porcelain` 只有目标路径 + `?? scratch/`；不碰 `primary/`、`supervision/`、`ledger/`、`shared/`；不改塔状态。

## 7. deliver（primary）

```powershell
cd $TOWER
python tools/towerctl.py deliver --task $ID `
  --evidence $WT/scratch/test-output.txt `
  --evidence $WT/scratch/commit.txt `
  --evidence $WT/scratch/diff.txt `
  --evidence $WT/scratch/gates.txt
```

判据（全部在复制证据**之前**）：

- **范围门**：`git diff --name-only --no-renames <dispatch.base_sha>..HEAD ⊆ allowed_paths ∪ owner completions`；
  越界 / tracked 未提交 → exit 2，零写入；
- **base 门**：base_sha 必须是 HEAD 祖先；不信任可改的 record，取 `DISPATCH` 事件；
- **shape 门**：worktree 必须带塔根的 `SHAPE-BASELINE.json`，不得越基线；
- 成功后 record=`delivered`、写 `DELIVERY.md` 与 `DELIVER` 事件，证据逐条 sha256。

## 8. checkback（独立 reviewer，read-only）

```powershell
cd $TOWER
python tools/towerctl.py checkback --task $ID `
  --reviewer "subagent:agent-y" `
  --verdict PASS `
  --note "8 paths; Ran 844+N; gates ok" `
  --structure "边界/数据流/失败路径/测试/可复现" `
  --head  (git -C $WT rev-parse HEAD) `
  --base  (python -c "import json;print(json.load(open('tasks/$ID/record.json',encoding='utf-8'))['dispatch']['base_sha'])")
```

判据：

- `reviewer` 非空且 **≠ executor**（同上下文自审 exit 2）；
- 默认 `--head` = worktree HEAD、`--base` = dispatch base；写 `REVIEW.json` + `CHECKBACK`；
- reviewer 必须亲跑证据，不能只读 executor 的结论；FAIL → 回 `rework` 重新 dispatch/deliver。
- `state-verify` 会核对 `REVIEW.json` 与最后一条带 head 的 `CHECKBACK`：不一致 → `review_unbacked` drift。

## 9. accept / close（owner 决策）

```powershell
python tools/towerctl.py accept --task $ID --decision "D-$ID" --by mac --note "PASS"
python tools/towerctl.py close  --task $ID
```

判据：`ACCEPTANCE.json` 的 auto 项全部 `passed`；任何 `failed` 拒绝；manual pending 必须
`--allow-manual-pending` 且每项有 note；`accept`/`close` 内联复核证据哈希。

## 10. envelope（base-side；primary 写文件 → supervision 验）

```powershell
# 1) 在 main 上提交一份只含 envelope 的 commit（base-side）
$ENV = "ENV-$ID"
#   tower-dsh/merge-envelopes/$ENV.json，字段见下
cd $REPO
git add tower-dsh/merge-envelopes/$ENV.json
git commit -m "chore: base-side envelope $ENV (main only)"

# 2) 回 tower 根登记
cd $TOWER
python tools/towerctl.py envelope-new --task $ID --file merge-envelopes/$ENV.json --base-side
```

envelope 必填：`schema=tower/merge-envelope@1`、`envelope_id`、`task`、`repository=".."`、
`branch="pilot/$ID"`、`base="main"`、`implementation_head_sha`=worktree HEAD、`envelope_path`、
`tests_baseline` / `tower_tests_baseline`（无基线 → exit 2）、`evidence` 列表。

判据（`--base-side`）：

- envelope commit 只改 envelope 路径、在 base 里、parent 是 implementation 祖先；
- `branch head == implementation_head_sha`（PR head 必须只含实现）；
- 状态 `DRAFT`，写 `ENVELOPE_NEW`；`MERGED`/`VERIFIED` 不能重开（只能新卡）。

## 11. queue + merge-check（supervision）

```powershell
python tools/towerctl.py queue-add --envelope $ENV
python tools/towerctl.py merge-check --envelope $ENV
```

判据：`queue-add` 写 `WAITING` + `QUEUE_ADD`；`merge-check` 至少要过
REVIEW 绑定（PASS + head/base 对齐）、baseline 不回退、两条 ledger 链完整、
`implementation_head_sha` 与 envelope 一致。`merge-check` 失败 → exit 2，零 `MERGE`。

## 12. merge（**owner 授权，supervision 执行**）

```powershell
python tools/towerctl.py merge --envelope $ENV `
  --role supervisor --supervisor sup-phase2-pilot `
  --mode pr
```

判据：

- 前置三链：authority pin（`sup-phase2-pilot` + owner/primary GitHub login 不同）→ primary/supervision ledger 链
  → 空账本守卫；缺一即 exit 2；
- PR 模式要求 PR 上有 **owner 账号的 APPROVED review**，且 approver ≠ primary / PR author（076+；076 是 legacy bootstrap）；
  `--match-head-commit` 钉死 head；
- base 只前进了 state-only 路径时，才允许 `--allow-state-ahead` 的**审计 admin**
  （ledger 写 `admin=true` + `base_sync=state-only`）；base 前进含 code 时不得 admin；
- **deviation 出口**：已经直接 `gh --admin` 合并但信封还停在 WAITING/CORRECTION 时，
  用 `envelope-recover --merge-commit <sha>` 补 `MERGE`（`recovered=true`），**不写 verified**；
  审计 admin 后信封尾部半写，同样先 recover（`recovered` re-fold）再 post-merge。
- 判据：queue=`MERGED`，supervision ledger 有 `MERGE`（带 `admin`/`recovered` 标记）。

## 13. post-merge（supervision / owner 视角）

```powershell
python tools/towerctl.py post-merge --envelope $ENV --result PASS --by mac
python tools/towerctl.py state-verify        # drift []
python tools/towerctl.py where --json        # C-04 位置推进
```

判据（9/9，任一失败即 `CORRECTION_REQUIRED` + `POST_MERGE_FAILED`）：

- 源状态只能是 `MERGED`；必须有 `MERGE`/`MERGE_HISTORICAL` 且 `merge_commit` 非空、在 origin/main、第二父 == implementation；
- 根套件与塔套件计数 ≥ baseline；baseline 不得低于历史 verified；
- implementation 是 base 祖先；信封在 base（base-side 走 tower 前缀）；工作树干净；
- `campaign-check` 0 error、`arch-check` 0 finding；
- 测试期间不改塔状态（077 起先 snapshot，失败先 restore 再写 CORRECTION）；
- 成功才写 `POST_MERGE_VERIFIED`；`01` deadline 卡在 `where` 的完成度以 campaign 节点为准。

## 14. 判据速查

| 阶段 | 命令 | 通过判据 | 谁 |
|---|---|---|---|
| 建卡 | `task-new` | exit 0；ID 未登记；objective 完整 | primary |
| 批准 | `spec-approve` | 批准人 ≠ executor | owner |
| 调度 | `check --phase ready` / `dispatch` | 依赖 closed；spec_gate PASS；base_sha 记录 | primary |
| 交付 | `deliver` | 范围/base/shape 三门全过；证据 sha256 | primary |
| 复核 | `checkback` | reviewer ≠ executor；PASS；head/base 绑定 | reviewer |
| 验收 | `accept` / `close` | ACCEPTANCE auto 全 passed | owner |
| 信封 | `envelope-new --base-side` | 只改 envelope；head=impl；baseline 非空 | primary |
| 入队 | `queue-add` | WAITING + QUEUE_ADD；重复拒绝 | primary |
| 合并 | `merge-check` / `merge` | REVIEW/baseline/两链/authority 全过；owner 授权 | supervision |
| 合并后 | `post-merge` | 9/9；merge 事实可反查；drift [] | supervision/owner |

## 15. 不要做的事

- 不要复用已登记 ID（`072` 是 `void`，复用会被 `task-new` 拒绝）。
- 不要在没有 `MERGE`/`MERGE_HISTORICAL` 事实时写 verified；先 recover。
- 不要把 `MERGE_HISTORICAL` 回填说成审计 admin，也不要把 `16-16` 说成 16 次 verified merge。
- 不要让 executor 写 `primary/`/`supervision/`/`ledger/`/`shared/`，也不要让 reviewer 改 worktree。
- 不要在 base 前进含 code 时用 `--allow-state-ahead`；不要用 local merge 替代 PR 路径（除非卡上明示）。
- 不要声称 online CI 已验证；除非给出 run URL。
