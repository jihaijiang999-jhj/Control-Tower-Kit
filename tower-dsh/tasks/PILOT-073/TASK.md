# PILOT-073 — spec/campaign 入 state/docs + 直接 admin 合并后的 envelope 恢复

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-073`

## Scope

- base-sync state-only 增加 `pilot/*.spec.json`、`command/campaigns/**`（tower 前缀内）；tools/arch/EVENT_CATALOG/其它 pilot 仍 code
- envelope-recover --envelope --merge-commit --reason --by：仅 pinned supervisor；源 WAITING/CORRECTION_REQUIRED；merge_commit 必须可解析、在 origin/main 且 implementation 是其祖先/父；拒绝未合并/错 commit/非 supervisor
- 成功：append MERGE（payload merge_commit/recovered=true/by/reason）、envelope.status=MERGED、queue MERGED；不写 POST_MERGE_VERIFIED
- test：state/campaign 分类 admin；tools 仍 2；WAITING+已合并→recover 0 + MERGE 1 条 + state-verify 0；未合并/错 commit/非 supervisor/重复 → 2 零写入
- 073 自身审计 admin；合并后恢复 071、post-merge 9/9、task-supersede 069、11/11
- 不改 058/059/060/065/070

## Allowed paths

- `pilot/worktrees/PILOT-073/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-073/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-073/tower-dsh/tools/tests/test_envelope_recover.py`
- `pilot/worktrees/PILOT-073/tower-dsh/tools/tests/test_base_sync.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- recovering a commit not in origin/main
- writing POST_MERGE_VERIFIED
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-073/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 770 + 新增用例数（main 基线 770）
- state-only 分类：pilot/*.spec.json、command/campaigns/** 可 flag admin；tools/arch 仍 code
- envelope-recover：已合并 WAITING→MERGED + 1 条 MERGE + 审计；未合并/错 commit/非 supervisor/重复 2 零写入
- 073 自身审计 admin 合并；071 recover 后 post-merge 9/9；069 superseded；where 11/11
- 真实塔 73/70 drift []；arch 18；profile 11/0；shape 0
