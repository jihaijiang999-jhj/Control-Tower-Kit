# PILOT-037 — Independent Checkback

- Reviewer: `subagent:50413a27-baf7-4c93-876d-f183fe168d6b`
- Verdict: **PASS**
- At: 2026-10-24T18:46:51+08:00

## Note

037 PASS（第二轮）。上一轮 3 个阻断项全部实测关闭：authority-check 由 5 字段升级为 9 字段（含 set_by/decision/set_at/note）+ tower_id 绑定（AUTHORITY_ABSENT 哨兵区分缺失/null/空串/单边出现）；revision 严格 type is int>=1，true/1.0/1/-1 全拒，--decision 空串/空白拒绝且零写入；state/AUTHORITY.json 为目录时 authority-set exit 2 单 JSON、无 traceback、0 事件、无 tmp 残留。新增链校验：event 存在即跑 verify_ledger_file(primary)，伪造 AUTHORITY_SET（seq/prev 对、hash 错）→ authority-check exit 2 `primary ledger chain broken`，且 legacy 信封 merge 被拦（队列 WAITING、无 MERGE_START；旧码同夹具实测 MERGED）。回归全过：happy/三种拒绝零写入/merge_authority 篡改/删文件 missing/文件无事件 unbacked/configured rogue 拒绝/pinned 过身份门/legacy merge-check 0/修复 revision 单调；旧码 A/B/C/D 对照独立复现。证据 10/10 SHA-256+字节数一致、spec 哈希一致、evidence/towerctl.py 与 worktree 字节相同、diff.txt 与 git diff 相同；scope 恰 4 allowed_paths；亲跑 Ran 328 tests / OK(skipped=1)。真实塔只读：state-verify 37/36 drift []（skipped 2：authority legacy + PILOT-025-VOID）、verify-ledger 0 error（primary 331/53 legacy）、spec-coverage 27/27、spec-lint 6/6、state/AUTHORITY.json 仍不存在。非阻塞残余（记录在案）：①假 legacy——删掉 primary 尾部唯一 AUTHORITY_SET（前缀仍是合法链）+ 用悬空 junction 顶替 state/AUTHORITY.json，可回到 legacy 并让 rogue merge 通过（需写 ledger/state，属 036 tamper-evident 威胁模型；修法是塔级 authority_required 标记或截止日关闭 legacy merge）；②authority-set 的 ledger append 失败（ledger 为目录）仍会 traceback（state 文件已写，merge 仍 fail closed）；③并发 authority-set 无跨锁（16 次双写 5 次重复 revision）；④链无密钥可重算、merge_authority 未强制等于当前 supervision.id、--by 非认证、legacy 兼容口在 backfill 前仍开。结论：configured 路径已从“任意字符串”变为“登记 supervisor + 文件/账本双锚 + 链校验”，是实质进步而非不可绕过身份系统。

## Evidence checked

- `tasks/PILOT-037/evidence/towerctl.py` `c9170f149b34927e23147cda19e6a7c53b620bb098af21aa3721a9fc065c8999`
- `tasks/PILOT-037/evidence/test_authority_state.py` `59b27fdcfab84cd74bb8eb83c64dc39d6065d1ea6bdf26449f638f2a2f1c14c5`
- `tasks/PILOT-037/evidence/test_state_verify.py` `e1692cbe0a7fa7de323aa231104e3e4c4858c67f4fa81b67fb656a02a48e740d`
- `tasks/PILOT-037/evidence/test_authority_drift.py` `8b1a3d5bbe0d9b80366bc32b60390feb3421507cbe1c97226bb74dc6870ef43a`
- `tasks/PILOT-037/evidence/test-output.txt` `9b4c6cee3e49073ec22c4287a47641562702d6dda44654505d6aaac0b0de4db9`
- `tasks/PILOT-037/evidence/authority_probe.py` `6746fea162af4eb0e524d3e1ef98eb4252f12a55c8fe80b194eedd1bf0ddeb39`
- `tasks/PILOT-037/evidence/probe.txt` `2be6de6546cf8fc6ac4a0781ef7b0056b28ebf8e871fe61fbff18f4163f6a19f`
- `tasks/PILOT-037/evidence/probe-old-code.txt` `548642a6ed69e36360711643c9d9f75add85ed7aa6762dd04d0ae3a850cf37f3`
- `tasks/PILOT-037/evidence/commit.txt` `b4e5ab970bd7ca3a667050e4882eec43b10cdaddfd63158f2e449ae30f397d7e`
- `tasks/PILOT-037/evidence/diff.txt` `03d327e32014e9d849dd939889d48ada806edd1ec1cdbf34a8d92af200c3e2e3`
