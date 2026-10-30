---
schema: tower/profile@1
object: TOWER-DSH
version: 1
updated: 2026-10-30
owner: mac
status: active
---

# PROFILE — TOWER-DSH（对象 0：塔自身）

这是对象层的第一个 PROFILE：对象不是外部产品，而是这座塔自己。它只声明**对象
不变量**——这些事实一旦不成立，塔给出的“完成/可信/可合并”结论就不再成立。
每条事实的 `probe` 都是只读 towerctl 子命令，`profile-check` 在子进程里逐条运行；
任何一条失败即 exit 2，不允许“文档说得好听、代码已经变了”。`expect` 只支持一个
stdout 子串，所以 AUTH 拆成两条：`AUTH` 锁 `required=true`（可选化即失败），
`AUTH-CONF` 锁 `status=configured`。

| id | fact | probe | expect | why |
|---|---|---|---|---|
| AUTH | 合并权威被标记为 required（policy + AUTHORITY_REQUIRED 双半） | authority-check | exit=0; stdout="required": true | required 是“授权不可被静默降级”的开关：一旦变成 optional，删掉标记就能退回 legacy，合并门重新变成字符串。 |
| AUTH-CONF | 合并权威已登记，且与 primary 身份分离 | authority-check | exit=0; stdout="status": "configured" | 只有 configured 才存在可核对的合并权威身份；legacy/required_unconfigured 都意味着“谁可以合并”没有落盘事实。 |
| LEDGER | primary/supervision 账本哈希链完整且可验证 | verify-ledger | exit=0 | 账本是权威事件链；链断则所有完成声明、证据与合并记录都可被静默改写。 |
| STATE | 工作副本与账本重放一致（drift 为空） | state-verify | exit=0 | record/board/queue/envelope 只是账本的工作副本；副本与账本分叉即意味着塔在报告一个不存在的状态。 |
| ARCH | ARCHITECTURE/GATES/INVARIANTS/EVENT_CATALOG 与代码逐条对账 | arch-check | exit=0 | 架构描述必须可证伪；门表或事件目录与代码脱节时，“结构是什么”就变成散文。 |
| CAMPAIGN | 战役目标、在飞卡数与 review_by 合法 | campaign-check | exit=0 | 战役是“为什么做这张卡”的锚；目标失联或 WIP 超限时，卡序不再服务战略。 |
| SHAPE | 相对冻结基线没有新增形状债务 | shape-check | exit=0 | 形状棘轮保证复杂度只降不升；基线漂移会让“小步交付”退化为持续膨胀。 |
| SPEC | 冻结 spec 与工作流文档结构合法（严格模式） | spec-lint --strict | exit=0 | spec 是任务边界的唯一契约；结构不合法时，allowed_paths/验收条件都可被误读。 |
| WHERE | 位置图可由 campaign 与 board 机读渲染 | where --json | exit=0 | 位置是“现在打到哪”的机读答案；不可渲染时路由只能靠人回忆，交接必然失真。 |
| STARTUP | 启动自检可完成并报告塔的真实阶段 | startup | exit=0 | 启动自检是每个会话进入塔的入口；它失败时后续所有命令都建立在未校验的前提上。 |
| WIRING | 接线完整：关键目录、状态与命令入口都存在 | wiring | exit=0 | 接线是把组件变成塔的连接关系；缺线时命令仍能跑，但门禁与证据会落空。 |
