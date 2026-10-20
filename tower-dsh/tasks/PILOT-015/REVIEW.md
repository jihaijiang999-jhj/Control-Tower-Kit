# PILOT-015 — Independent Checkback

- Reviewer: `subagent:rev-pilot-015`
- Verdict: **PASS**
- At: 2026-10-20T12:01:40+08:00

## Note

复验 PASS（AC-1..AC-8）。四点重点全部通过：create 无 --json 且唯一 /pull/ 正则；不可执行 gh 目标不卡 MERGING；ff 失败保留 pr_number/remote_merged 且重试仅一次 create；已存在 PR 走 pr view 回退。174 tests OK（常规与空 git 配置）。两点判定：超时只杀直系进程属可接受残余（真实 gh pr checks 不产生长命子进程），但 TOWERCTL_GH 包装器场景需修；check_conclusion 硬编码 success 可接受（仅在 checks exit 0 后写入）。已知偏离（非阻塞，记录在案）：(a) spec 的 gh pr create --json 处方有误，实现按证据改为解析 URL——spec 冻结未改，后续卡需更正该措辞；(b) spec 要求 merge-ledger 同步 check_conclusion，实现仅写入信封，列为后续小修；(c) 证据 ID 重复 E-006 为既有 deliver 缺陷；(d) --check-timeout help 文案未覆盖 create/view/merge。

## Evidence checked

- `tasks/PILOT-015/evidence/towerctl.py` `beaa855b3780f71330522c8d5f7f63c5ea717797c36b0caf8817aa80ae1e0809`
- `tasks/PILOT-015/evidence/test_merge_pr_mode.py` `62b94c6f310b37788abdd858f180f9798663cae80058bd9e88416e012a0b9881`
- `tasks/PILOT-015/evidence/test-output.txt` `bebdc08423dd69f81500a98cfa3a22a7007ceb1aeba1b4dfa9065a3d4a422f72`
- `tasks/PILOT-015/evidence/test-output-no-gitconfig.txt` `de58b8b55f1b84db34785aa204596b7aa167574e62ae6b11be53dca70aa2c43a`
- `tasks/PILOT-015/evidence/commit.txt` `b2b4f547c7be89c0cf0535d7540fa261e36e0e58ac7cd959b3bfe76c2b073f4c`
- `tasks/PILOT-015/evidence/diff.txt` `fd6f3192f4157497ec7b7d0faf82ec09c0fc77d984dae906890624b62b35009e`
