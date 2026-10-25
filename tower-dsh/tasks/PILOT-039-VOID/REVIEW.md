# PILOT-039 — Independent Checkback

- Reviewer: `subagent:baa3ec9e-499a-4a82-b5d5-41d279b1e51a`
- Verdict: **FAIL**
- At: 2026-10-25T12:58:22+08:00

## Note

039 FAIL（阻塞：missing ledger 的 legacy 合并口）。复核自建塔复现：configured/required/legacy 塔 + legacy 信封已入队 + 删 ledger/supervision.jsonl → merge-check exit 0、merge exit 0/MERGED、写 MERGE_START、ledger 重建后 verify-ledger 全绿；legacy 塔删 ledger/primary.jsonl 同样 MERGED。根因：ledger_precondition_breaks 对缺失文件 continue，违反 spec「两条链各跑一次 verify_ledger_file，任一有错即 fail」与 forbidden「chain fails verification 不得 merge」，也违背 036 缺失=错原则。其余通过：9/9 证据哈希与字节数、scope 恰 3 文件、Ran 357 OK(skipped=1)、policy 四审计字段逐项篡改 check 2+drift authority_policy_mismatch+merge 2（event payload 篡改并重算 hash 也会 drift）、require_authority 类型错 fail closed、并发 6/6 revision 1..6 唯一递增且无锁/tmp 残留、锁超时干净 exit 2、旧码 policy 篡改全绿且 MERGED、旧码并发 revision 重复、真实塔只读 39/38 drift [] 且 350/198 0 error、coverage 27/27、lint 6/6。偏离①（merge-check 前置链只对 legacy）行为等价可接受；偏离②（缺失跳过）不可接受。返工方向：missing 必须算错（无条件 verify_ledger_file），并为缺少空 supervision.jsonl 的既有夹具补 touch（test_coverage/test_gates 等），不得放宽断言。因 allowed_paths 需扩到夹具文件，按 spec 冻结规则重建卡：v1 归档为 tasks/PILOT-039-VOID + pilot/PILOT-039.spec.v1.json，v2 重建后重新 dispatch。

## Evidence checked

- `tasks/PILOT-039/evidence/towerctl.py` `a029aa383c68141c0bf7ce32bace015c40f430ce3323a8fded5566b8c05007e8`
- `tasks/PILOT-039/evidence/test_authority_hardening.py` `e1ebd820583033a17a4aa8a3320803e2e76a941fbca7e2d3ba6c9fc7ce46eaf4`
- `tasks/PILOT-039/evidence/test_state_verify.py` `8423e2f6e6c0339f825fc2482f197a9f4a3086d94103aa1ee66f56030e96c16a`
- `tasks/PILOT-039/evidence/test-output.txt` `5f3ee69ee7106af668c2f070cb2ade9e719db80d9c72b06141b1b3e8b79c523b`
- `tasks/PILOT-039/evidence/authority_hardening_probe.py` `3fa3227977fd9ab0894d5094ea43eef459c1f3063d40e4dd326b4d35fc8c02ce`
- `tasks/PILOT-039/evidence/probe.txt` `e2e366def53cb9e64ddccee9339c69735e5f5f225b06c4743508c6be0fcf63b8`
- `tasks/PILOT-039/evidence/probe-old-code.txt` `6aed33aee4026ccc9fe76bfb24a9991328f1476b4bc333c8561183376f24c825`
- `tasks/PILOT-039/evidence/commit.txt` `e7f3ab51de4cb57e6f0a02cb37d011262e297fc8120d88486b289fa39179069e`
- `tasks/PILOT-039/evidence/diff.txt` `6a73e99880692d3e6ae3ea8149297c295572604c226b5488ebb64b9d729230e9`
