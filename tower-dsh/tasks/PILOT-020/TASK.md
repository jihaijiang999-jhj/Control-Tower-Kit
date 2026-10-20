# PILOT-020 — CI action 升级到 checkout@v7 / setup-python@v7，消除 Node 20 弃用告警

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-020`

## Scope

- tower-gate.yml 的 actions/checkout 从 v4 升到 v7，actions/setup-python 从 v5 升到 v7
- 保持 runs-on windows-latest、python-version 3.12、working-directory tower-dsh、五步顺序不变
- 同步更新 test_ci_gate.py 中对 action 版本的断言（常量），其余断言不动
- 合并后在 GitHub 上确认 CI 仍全绿且不再出现 Node.js 20 弃用注解

## Allowed paths

- `pilot/worktrees/PILOT-020/.github/workflows/tower-gate.yml`
- `pilot/worktrees/PILOT-020/tower-dsh/tools/tests/test_ci_gate.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- changing other tests or towerctl.py

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总数 >= 193
- workflow 中 checkout 为 @v7、setup-python 为 @v7，且不再出现 @v4/@v5
- window-latest、python-version "3.12"、working-directory tower-dsh、五条 run 步骤与顺序均不变
- spec-coverage 27/27、tool_gaps 空；spec-lint --strict 6/6
- git diff --name-only main..HEAD 恰好两个 allowed 文件
