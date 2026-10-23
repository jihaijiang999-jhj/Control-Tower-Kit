# PILOT-036 — 信任边界收口：缺失/不可读 ledger 不再算链 ok、identity 精确比较、ENVELOPE_NEW 绑定 head/task

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-036`

## Scope

- verify_ledger_file：账本文件缺失时记 errors=["ledger missing: ledger/<name>.jsonl"]、exists=false、events=0；读取过程中任何 OSError（含 PermissionError、IsADirectoryError）转成 errors=["ledger unreadable: ledger/<name>.jsonl: <err>"], 不抛 traceback；已存在但为空文件仍算 intact（0 事件、无 error）
- cmd_verify_ledger：缺失/不可读都输出单个 JSON（ok=false、errors 非空）并 exit 2；不得出现 traceback
- envelope_checks 的 "ledger chain intact"：primary 或 supervision 缺失/不可读即失败，detail 以 "<name>: " 前缀给出首条错误（现行为汇总全部错误到 chain_errors，缺失/不可读应进入同一汇总）
- 命令级 identity 精确比较：cmd_merge_check 与 cmd_merge 直接比较 env.get("envelope_id") 与请求 id（不再 str(... or "")），类型不同即命令级失败，错误文案为 "envelope identity matches request: file declares <repr>, request <repr>"；envelope_checks 内部的 identity 比较保持原样（已是精确比较），不得回退成归一化比较
- ENVELOPE_NEW 绑定 head/task：新式信封的 "envelope_new recorded" 检查要求存在一条 ENVELOPE_NEW 事件，其 payload.envelope == 信封 id、payload.task == 信封 task、payload.head == 信封 envelope_head_sha；三者都中时 detail 保持 "ENVELOPE_NEW event present"，完全没有事件时保持 "ENVELOPE_NEW event missing"，事件存在但绑定不符时 detail 必须点明是 task 还是 head 不符
- 新增 tools/tests/test_trust_boundary.py：覆盖缺失账本、不可读账本（把 ledger/<name>.jsonl 换成目录）、空账本仍 intact、非字符串信封 id 的命令级拒绝（含 str() 归一化会误放的对照用例）、ENVELOPE_NEW 绑定不符（换 head / 换 task）阻断 merge-check 与 merge、绑定正确仍通过
- 既有测试仅做夹具补强：tools/tests/test_ledger_chain.py 与 tools/tests/test_ledger_lock_windows.py 的 setUp 各补一个空的 ledger/supervision.jsonl，使"只验 primary 链"的成功路径不再依赖缺失账本；不得删除或放宽任何断言
- 不改 legacy（无 baseline）信封路径、不改 post-merge、不改 queue-add、不改 state-verify 的 wire format

## Allowed paths

- `pilot/worktrees/PILOT-036/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-036/tower-dsh/tools/tests/test_trust_boundary.py`
- `pilot/worktrees/PILOT-036/tower-dsh/tools/tests/test_ledger_chain.py`
- `pilot/worktrees/PILOT-036/tower-dsh/tools/tests/test_ledger_lock_windows.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- treating an existing empty ledger as missing
- changing legacy (no baseline) envelope semantics
- editing the spec in place instead of rebuilding the task card

## Acceptance

- cd pilot/worktrees/PILOT-036/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 300（main 基线 293）
- 缺失账本：造一个除 supervision ledger 外全部合法的塔，verify-ledger --ledger supervision exit 2、ok=false、errors 含 "ledger missing"；merge-check（新式信封）只有 "ledger chain intact" 失败，detail 以 "supervision: ledger missing" 开头
- 不可读账本：把 ledger/primary.jsonl 换成同名目录，verify-ledger --ledger primary exit 2、输出恰一个 JSON、errors 含 "ledger unreadable"、无 traceback；同塔 merge-check 的 "ledger chain intact" detail 以 "primary: ledger unreadable" 开头
- 空账本：缺失用例中 touch 出空 supervision.jsonl 后，verify-ledger exit 0、ok=true（证明缺的是"文件不在"，不是"没有事件"）
- identity 精确比较：把 supervision/envelopes/<ID>.json 的 envelope_id 改成整数字面量（其 str() 等于请求 id），merge-check 与 merge 均 exit 2，errors 是字符串 "envelope identity matches request: ..."（不是 check 字典列表）；同一塔把 id 改回字符串后 identity 检查通过
- ENVELOPE_NEW 绑定：合法塔上把信封记录 envelope_head_sha 换成另一个合法 40 位 sha（或把 ENVELOPE_NEW 事件的 task 换成别的 task），merge-check 失败于 "envelope_new recorded" 且 detail 点明 head/task；merge 在 MERGING 之前阻断（队列条目变 CORRECTION_REQUIRED，无 MERGE_START）；把值改回后该检查通过
- 旧码对照：用 git show main:tower-dsh/tools/towerctl.py 落一份 main 版工具，对同一组夹具复跑——缺失账本 verify-ledger exit 0、目录账本 traceback、整数 id 通过命令级 identity、错 head 的 ENVELOPE_NEW 通过——四项在旧码上全部"不报"，在新码上全部被拒
- 真实塔 state-verify：exit 0、drift=[]、tasks=36、envelopes=35（本卡建 envelope 之前）
- 真实塔 verify-ledger：primary 与 supervision 均 0 error（事件数不少于 316/183）
- python tools/towerctl.py spec-coverage 27/27、python tools/towerctl.py spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-036 diff --name-only main..HEAD 恰好四个 allowed_paths 文件（tower-dsh/tools/towerctl.py、tower-dsh/tools/tests/test_trust_boundary.py、tower-dsh/tools/tests/test_ledger_chain.py、tower-dsh/tools/tests/test_ledger_lock_windows.py）
