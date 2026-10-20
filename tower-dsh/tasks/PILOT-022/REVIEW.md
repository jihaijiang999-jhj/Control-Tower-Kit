# PILOT-022 — Independent Checkback

- Reviewer: `subagent:rev-pilot-022`
- Verdict: **PASS**
- At: 2026-10-20T23:49:08+08:00

## Note

AC-1..AC-14 全 PASS（AC-11 计数为 spec 陈旧值，见下）。214 tests OK（main 基线 203）；真实塔实跑 exit 0、tasks=22/envelopes=21、drift=[]、skipped=[]，与 real-run.txt 逐字一致；独立探针用 main 版 towerctl 跑新测试得 failures=12/errors=3，证明新用例有鉴别力；8 份证据 SHA-256 与 spec_sha256 全部独立复算匹配；diff 恰两个 allowed 文件；402 个真实塔文件前后 SHA-256 一致（只读）。偏差：卡写 tasks=21，实为 22（PILOT-022 自身 TASK_NEW/DISPATCH/DELIVER 已入 ledger，冻结时卡内尚未包含自身），record/board/replay 三者一致且 drift 为空，判定为 spec 计数陈旧而非实现缺陷，如实记录不放宽规则。残余：带生命周期的非法信封 id 既不进 drift 也不进 skipped（安全选择：绝不用作路径），已记录。

## Evidence checked

- `tasks/PILOT-022/evidence/towerctl.py` `5f00b1f999707543343ca5d0c515e800ee4999c977dac1a4eab5599664ee8bee`
- `tasks/PILOT-022/evidence/test_state_verify.py` `5a949e5462bab445de9a83e1d4a7bd769dca0a916e7866122073f18edbfb5b8b`
- `tasks/PILOT-022/evidence/test-output.txt` `268eb843ff388c305e921054b66aa87838b74a6cc01b34a5cdc38a623d29194c`
- `tasks/PILOT-022/evidence/real-run.txt` `96bd3ce083171f9e42e83c5f20c88dbf856d65ce8d0848b78f10d7c4c54af10d`
- `tasks/PILOT-022/evidence/real-run-meta.txt` `394887b41eabc978cf89b03f1ad90eb6f7c370e7bd7b2a012f875c84057cbe2e`
- `tasks/PILOT-022/evidence/probe-old-code.txt` `3e90bfe3cf154bea8685d4482af4cf499cce286e113de19c428715574e4f4a48`
- `tasks/PILOT-022/evidence/commit.txt` `0a4387b7cefd466a40e06452e6e8491ae2fafeb080a2ef8e5811a8b58e5583f1`
- `tasks/PILOT-022/evidence/diff.txt` `977c98489e5ee506baed13ef6ff97d93391b8a78c9642bad9287c29b2184416c`
