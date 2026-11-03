# PILOT-069 — superseded by PILOT-070

**状态**：delivered，未 review、未 envelope、未 merge；由 `PILOT-070` 取代。

## 原因

069 的 `base_ahead_paths` 仍以当前 `HEAD`（merge 时即 base `main`）为基准：

```text
HEAD == origin/main
→ merge-base(HEAD, origin/main) == origin/main
→ base-ahead = []
→ 审计 admin 永不触发
```

`PILOT-070` 改为：

```text
merge-base(envelope.implementation_head_sha, origin/main)..origin/main
```

即 implementation 分叉点之后 base 新增的内容。

## 处置

- 不 merge 069、不补 envelope、不伪造 verified；
- 070 完成后 069 记录保留为 superseded；
- 069 的 751 tests 与 merge-base 显式化仍作为 070 的参考，不进入 main。

## 边界

- 本文件不是 envelope，不是 merge 记录；
- 069 的代码分支 `pilot/PILOT-069` 保留，不删除。
