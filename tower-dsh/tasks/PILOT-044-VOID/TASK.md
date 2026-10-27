# PILOT-044 — 形状预算 ratchet：shape-check（只判新增债务）+ REVIEW Structure 五问

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-044`

## Scope

- 新增 towerctl shape-check：扫描塔根 tools/*.py 与 tools/tests/*.py（跳过 __pycache__），按基线做 ratchet——新函数 >80 行或 >12 分支 → error；基线内函数超过基线值（变长/分支增加）→ error；基线内函数未超过 → 放行；新文件 >600 行 → error；新出现 ≥15 行重复块（去空白/注释后按 15 行窗口哈希）→ error；新出现未使用 import → error；全部通过 exit 0
- shape-check --write-baseline：把当前扫描结果写入 state/SHAPE-BASELINE.json（schema tower/shape-baseline@1；files→{lines,functions:{name:{lines,branches}}}；unused_imports；duplicate_blocks 的 sha256 列表；键排序、无时间戳，两次运行字节相同）；--write-baseline 不与其他检查混用（写入即 exit 0）
- shape-check 默认读 state/SHAPE-BASELINE.json；基线缺失时 exit 2 并提示先 --write-baseline（不静默跳过）
- deliver 接入：范围门通过后、复制证据前，对 worktree 的 tools/ 跑同一 ratchet（基线取 worktree 的 state/SHAPE-BASELINE.json；worktree 无 tools/*.py 或基线缺失 → 跳过并在输出注明 shape_check="skipped"；有基线且发现新增债务 → exit 2、零写入）；成功输出增加 shape_checked=true|false
- checkback 增加可选 --structure <text>：REVIEW.md 固定包含 “## Structure review（五问）” 区块，逐条列出——(1) 新抽象是否有 ≥2 个使用点？(2) 有无死代码/永久开关？(3) 有无 ≥15 行重复？(4) 测试是否只镜像实现？(5) 新增 TODO 是否有卡号？——并把 --structure 文本作为“reviewer 回答”；未提供则写“未提供（044 起建议填写，暂不阻塞）”；record.review.structure 记录该文本
- 新增 tools/tests/test_shape_check.py：新 90 行函数 → exit 2；基线内 120 行函数不报；基线内函数变 130 行 → exit 2；新 700 行文件 → exit 2；新未使用 import → exit 2；新 15 行重复块 → exit 2；--write-baseline 两次字节相同；基线缺失 → exit 2；deliver 对有新增债务的 worktree → exit 2 且零写入，无债务 → 0 且 shape_checked=true；checkback --structure → REVIEW.md 含五问与回答
- 生成并提交 state/SHAPE-BASELINE.json（基于 042 合并后的 main，不包含 044 自己的改动），使 044 自身新增函数全部 ≤80 行/≤12 分支（dogfooding）
- 真实塔验证：worktree 新工具 shape-check exit 0、authority-check exit 0、state-verify drift []；建信封前 tasks=43/envelopes=42，建信封后 43/43；merge 前置链与空账本守卫仍通过
- 不改 036–043 的信任边界/授权/前置链/空账本/范围门/completion/base_sha 语义；不引入第三方依赖；不手写 ledger；CI workflow 的接线留给 045（workflow 在仓库根，allowed_paths 映射暂不支持，属已知边界）

## Allowed paths

- `pilot/worktrees/PILOT-044/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-044/tower-dsh/tools/tests/test_shape_check.py`
- `pilot/worktrees/PILOT-044/tower-dsh/state/SHAPE-BASELINE.json`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- hand-editing state/AUTHORITY.json, shared/AUTHORITY_POLICY.json or ledger/*.jsonl
- silently skipping shape-check when the baseline exists
- weakening thresholds or baselining 044's own new functions to make them pass
- adding a third-party linter/coverage dependency

## Acceptance

- cd pilot/worktrees/PILOT-044/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 419 + 新增用例数（main 基线 419）
- shape-check 在真实塔 exit 0；--write-baseline 两次输出字节相同；删除基线后 shape-check exit 2 并提示写入
- 夹具：新 90 行函数 → exit 2；基线内 120 行函数 → 0；基线内函数 120→130 → exit 2；新 700 行文件 → 2；新未使用 import → 2；新 15 行重复块 → 2
- deliver：worktree 有新增长函数 → exit 2、零写入；无新增债务 → 0 且输出 shape_checked=true；无 tools/ 或无基线的夹具 → shape_check=skipped（既有 deliver 测试全绿）
- checkback --structure '…' → REVIEW.md 含 “Structure review” 五问与回答，record.review.structure 为该文本；不传 --structure 时 REVIEW.md 仍含五问、回答为“未提供”
- 旧码对照：main 版工具对新长函数夹具 deliver exit 0（无 shape 门）、新码 exit 2；main 版无 shape-check 命令。证据写进 scratch/probe-old-code.txt
- 真实塔：worktree 新工具 shape-check exit 0、authority-check exit 0（configured+required）、state-verify drift []；建信封前 tasks=43/envelopes=42，建信封后 43/43；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-044 diff --name-only main..HEAD 恰三个 allowed_paths（towerctl.py、test_shape_check.py、state/SHAPE-BASELINE.json）
