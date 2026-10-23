# PILOT-034 — 合并门自验：ledger 链完整、ENVELOPE_NEW 存在、信封身份绑定请求 id

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-034`

## Scope

- cmd_merge_check 与 cmd_merge 在读取信封后校验 env.envelope_id 与命令行 --envelope 的请求 id 严格相等；不等即 exit 2（错误点名文件内容 id 与请求 id），不进入后续检查
- envelope_checks 新增可选参数 expected_id；两个调用方传入请求 id，新增检查 envelope identity matches request（ok = env.envelope_id == expected_id）；直接调用而不传 expected_id 时跳过该检查（兼容测试）
- envelope_checks 对新式信封（同时带合法 tests_baseline 与 tower_tests_baseline）新增两项检查：ledger chain intact（primary 与 supervision 两份 ledger 的 verify_ledger_file 均无 errors；detail 为第一条错误或 ok）；envelope_new recorded（supervision ledger 中存在该信封的 ENVELOPE_NEW 事件）
- 保留 033 的 queue entry backed by ledger 检查与 legacy 信封的兼容（旧信封不启用上述新式检查）
- 新增只读辅助 ledger_has_event(root, name, event_type, envelope_id)；复用 ledger_events_in_seq_order，坏行忽略
- 更新 tools/tests/test_envelope_baseline.py：伪造一行 QUEUE_ADD（坏哈希链）→ merge-check exit 2 且失败项含 ledger chain intact；只追加 QUEUE_ADD 不追加 ENVELOPE_NEW → envelope_new recorded 失败；把已背书信封内容复制为另一个 id 文件名并入队 → merge-check --envelope <新id> 因 identity 失败；正常 envelope-new+queue-add 通过全部新检查；legacy 信封行为不变

## Allowed paths

- `pilot/worktrees/PILOT-034/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-034/tower-dsh/tools/tests/test_envelope_baseline.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- trusting a file's self-declared identity without matching the requested id

## Acceptance

- cd pilot/worktrees/PILOT-034/tower-dsh && python -B tools/run_tests.py 全部通过，总数 >= 287（main 基线 287）
- 伪造 QUEUE_ADD 行（哈希链破坏）后 merge-check 新式信封 → exit 2，失败项含 ledger chain intact；同一塔 verify-ledger 也报错
- 只追加 QUEUE_ADD、不追加 ENVELOPE_NEW → merge-check exit 2，失败项含 envelope_new recorded
- 把已背书信封的 JSON 复制为 ENV-OTHER 文件名并入队 → merge-check --envelope ENV-OTHER exit 2，失败项含 envelope identity matches request
- 正常 envelope-new + queue-add 的信封 → merge-check 全部检查通过（新检查 ok）
- legacy 信封（无 baseline）→ merge-check 仍通过（不启用新式检查）
- 真实塔 state-verify：exit 0、tasks=34/envelopes=33、drift=[]
- 真实塔 post-merge：7/7，塔计数/anchor 检查通过
- python tools/towerctl.py spec-coverage 27/27、spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-034 diff --name-only main..HEAD 恰好两个 allowed_paths 文件
