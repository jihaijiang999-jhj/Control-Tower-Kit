# PILOT-019 — Independent Checkback

- Reviewer: `subagent:rev-pilot-019`
- Verdict: **PASS**
- At: 2026-10-20T21:31:25+08:00

## Note

AC-1..AC-8 全 PASS。192 tests OK（含独立空 GIT_CONFIG 复跑）；exit 8 + 任意文本重试成功；exit 1 + 'no checks'/非整短语立即 block 且 calls=1；整短语仍兼容重试；纯失败回归 calls=1。鉴别力已验证：同一探针在 main 版上 exit 8 立即 block、'no checks passed' 被当 pending 重试 36 次到 timeout。CHECKS_PENDING_EXIT=8 与 gh 2.96 文档一致。残余：若 gh 真在失败时返回 8，会被当 pending 重试到 timeout（仍 fail-closed，只延迟与归因变差）；line 2234 的 'already exists' 仍是文本启发式，列为后续改进。

## Evidence checked

- `tasks/PILOT-019/evidence/towerctl.py` `eae10f2939c3bfc83c7c59a90a9792e5857c69b5f054a17e1e1ddbc4da342f9f`
- `tasks/PILOT-019/evidence/test_merge_pr_mode.py` `d38ebed4a65281e198a815cabf40c4c14b4796023e3e208c4a6a650c3e9a2c58`
- `tasks/PILOT-019/evidence/test-output.txt` `653831d131771cb8d7e04cbc40be03d221f8527650322a1cd6abcf3c0b8af113`
- `tasks/PILOT-019/evidence/test-output-no-gitconfig.txt` `a0aa61ce20724e6534ec2858cb0b620ac99ef43ddb940f682929c1a94272418a`
- `tasks/PILOT-019/evidence/commit.txt` `20e04a5dd65cddd7f56258b15d5bf92355b3c8e3e451d765f191e58623fa7e1a`
- `tasks/PILOT-019/evidence/diff.txt` `89b3e1985e22b0a0830939eed711edbd020d26f7555aab5e7c2b9d764deda423`
