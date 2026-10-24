# PILOT-038 — Independent Checkback

- Reviewer: `subagent:bf7571e7-8da5-4a64-bd41-c9579c9b31f3`
- Verdict: **PASS**
- At: 2026-10-24T20:55:08+08:00

## Note

038 PASS（代码/验收），带一个部署前置：真实塔尚未执行 authority-require，038 的要求在真实塔上还未生效（迁移由 controller 做，reviewer 禁止）。独立复核自建 %TEMP% 夹具复现：require 后 configured/required、恰一条 AUTHORITY_REQUIRED、policy 与 event 同构；非 owner 零写入；重复 require already=true；单侧缺失 repaired=true；037 攻击夹具（删 state/AUTHORITY.json + 移除尾部唯一 AUTHORITY_SET，前缀仍合法）→ verify-ledger 0、authority-check exit 2 required_unconfigured、state-verify 唯一 drift authority_required_unconfigured、merge exit 2、队列 WAITING、无 MERGE_START（main 版工具同夹具：legacy/0/MERGED，已被翻红）；删 policy（事件在）→ policy_missing；policy true 但截 REQ → policy_unbacked；ledger 为目录时 authority-set/authority-require 均 exit 2 单 JSON 无 traceback、恢复后可修；look-alike（"true"/1/0/null）不被当 required，且事件在时 fail closed；state 文件为目录 → fail closed。证据 9/9 SHA-256+字节数一致、evidence/towerctl.py 与 worktree 字节相同、diff.txt 与 git diff 相同；scope 恰 3 allowed_paths；test_state_verify.py 纯追加 +65/-0、test_authority_state.py 未动；亲跑 Ran 341 tests / OK(skipped=1)。真实塔只读：state-verify 38/37 drift []、verify-ledger 0 error（primary 340/supervision 193）、authority-check configured/optional（policy 不存在、无 AUTHORITY_REQUIRED）、spec-coverage 27/27、spec-lint 6/6。残余：038 不是不可删除的事实——删 policy + state + 截掉全部 SET/REQ（合法前缀）仍回 legacy 且 verify-ledger 0；配对只验 presence/极性，不验 policy 字段同构；owner 是字符串非认证；merge 不跑 verify-ledger（空账本前缀不被 merge 抓）。结论：037 的精确假 legacy 路径已关上，038 把门槛从“删一个文件+截一条尾”抬到“删四个工件+截到最早 SET/REQ 之前”。

## Evidence checked

- `tasks/PILOT-038/evidence/towerctl.py` `c1bd64ddaf9381e9cb547255a8091f6c9ed1b001cd6285644b2a2a048118aa7c`
- `tasks/PILOT-038/evidence/test_authority_required.py` `af5df9a379e340afbd724a10912fbf0e7c523bf94d3af8545e1dba85fc868159`
- `tasks/PILOT-038/evidence/test_state_verify.py` `882841387815bf36aaa34969634b7b49dec62b4f6a78972fa164fb061bdaab5a`
- `tasks/PILOT-038/evidence/test-output.txt` `792b32eaf3ceb8269e95df39065cdd2ecaf9d220ce66ed335ebda640a3c30f3e`
- `tasks/PILOT-038/evidence/authority_required_probe.py` `9a15fa12c895e73c2fc4f48b48923b6c5f1c960d6921f137230925fef01400e0`
- `tasks/PILOT-038/evidence/probe.txt` `67ce9395b9902cc6aa59ac9646929541328c0ac3e9e790ce92d75ef8f53d5637`
- `tasks/PILOT-038/evidence/probe-old-code.txt` `07593fbd00ca039f8c2a0247221a4fe9a806579fdf7ac642215c27a61a9e7700`
- `tasks/PILOT-038/evidence/commit.txt` `b58fd13fa6384228f6b2f5ee2c54c17aea1388118103d4c2d6cfe9060394bf78`
- `tasks/PILOT-038/evidence/diff.txt` `2baed36c759013fc537b6c9012c9adf770452d3c536fade9cc32d570cf03a5d1`
