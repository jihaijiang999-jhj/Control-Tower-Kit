# PILOT-024 — Independent Checkback

- Reviewer: `subagent:rev-pilot-024`
- Verdict: **PASS**
- At: 2026-10-21T05:01:36+08:00

## Note

AC-1..AC-6 全 PASS。根套件 Ran 2 tests OK（内层塔套件 Ran 236 / OK skipped=1，阈值 >=8 未改）；run_captured 同时被真实门禁与新回归测试使用，门禁 argv/cwd/returncode/Ran 计数断言逐字未变。独立复现旧策略：真 236 套件在 main 解码策略下 stderr=None、TypeError，reader 线程 UnicodeDecodeError 位置 31994，与 PILOT-023 post-merge 完全一致；新 helper 对 raw 0xbf 返回 str + U+FFFD、无异常；monkeypatch 旧策略下新回归测试失败（非空转）。7 份证据 SHA-256/bytes 全匹配，spec_sha256 匹配；scope 恰一文件；481 文件只读快照一致。结论：该修复闭合 PILOT-023 post-merge 失败。残余（不阻塞）：errors=replace 会掩盖子进程本地化诊断文本；PYTHONIOENCODING 影响所有门禁子进程。

## Evidence checked

- `tasks/PILOT-024/evidence/test_tower_gates.py` `fe1bf5ce1daa3853f9df1266349ec29cc93883db114104771ab0456eaf33bf07`
- `tasks/PILOT-024/evidence/root-test-output.txt` `dc16e1abf2d0bdd1552669ff285ea5efb4977c6aca8377b2db748b5830870262`
- `tasks/PILOT-024/evidence/real-gate-output.txt` `004297138da40528a766b427ed3c390f3229403e7bf9dc4ccfe7e69202535f11`
- `tasks/PILOT-024/evidence/probe-old-code.txt` `e9c5b6588fcd0982a2a8dd19b3a4a96ee650a2e0f194fda5d8a01830ab4ca0c6`
- `tasks/PILOT-024/evidence/weakness-check.txt` `355ec7498a9659351ea544222b13783411db83af27f244c9807dd1dbcd389bba`
- `tasks/PILOT-024/evidence/commit.txt` `a1e7669a377306a8a5437012b48fbb5bf5f8589ff51609fbaa99dda7bbb0cd40`
- `tasks/PILOT-024/evidence/diff.txt` `4af5501ccc032c71f5940d24aec4336ee01a566caecc769ae915f26bc5435d4e`
