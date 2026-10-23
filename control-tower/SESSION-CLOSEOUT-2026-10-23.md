# SESSION-CLOSEOUT — 2026-10-23（PILOT-022 … PILOT-035）

- Controller：`ctl-yingxian-qa-001`（primary）
- 窗口起点：`PILOT-021` 刚闭环（21 任务 / 21 信封，203 tests）
- 窗口终点：`PILOT-035` 闭环（35 任务 / 35 信封，293 tests）
- 收官时权威值：`state-verify` → `tasks=35, envelopes=35, drift=[], evidence_checked=264`；
  `verify-ledger` → primary 316 / supervision 183，0 error；`authority_dirty_count=0`；工作树干净。
- 收官时 CI：run `39929889654` **success**（3m29s）。

## 1. 本窗口交付（14 张卡）

| 卡 | 一句话 | Merge |
|---|---|---|
| 022 | 坏文件算 drift、输出 skipped、board 期望值取重放值 | PR #7 `6a920a5` |
| 023 | 证据完整性：SHA-256/字节数/spec 哈希，越界路径不触盘 | PR #8 `a88388b`（假红→024 修复后重试） |
| 024 | post-merge 解码修复：PYTHONIOENCODING + errors=replace | PR #9 `c4fb58f` |
| 025 | 测试计数门：解析 `Ran N tests`，baseline 入信封 | PR #10 `f265847` |
| 026 | 塔套件计数入闸（`tower_tests_baseline`） | PR #11 `e73f1f5` |
| 027 | 测试运行器：TMP 指向仓内 `.test-tmp`，附复跑清单 | PR #12 `223b10b` |
| 028 | 状态迁移合法性：跳步/乱序记 `illegal_transition` | PR #13 `188f122` |
| 029 | baseline 必填：`envelope-new` 强制两字段 | PR #14 `ef72400` |
| 030 | `queue-add` 也强制 baseline（堵手写入队） | PR #15 `aa88f76` |
| 031 | baseline 单调：不得低于 ledger 已验证最大值 | PR #16 `c9a7da6` |
| 032 | 完成卡禁止静默重建（`TASK_NEW` 收紧） | PR #17 `da5a25c` |
| 033 | 无事件信封/队列条目显形；merge 要求 `QUEUE_ADD` | PR #18 `eb8f03b` |
| 034 | 合并门自验：链完整 + `ENVELOPE_NEW` + 身份绑定 | PR #19 `7f122b8` |
| 035 | 半写修复：`queue-add` 补缺失 `QUEUE_ADD` | PR #20 `a7e429d` |

测试演进：203 → 214 → 232 → 236 → 241 → 246 → 252 → 261 → 266 → 271 → 277 → 281 → 287 → 291 → 293。

## 2. 本窗口的三个真实教训

1. **假红是门禁缺陷，不是实现缺陷**：023 的 post-merge 因 cp936 子进程输出被严格 UTF-8 解码而崩溃（`0xbf` at 31994），024 修的是门禁自己的解码器。判例：失败信号必须来自被测对象。
2. **卡面与验收冲突时先修卡**：025 v1 的 `allowed_paths` 漏列 `test_hardening2.py`，按卡面执行必然红或越界；v1 归档（`tasks/PILOT-025-VOID` + `spec.v1.json`），v2 重建。判例：作废要留痕，不能原地改 spec。
3. **同一个自伤犯了两次**：RUN-B 与 RUN-C 首次 post-merge 都因“预批准 spec 还 untracked”判工作树脏；RUN-D 改成 spec 随章程一起入库后不再复现。判例：预批准物必须先入库。

## 3. 收官时仍开着的口（下一窗口输入）

- **信任边界（建议 036）**：缺失/不可读 ledger 仍算链 ok；命令级 identity 用 `str()` 比较；`ENVELOPE_NEW` 只绑 id 不绑 head/task。
- **legacy 降级**：无 baseline 的旧信封仍可绕过新式合并检查（有意兼容，但也是绕过）。
- **链的性质**：unkeyed SHA-256，可重算伪造；边界是“只有 towerctl 写 + 锁 + verify-ledger 可审计”。
- **∅5 对象层**：仍为空——塔能证明“发生过什么”，不能推导“被迭代系统必须成立什么”。
- **∅6 趋势/熔断、∅7 授权态单写者、∅8 判例集、∅9 包号防呆**：均未做。
- **真实项目 pilot / 分支保护**：仍只有玩具项目与 owner 直推（`enforce_admins=false`）。

## 4. 复跑与验证

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py state-verify          # 35/35, drift [], evidence_checked 264
python -B tools/run_tests.py                   # Ran 293 / OK (skipped=1)
python tools/towerctl.py verify-ledger         # 316/183, 0 error
```

CI 历史：PR #7…#20 全绿；main 最近 run `39929889654` success。

## 5. 交接提示

- 状态（`primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`）是权威；本文件只是窗口摘要。
- 新窗口读序：`TOWER.md` → `START-HERE.md` → `primary/CURRENT_STATE.json` → `primary/TASK_BOARD.json`
  → `supervision/MERGE_QUEUE.json` → `control-tower/MAP.md`（§6.9–§6.15）→ 本文件。
- 继续造卡时沿用批授权：一次批准一批 spec，固定卡序，硬停清单 + 预算；merge 以
  `--role supervisor` 且 supervisor ≠ primary；状态提交只在 envelope 之后。
