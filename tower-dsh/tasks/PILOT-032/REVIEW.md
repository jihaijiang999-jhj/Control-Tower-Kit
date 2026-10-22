# PILOT-032 — Independent Checkback

- Reviewer: `subagent:rev-run-c-032`
- Verdict: **PASS**
- At: 2026-10-23T02:56:33+08:00

## Note

RUN-C 卡 3/3 PASS。281 tests OK(skipped=1)；独立 9 项探针：首次 TASK_NEW(None)、dispatched/reviewed/delivered/rework 重建合法；accepted/closed→TASK_NEW 判红，drift 仅 {kind,target,event,expected,actual}（无 path），expected=None-first 排序且不含 accepted/closed；混合账本只报完成卡重置；ready→TASK_NEW 仍合法（task-new 目录检查兜底）。真实账本 33 个 TASK_NEW = 32×None + 1×dispatched，无 accepted/closed 来源；真实塔 32/31/drift 0。旧码对照恰 3 个完成卡重置测试失败。表比较：仅 TASK_NEW 集合与哨兵守卫变化，其余迁移/折叠/计数/既有 drift 不变，无残留 ANY_STATE。9/9 证据哈希与 spec_sha256 匹配；scope 恰两文件；660 文件只读快照一致。残余（不阻塞）：未来生命周期事件缺表项会被默认放行（建议完整性断言）；关闭卡无正式 reopen 流程（需新 id）；ready→TASK_NEW 未钉测试；卡面 baseline 266 已过期（实际 277）；检测型设计，task-new 本身不拦截。

## Evidence checked

- `tasks/PILOT-032/evidence/towerctl.py` `2fab47d11405bec7121d9fdb921804a7a10fcbd3212ada7db3b43228573d6ff5`
- `tasks/PILOT-032/evidence/test_state_verify.py` `25c32e3bd9ee4204c5983cc5147031380123526e69191017f45c7ac5c8bf31ef`
- `tasks/PILOT-032/evidence/test-output.txt` `6c3434d719723465bc7b8f4ed32dcc2f9f78d7a21c39edd722cc9d30730087ff`
- `tasks/PILOT-032/evidence/rebuild-probe.txt` `b35f1277866b4ca807f2c7d694f19a2567fd810e8f9f6a94e166146a8695eb3f`
- `tasks/PILOT-032/evidence/rebuild_probe.py` `bb289a50a4801bc526c48bda1a69f8d03a0d2d7a3560782c67efd8112d470bd4`
- `tasks/PILOT-032/evidence/real-run.txt` `e920add655fdbdecae0ac8ea786474f73e06db928811cfdd4f9beaa94436087e`
- `tasks/PILOT-032/evidence/probe-old-code.txt` `09d748699ada1f1c527ef469d2f74c8ce9f65630d3ed260cb9bbd8c7953d34d6`
- `tasks/PILOT-032/evidence/commit.txt` `8a3cbb271c2cd7fa81f9dc4a7f5f28a898aab141d5c9bc8c1a715ea3b5fbb181`
- `tasks/PILOT-032/evidence/diff.txt` `cd8f7f97fc12df38b2f1d5bfd9aca13f1b1a721e750622b5f159ea6d39177a49`
