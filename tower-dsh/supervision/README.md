# Supervision Tower — Phase 2 ACTIVE

本目录是 BI 双塔模式在 tower-dsh 的落地：**独立验收 + 串行合并 + 合并后验证**。

## 单一事实来源

- `CURRENT_STATE.json` — 监督塔状态、supervisor id、下一动作
- `MERGE_QUEUE.json` — 唯一串行合并队列
- `envelopes/<id>.json` — 合并信封记录（implementation head A / envelope head B）
- `registries/merge-ledger.json` — 不可覆盖的合并审计账本
- `reviews/<id>-post-merge.txt` — 合并后测试输出
- `outbox/corrections/` — 纠正单

## 规则

1. 主塔只能提交信封，不能 merge；
2. 监督塔独占 `MERGE_QUEUE.json`；
3. 同一时刻只允许一个 `MERGING`；
4. 合并前必须通过：作者 ≠ 合并批准者、B 的父提交是 A、B 只改信封路径、base 是 A 的祖先、证据哈希有效、review PASS；
5. `MERGED` 不是完成态，必须 `POST_MERGE_VERIFIED`；
6. 生产轨仍然 `no_access`。

## 命令

```powershell
python tools/towerctl.py supervision-init
python tools/towerctl.py supervision-status
python tools/towerctl.py envelope-new --task PILOT-001 --file <path>
python tools/towerctl.py queue-add --envelope ENV-PILOT-001
python tools/towerctl.py merge-check --envelope ENV-PILOT-001
python tools/towerctl.py merge --envelope ENV-PILOT-001 --role supervisor --supervisor sup-phase2-pilot
python tools/towerctl.py post-merge --envelope ENV-PILOT-001 --result PASS
```
