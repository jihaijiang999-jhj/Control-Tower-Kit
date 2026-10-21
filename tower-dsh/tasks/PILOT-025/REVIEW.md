# PILOT-025 — Independent Checkback

- Reviewer: `subagent:rev-pilot-025`
- Verdict: **PASS**
- At: 2026-10-22T00:34:53+08:00

## Note

v2 独立复核 PASS。241 tests OK(skipped=1)；五个自建 post-merge fixture 全对：baseline1 通过(ran 1, baseline 1, envelope/review/ledger 均记 tests_count)、baseline2 判红并转 CORRECTION_REQUIRED、legacy 无基线走 tests count present、删测试后 0 tests 判红、坏字节子进程 exit0 且 U+FFFD（main 版则 UnicodeDecodeError，证明解码修复真实）；parse 取最后一次匹配。test_hardening2 只改 4/4→5/5 一行（numstat 1/1，line 508）。13/13 证据哈希匹配，spec_sha256=334f128...匹配 v2；v1 spec 哈希与 VOID record 匹配。scope 恰三文件；456 文件只读快照一致；state-verify drift=[]，VOID 仅进 skipped（预期）。v1→v2 重建被判定必要且可追溯。AC7（真实塔 ran 2, baseline 2, 5/5）按流程留给 merge 后 post-merge；信封须带 tests_baseline=2。残余（不阻塞）：towerctl.py:2463 docstring 仍写 4/4；信封缺 baseline 会静默降级 legacy；tests_count 可能为 null；TEST_COUNT_RE 多 \\b；E-004..013 为 UTF-16LE。

## Evidence checked

- `tasks/PILOT-025/evidence/towerctl.py` `c4f892fe1309c6f5cdf0f66425553d582ed5e407b5b1ffc78f871e7c5519ceee`
- `tasks/PILOT-025/evidence/test_post_merge.py` `1b10e4323de145f2f17b804c13fb7cddf26c794778c73f4a754d4e75b8c9c7cd`
- `tasks/PILOT-025/evidence/test_hardening2.py` `cd82604128fbdcc63f7377ca4d963f908b271d434bd7c2395e9c27c6af21bce5`
- `tasks/PILOT-025/evidence/test-output.txt` `cea8fb3851556c12ed098b5e69e26f8ec3c0c3218150659eeb93235374498d3b`
- `tasks/PILOT-025/evidence/post-merge-checks.txt` `1ebb5436cbc143cf17ca255a04e10df5c8bf23f941e563439443e2f2b57a03d2`
- `tasks/PILOT-025/evidence/parse-probe.txt` `c218cddf043272599022c0266ba6641fb2c98d4f342977e321e79f72b2ffc21e`
- `tasks/PILOT-025/evidence/real-run.txt` `e786822f93efd4bf0584cf4983c8a3816b78b1036085050db40ff89de51dc615`
- `tasks/PILOT-025/evidence/real-spec-coverage.txt` `596fa953b85b1c28fc7d3658113a17c2e31b68512bd85a544b980a6178a9120d`
- `tasks/PILOT-025/evidence/real-spec-lint.txt` `85b54ab102dfc3b86e0eb4bc245e1ff116a83d2d189c9d05bb0ccb2dece2737c`
- `tasks/PILOT-025/evidence/probe-old-code.txt` `29a6ade35e8c4bda314a2075d37ec508de0a112bd7d648320fd2e87cf3fb912a`
- `tasks/PILOT-025/evidence/CONFLICT.md` `c0a9d4423c06b04029fcd85b75d11b299d15d5f06f8fac8e67bd66301692a97b`
- `tasks/PILOT-025/evidence/commit.txt` `48e7ceaa3705d7ac001001e40f38826d55c58c94f83e644f7c9c5f01a4806a77`
- `tasks/PILOT-025/evidence/diff.txt` `08b49a84b6298fc66d528df7f75baf9db8180119bfd1b1f2b623cf90db521236`
