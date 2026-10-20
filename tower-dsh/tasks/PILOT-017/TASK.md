# PILOT-017 — 权威状态检测补齐 tasks/ 与 pilot/，并把目录集合变成可测试的常量

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-017`

## Scope

- AUTHORITY_STATE_DIRS 从 primary/supervision/ledger/handoffs/shared 扩展到包含 tasks 与 pilot
- pilot 下被 gitignore 的 pilot/repo、pilot/worktrees 不应出现在 drift 里（git 自然忽略，需测试证明）
- status/startup 的 authority_dirty 计数覆盖新增目录，语义不变（null 仍表示不在 git 仓）
- 新增测试：tasks/<id>/record.json 未提交时计入；pilot/<ID>.spec.json 未提交时计入；worktree/repo 被忽略；干净仓仍为 []
- 既有测试断言零修改

## Allowed paths

- `pilot/worktrees/PILOT-017/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-017/tower-dsh/tools/tests/test_authority_drift.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- changing other tests

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总数 >= 182
- 临时仓内修改 tasks/<id>/record.json 后 status.authority_dirty 含该路径
- 临时仓内新增未提交的 pilot/PILOT-999.spec.json 后 authority_dirty 含该路径
- pilot/repo 或 pilot/worktrees 下的未跟踪文件不出现在 authority_dirty（被 .gitignore 覆盖时）
- 干净仓仍 [] / 0；非 git 仓仍 null / null 且 exit 0
- spec-coverage 27/27、tool_gaps 空；spec-lint --strict 6/6
- git diff --name-only main..HEAD 恰好两个 allowed 文件
