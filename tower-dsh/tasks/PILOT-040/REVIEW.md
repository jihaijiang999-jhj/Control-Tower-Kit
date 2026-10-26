# PILOT-040 — Independent Checkback

- Reviewer: `subagent:3ecc3001-a65f-462b-a63d-3d8ee3e1cdd4`
- Verdict: **PASS**
- At: 2026-10-26T12:11:44+08:00

## Note

040 PASS（无阻塞）。空账本守卫已关掉 0 字节截断对 legacy merge 的掩护：configured/required + 手写 envelope + 队列 + 0 字节 supervision.jsonl → merge-check exit 2（失败项 ledger history present，文案含 empty 与工件清单）、merge exit 2、队列 WAITING、无 MERGE_START/MERGING、ledger 仍 0 字节、envelope DRAFT；legacy 塔同夹具保持旧行为（merge 成功，兼容边界已 pin）；fresh configured（无工件）不触发；非空 ledger + 工件不触发；同夹具 state-verify exit 2 且 drift envelope_unbacked/queue_unbacked（审计先行）。authority-require 回显已修：already 请求 D-NEW 实际 D-ORIG → decision=D-ORIG、requested_decision=D-NEW、事件 1 条、policy/ledger 字节不变；repaired 两方向同样以事件为准；首写行为不变。独立复核 12/12 证据 SHA-256+字节数一致、spec 哈希一致、evidence/towerctl.py 与 worktree 字节相同；scope 5 文件（towerctl + 新测试 + 三个既有测试的 §6.11 授权播种：8/0、11/0、10/0，零删除零断言改动，commit body 已写明 allowed_paths 未含这两个文件）；亲跑 Ran 371 tests / OK(skipped=1)。旧码同夹具 merge-check 0、merge MERGED 且重建 ledger（604B，含 MERGE_START），新码 exit 2；旧码 authority-require 回显请求值（bug 已复现）。真实塔只读：state-verify 40/39 drift []（skipped 2 VOID，evidence 317）、authority-check configured+required（13 checks，rev 2）、verify-ledger 0 error（primary 364/supervision 203）、coverage 27/27、lint 6/6、ledger_empty_guard(real)=[]、8 个关键文件哈希前后不变。残余（非阻塞）：①守卫按“可解析 JSON 对象”计事件，截成 {"seq": 1}（11B）可过 039 并绕过守卫（需写 ledger；本质仍是 036 无密钥链残余，建议 041 把计数限定为含非空 type + dict payload 的行）；②仅 merge-ledger 工件时守卫失败但 state-verify ok，文案与审计不一致；③§6.11 播种导致卡面与 allowed_paths/验收文字 stale（5 文件 vs 3），closeout 记录；④evidence 的 probe/test-output 为 UTF-16LE（哈希字节一致，卫生问题）；⑤legacy 塔 primary 清 0 字节仍按 036 放行（卡面明确保持）。

## Evidence checked

- `tasks/PILOT-040/evidence/towerctl.py` `59846ab1c07c7403d4bb1cf509e62e2b32cecafc4d489fc8337f50d7233b4d5e`
- `tasks/PILOT-040/evidence/test_empty_ledger_guard.py` `2a5274db5010796fb2ddac83026f73dfe49c75f0fb498437d4c3a64f6aa457eb`
- `tasks/PILOT-040/evidence/test_authority_hardening.py` `ecf0020a0fcc68b4ca73591a3f500aa016db0c13d87eacba3d6bc245392db0ea`
- `tasks/PILOT-040/evidence/test_authority_required.py` `4f2b3d5780485e0fc1187e27cbc2e4f439ac7b5c993d53d9a40067824d0e3530`
- `tasks/PILOT-040/evidence/test_authority_state.py` `e505468bff086d595c127231b41fcc8b556e6760da0317e6991c3c4494afec6d`
- `tasks/PILOT-040/evidence/test-output.txt` `ba28b6f775aaec6a1b2eb9e48cb327d0445f07accc07377725adb04fa339ed07`
- `tasks/PILOT-040/evidence/empty_ledger_probe.py` `1ab1bf3f700ec1ac2b681a94bebb64e7c156849d8a9077997ae5a7f3900e13b0`
- `tasks/PILOT-040/evidence/probe.txt` `1259f88fd91bef218a3c73451aeca8cf15776f176b9ede2a7726ca0ab4acebe5`
- `tasks/PILOT-040/evidence/probe-old-code.txt` `e25051e34bcc97f2e7c8ad7e2dd925dfb1f4e49834482726169a31a90c01e15c`
- `tasks/PILOT-040/evidence/commit.txt` `92585b04670b04ed280452420c7e39bb1c114f547a3eccd7765d61528c7da356`
- `tasks/PILOT-040/evidence/diff.txt` `a6544db6c8a6937192d61815c3fd856e0ce445d91189f472e9678301d6b3ec27`
- `tasks/PILOT-040/evidence/fixture-seeding.diff` `cbc85a32ad893ecc273571a8576dfa26c8ba24ebc8a7413d73756e869d9f9272`
