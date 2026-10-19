# Handoffs — project-handoff v2.1

本目录存放 tower-dsh 的 v2.1 交接包。

## 三原则

1. **交出塔台写包** — 最懂当前状态的人写包。
2. **整包重生成** — 不做增量修补；旧包保留为轨迹。
3. **真相源指针化** — 只给“读什么、在哪、下一步”，不复制项目文档。

## 包结构

```text
handoffs/<package-id>/
├─ HANDOFF.md       # §0 / §0a / §1–§7
├─ SELF-CHECK.md    # 交出前自查（全 [x]）
├─ package.json     # 包身份、文件哈希、state 快照、status
├─ CLAIM.json       # 接收方 claim
├─ RECEIPT.md       # 接收方首验回执
├─ ACCEPTANCE.json  # 交出方接受
└─ ACTIVATION.json  # 接收方激活为新 controller
```

状态机：

```text
PREPARED → READY_FOR_RECEIVER → RECEIVED → ACCEPTED → ACTIVE
```

## 命令

```powershell
python tools/towerctl.py handoff-new --package HANDOFF-PILOT-001
python tools/towerctl.py handoff-check --package HANDOFF-PILOT-001
python tools/towerctl.py handoff-claim --package HANDOFF-PILOT-001 --controller ctl-phase3-receiver-001
python tools/towerctl.py handoff-receipt --package HANDOFF-PILOT-001 --controller ctl-phase3-receiver-001
python tools/towerctl.py handoff-accept --package HANDOFF-PILOT-001 --controller ctl-phase3-receiver-001
python tools/towerctl.py handoff-activate --package HANDOFF-PILOT-001 --controller ctl-phase3-receiver-001
python tools/towerctl.py handoff-status
```

## 纪律

- 接续自检只读；凭据零回显；
- 不认预填结论；任何 §0 漂移如实上报；
- 交出方在 `accept` 后停写 primary state；
- 接收方在 `activate` 后才成为新 controller；
- 四闸仍归 owner。
