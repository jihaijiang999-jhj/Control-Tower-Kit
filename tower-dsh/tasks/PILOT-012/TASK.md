# PILOT-012 — 把验证搬到服务端：GitHub Actions 门禁 workflow + CODEOWNERS + 自测

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-012`

## Scope

- 新增 .github/workflows/tower-gate.yml：触发 pull_request、push 到 main、workflow_dispatch
- 运行环境固定 windows-latest + Python 3.12（本塔唯一已验证环境），不使用第三方 action 以外的依赖
- workflow 依次执行：全量单元测试、spec-lint --strict、spec-coverage、verify-ledger、status（status 只记录 authority_dirty 不判红）
- 所有 towerctl 步骤在 tower-dsh 工作目录下执行（working-directory）
- 新增 .github/CODEOWNERS，把仓库默认 owner 指向 mac 的 GitHub 账号，为将来的 required review 铺路
- 新增 tower-dsh/tools/tests/test_ci_gate.py：把 workflow 与 CODEOWNERS 的关键内容断言固化成回归测试
- 不修改 towerctl.py，不修改任何既有测试，不引入网络依赖

## Allowed paths

- `pilot/worktrees/PILOT-012/.github/workflows/tower-gate.yml`
- `pilot/worktrees/PILOT-012/.github/CODEOWNERS`
- `pilot/worktrees/PILOT-012/tower-dsh/tools/tests/test_ci_gate.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- changing towerctl.py or existing tests

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总用例数 >= 150
- .github/workflows/tower-gate.yml 存在，且包含 pull_request、push、main、windows-latest、3.12 五个关键标识
- workflow 包含 unittest discover -s tools/tests、spec-lint --strict、spec-coverage、verify-ledger 四条命令
- workflow 中所有 towerctl 与测试命令都在 working-directory: tower-dsh 下执行（或显式 cd）
- .github/CODEOWNERS 存在且包含 @jihaijiang999-jhj
- 新增的 test_ci_gate.py 不访问网络、不依赖真实 GitHub，只读仓库内文件
- spec-coverage 仍 27/27、tool_gaps 为空；spec-lint --strict 仍 6/6 通过
- git diff --name-only main..HEAD 恰好是三个 allowed 文件
