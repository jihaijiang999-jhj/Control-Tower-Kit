# PILOT-011 — 权威状态脏检测：status/startup 报告未提交的权威状态，handoff-activate 提示提交

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-011`

## Scope

- 新增 authority_drift(root)：塔根位于 git 仓内时，报告 primary/、supervision/、ledger/、handoffs/、shared/ 下未提交的改动；不在 git 仓内返回 None
- authority_drift 忽略工具自有输出目录（沿用 TOOL_OWNED_STATE_DIRS：supervision/reviews、supervision/outbox），避免 post-merge 自身产物造成的噪声
- status 输出新增 authority_dirty（list 或 null）与 authority_dirty_count（int 或 null）
- startup 输出新增 authority_dirty_count，口径与 status 一致
- handoff-activate 输出新增 commit_required（bool）：激活写盘后权威状态脏即为 true，并给出可直接执行的提交提示文本
- 不自动 commit：工具只报告，不替人决定提交边界
- 新增 tools/tests/test_authority_drift.py 覆盖以上行为，沿用现有测试的临时塔构造方式

## Allowed paths

- `pilot/worktrees/PILOT-011/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-011/tower-dsh/tools/tests/test_authority_drift.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总用例数 >= 140
- status 输出含 authority_dirty 与 authority_dirty_count 两个字段；干净 git 仓内分别为 [] 与 0
- 在 git 仓内修改 primary/CURRENT_STATE.json 后，status 的 authority_dirty 含该路径且 count >= 1
- 塔根不在 git 仓内时 authority_dirty 为 null、authority_dirty_count 为 null，status 仍 exit 0
- startup 输出含 authority_dirty_count，且与同一状态下 status 的取值一致
- handoff-activate 输出含 commit_required；激活后（状态刚写入且未提交）为 true
- supervision/reviews/ 下的未提交文件不计入 authority_dirty
- ledger/ 与 handoffs/ 下的未提交改动计入 authority_dirty
- 既有子命令的已有输出字段与语义不变；spec-coverage 仍 27/27、gaps 0；spec-lint --strict 仍 6/6
