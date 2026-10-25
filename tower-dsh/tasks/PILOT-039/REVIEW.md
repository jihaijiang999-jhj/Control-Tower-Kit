# PILOT-039 — Independent Checkback

- Reviewer: `subagent:baa3ec9e-499a-4a82-b5d5-41d279b1e51a`
- Verdict: **PASS**
- At: 2026-10-25T13:26:33+08:00

## Note

039 PASS（v2，第二轮）。第一轮 FAIL 的 missing-ledger 旁路已关闭：ledger_precondition_breaks 对 primary/supervision 无条件 verify_ledger_file（缺失/不可读/坏行一律 fail），merge 在 authority 之后、读信封/队列/git 之前 exit 2，队列保持 WAITING、无 MERGE_START/MERGING、ledger 不被重建。复核实测四组全关：configured/required/legacy + legacy 信封 + 删 supervision.jsonl → merge-check 2 / merge 2 / 队列 WAITING / 无 MERGE_START / ledger rows 0；删 primary.jsonl（legacy → chain missing；configured/required → authority gate 先拦）同样 exit 2；新式信封缺 supervision 失败项恰 ["ledger chain intact"]（无同义 pre-merge 项）；干净 legacy/configured merge-check 0。同构：policy 四审计字段逐项篡改 → check 2 + drift authority_policy_mismatch + merge 2；event payload 篡改并重算 hash 仍 drift；并发 3 进程×2 轮 6/6 成功、revision 1..6 唯一递增、无锁/tmp；旧码 A–D 对照（policy 篡改 MERGED、伪造 primary+legacy MERGED、并发 revision 重复、删 supervision+legacy MERGED 且 ledger 重建）全部翻红。证据 12/12 SHA-256+字节数一致、spec 哈希一致、evidence/towerctl.py 与 worktree 字节相同；scope 6 文件（5 allowed + test_merge_pr_mode.py 的 +1 行 fixture，numstat 1 0），按 MAP §6.11 最小可证明补齐且 commit body/commit.txt 已写明前提错误（v2 allowed_paths 未含该文件），无断言改动；亲跑 Ran 363 tests / OK(skipped=1)。真实塔只读：state-verify 39/38 drift []（skipped 2 个 VOID 归档）、authority-check configured+required、verify-ledger 0 error（primary 356/supervision 198）、coverage 27/27、lint 6/6，policy/state/ledger 哈希前后不变。残余（非阻塞）：①v2 acceptance 文字仍写"恰五个 allowed_paths"与实际 6 个不一致（卡面 stale，按 §6.11 记录）；②ledger 截断为 0 字节仍是合法空链（036 已定义空账本 intact，超出"缺失/不可读/坏行"范围）；③authority-require 的 already=true 分支回显请求 decision 而实际不改变；④policy+event 双写并重算整链的 TOFU 残余（policy 的 git 追踪是外部锚）。注：v1 因该阻塞项已按 spec 冻结规则作废归档（tasks/PILOT-039-VOID + pilot/PILOT-039.spec.v1.json）。

## Evidence checked

- `tasks/PILOT-039/evidence/towerctl.py` `31675ca89fc6d695d29d2a2314e617412067fdd8ab6b1f0a64ab818b979744b3`
- `tasks/PILOT-039/evidence/test_authority_hardening.py` `be45b5d482c52bbc002161dfc4d1b776c43421fd6d5152e25f9730f520c04b41`
- `tasks/PILOT-039/evidence/test_state_verify.py` `8423e2f6e6c0339f825fc2482f197a9f4a3086d94103aa1ee66f56030e96c16a`
- `tasks/PILOT-039/evidence/test_coverage.py` `6c4ccb44f4f50d02abd286cde4223b06d5a0da170aaa537b6ad358133ce1cb70`
- `tasks/PILOT-039/evidence/test_gates.py` `78b19d310e673045fbf215d78947fb0ddd1ae5410f5b9e750c68db933ab0a8f1`
- `tasks/PILOT-039/evidence/test_merge_pr_mode.py` `6d637cdd0ae79f1948d22039d1a65dda88548fa19dd2dec3ef1583a14ad5cb2b`
- `tasks/PILOT-039/evidence/test-output.txt` `91d35e8ce329fc737a80832dffee4179c6d6a98436a132d39db49de62d143b4c`
- `tasks/PILOT-039/evidence/authority_hardening_probe.py` `a1af72ac09c73318ac3b99a0009481a055a54b9f0a94455ec99908718a226f27`
- `tasks/PILOT-039/evidence/probe.txt` `7b1d9133fd181f8b304de97e6076f1030f09e07d319493b1fe12fb40236c1135`
- `tasks/PILOT-039/evidence/probe-old-code.txt` `efd562f2b07fc713597adbf10cc93a483c7a25f797c909c084298faae2c9387f`
- `tasks/PILOT-039/evidence/commit.txt` `9611ee82e00f4307be2ba9572482e7ce1cae76bcac7285b9b753741a78f60007`
- `tasks/PILOT-039/evidence/diff.txt` `81ac12d432d96bc048890fc95c0959ac6303cedf67250b592b36a4b6f440cefb`
