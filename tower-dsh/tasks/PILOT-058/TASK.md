# PILOT-058 — 结构化 REVIEW：head/base 绑定 + expected-head merge

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-058`

## Scope

- checkback：新增 --head（默认 worktree HEAD）、--base（默认 record.dispatch.base_sha）、可重复 --finding；写 tasks/<id>/REVIEW.json：{schema:tower/review@1, task, reviewer, verdict, head, base, scope, findings[], note, at}；PASS/FAIL 都写
- merge-check：REVIEW.json 必须存在；verdict=PASS；review.head == envelope.implementation_head_sha；review.base == record.dispatch.base_sha（若 record 有）；缺失/不一致 exit 2 并指出 stale
- merge（--mode pr）：调用 gh pr merge 时加 --match-head-commit <envelope implementation_head_sha>；head 不匹配则 fail，不走无 head 约束的合并
- envelope-new：不改写 REVIEW；若 REVIEW.head != 新 envelope head，后续 merge-check 必须报 stale（不自动接受旧 PASS）
- 旧卡兼容：057 之前已合并的卡无 REVIEW.json 不回溯；057 起新卡必须写；已有 REVIEW.json 的旧 fixture 不受影响
- 测试覆盖：checkback 写 JSON（PASS/FAIL）；merge-check 缺失/PASS/FAIL/head 不同/base 不同；merge 命令含 --match-head-commit；head 改变后重 checkback 覆盖为新 head
- 不改 036–057 的授权/账本/双塔/信封/合并/记录层/ID 语义；只收紧 review 与 merge

## Allowed paths

- `pilot/worktrees/PILOT-058/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-058/tower-dsh/tools/tests/test_review_gate.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- accepting a REVIEW whose head != envelope head
- merging without --match-head-commit
- weakening existing review/merge gates

## Acceptance

- cd pilot/worktrees/PILOT-058/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 646 + 新增用例数（main 基线 646）
- checkback PASS 写 REVIEW.json，head=worktree HEAD，base=dispatch base_sha，scope/findings/verdict/reviewer/at 齐全；FAIL 也写 verdict=FAIL
- merge-check：无 REVIEW → exit 2；verdict FAIL → exit 2；review.head != envelope head → exit 2（stale）；head/base 一致 → 0
- merge --mode pr 的 gh 参数含 `--match-head-commit <envelope head>`；head 不匹配时 fail 且不产生 MERGED
- envelope head 改变后旧 REVIEW 不再 PASS；重新 checkback 写新 head 后 merge-check 0
- 真实塔 state-verify drift []；真塔 tasks=57/envelopes=56（058 建卡后），建信封后 57/57
- git -C pilot/worktrees/PILOT-058 diff --name-only main..HEAD 恰 2 个 allowed_paths
