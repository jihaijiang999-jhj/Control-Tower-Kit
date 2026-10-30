# PILOT-052 — 对象层：PROFILE v1 + profile-check（∅5）

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-052`

## Scope

- state/PROFILE-TEMPLATE.md：schema=tower/profile@1 front-matter（object/version/updated/owner/status）；固定表格列 id | fact | probe | expect | why；probe 只允许 towerctl 子命令，expect 支持 exit 码与可选 stdout 子串
- state/PROFILE-TOWER-DSH.md：对象 TOWER-DSH 的 10 条事实（authority configured+required、ledger 链完整、state drift 0、arch-check 通过、campaign-check 通过、shape-check 通过、spec-lint 6/6、where 可渲染、startup/wiring 健康、测试基线可复跑），每条带只读 probe 与 expect；不写会随版本漂移的计数（如 tests N）
- towerctl profile-check：--file/--object 选择；解析 front-matter 与表格，校验必需列、id 唯一、probe 非空、probe 是允许的 towerctl 子命令（禁止 profile-check 递归、禁止 deliver/merge/close 等写命令）；逐条运行（subprocess，带 --root），比对 exit 与 stdout 子串；失败 exit 2 单 JSON（findings: id/expected/actual），全部通过 exit 0；缺文件/坏 front-matter/未知 probe → exit 2 无 Traceback
- arch/GATES.json 增加 GATE-PROFILE（command=profile-check、phase=objects、test 指向 test_profile 的拒绝用例）；tools/tests/test_arch.py 的 gates 计数 16→17（本卡 allowed，不用 completion）
- ARCHITECTURE.md §4 增加“对象层”契约段：PROFILE schema、probe 白名单、profile-check 只读、对象 0 的限制
- 新增 tools/tests/test_profile.py：模板可解析；10 条事实全通过；缺 front-matter/缺列/id 重复/未知 probe/写命令 probe/exit 不符/stdout 不符/坏表格/缺文件 → exit 2 单 JSON；profile-check 运行前后塔状态哈希不变；@1 旧塔无 PROFILE 不影响其他命令
- 不改 036–051 的信任边界/授权/前置链/范围门/completion/shape/objective/campaign/depends_on 语义；不新增事件类型；不改 spec@2；不写 primary/supervision/ledger

## Allowed paths

- `pilot/worktrees/PILOT-052/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-052/tower-dsh/tools/tests/test_profile.py`
- `pilot/worktrees/PILOT-052/tower-dsh/tools/tests/test_arch.py`
- `pilot/worktrees/PILOT-052/tower-dsh/state/PROFILE-TEMPLATE.md`
- `pilot/worktrees/PILOT-052/tower-dsh/state/PROFILE-TOWER-DSH.md`
- `pilot/worktrees/PILOT-052/tower-dsh/arch/GATES.json`
- `pilot/worktrees/PILOT-052/tower-dsh/ARCHITECTURE.md`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening existing gates
- new ledger event types
- changing tower/spec@2 fields
- executing arbitrary shell commands from PROFILE
- probes that mutate state (deliver/merge/close/accept/dispatch)
- profiling a real external object without owner-provided facts
- touching TOWER.md (L0)

## Acceptance

- cd pilot/worktrees/PILOT-052/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 585 + 新增用例数（main 基线 585）
- profile-check 对 state/PROFILE-TOWER-DSH.md exit 0；10 条事实全部有 probe 且实际通过；输出 findings=[]
- 模板 state/PROFILE-TEMPLATE.md 可被 profile-check --file 解析（允许占位示例，不纳入真实对象断言）
- 缺 front-matter/缺列/id 重复/未知 probe/写命令 probe/exit 不符/stdout 不符/坏表格/缺文件 → 全部 exit 2 单 JSON、无 Traceback、findings 点名 id
- 只读证明：profile-check 运行前后 primary/supervision/ledger/tasks 关键哈希不变；probe 白名单拒绝 deliver/merge/close/accept/dispatch/profile-check
- arch/GATES.json 含 GATE-PROFILE 且 test 真实存在；test_arch 计数 17；arch-check 在 worktree exit 0
- 旧码对照：main 无 profile-check（argparse invalid choice exit 2）；新码 exit 0。证据写进 scratch/probe-old-code.txt
- shape-check 在 worktree exit 0（新增函数 ≤80 行/≤12 分支；既有函数不增长）
- 真实塔：worktree 新工具 campaign-check/arch-check/authority-check/profile-check exit 0、state-verify drift []；建信封前 tasks=52/envelopes=50，建信封后 52/51；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-052 diff --name-only main..HEAD 恰七个 allowed_paths
