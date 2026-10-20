# PILOT-023 — Independent Checkback

- Reviewer: `subagent:rev-pilot-023`
- Verdict: **PASS**
- At: 2026-10-21T04:37:15+08:00

## Note

复评 PASS（返工后 4b21038）。B1/B2 已闭合：独立 spy 覆盖 os.stat/lstat/open/scandir/realpath/islink/isjunction/exists/io.open/builtins.open，越界证据与越界 spec 同时存在时 touched=[]，drift 仅 evidence_path_escape/spec_path_escape，evidence_checked=1；junction 指向根外同样未触盘。NUL evidence/spec 路径均为 exit 2、单一 JSON、无 traceback（evidence_unreadable/spec_unreadable）。236 tests OK（skipped=1，仅 symlink 权限跳过）；旧码探针 21 failures+4 errors，证明新用例有鉴别力。真实塔 exit 0、tasks=23/envelopes=22、drift=[]、evidence_checked=147（独立复算 147）；8 份证据 SHA-256 与 bytes 全匹配，spec_sha256=8c28fb...匹配；scope 恰两文件；420 文件只读快照一致。残余（不阻塞）：词法前缀大小写敏感（绝对路径仅大小写不同会误报 escape，真实记录均为相对路径）、根内符号链接一律按 escape 保守处理、spec_unreadable 为新 kind 但不削弱既有三类、TOCTOU/hardlink 不在范围。

## Evidence checked

- `tasks/PILOT-023/evidence/towerctl.py` `977b7c26bbd9b8d8d4304b40011e37fef857696a441a64421709dc92d798788b`
- `tasks/PILOT-023/evidence/test_state_verify.py` `143460bb3dbc4d54e6b87108f4c7a078cdac1b39fb068330d42d9f132bbb3397`
- `tasks/PILOT-023/evidence/test-output.txt` `e0468cb8b1b6f508fc969c41403888c7562f6fa66ed8f71596889028b43af0b5`
- `tasks/PILOT-023/evidence/real-run.txt` `580757d7291d807dc1fc363502129094d2286c72875d736e06a98dbb6c4b3dbf`
- `tasks/PILOT-023/evidence/real-run-meta.txt` `54d6052ce5c91d7e339d831f7e26c7cf05f57813b0e8cec4ff32e4255bd97de9`
- `tasks/PILOT-023/evidence/probe-old-code.txt` `a3cc96241b061af8f69b58e6428b09bede205b7b652450320001b07233c4d9f3`
- `tasks/PILOT-023/evidence/commit.txt` `f5e3863c16a8d45c284f9a02d769a2a00534cdc380084801ec730eaf657bfec6`
- `tasks/PILOT-023/evidence/diff.txt` `38b01061037c6cd778d4e25b59d9768d41b728de917efaef63de915c7f94dd8f`
