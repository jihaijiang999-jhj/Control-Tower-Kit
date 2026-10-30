---
schema: tower/profile@1
object: OBJECT-ID
version: 1
updated: 2026-10-30
owner: mac
status: template
---

# PROFILE — OBJECT-ID（模板）

对象层把“这个系统是什么、哪些不变量不能碰”写成可执行事实：每条事实一个只读
probe，`towerctl profile-check` 逐条运行并比对 `expect`。模板只用于复制结构，
`status: template` 时 `profile-check` 解析并校验结构但**不运行 probe**。

使用时：把 `object` 改成真实对象 id，`status` 改成 `active`，`updated` 改成当天
日期，再用真实事实替换示例行。`probe` 只能取 `profile-check` 白名单里的只读
towerctl 子命令（见 `ARCHITECTURE.md` §4）；`expect` 只支持 `exit=N` 与可选的
`; stdout=子串`；`why` 写“为什么这是对象不变量”，不要写“测试通过”。

| id | fact | probe | expect | why |
|---|---|---|---|---|
| SAMPLE-AUTH | 权威态已配置且标记为 required | authority-check | exit=0; stdout=configured | 没有登记的合并权威时，任何“谁可以合并”的判断都退化为字符串，合并门失去意义。 |
| SAMPLE-WHERE | 当前位置图可渲染 | where --json | exit=0 | 位置是 “现在打到哪” 的唯一机读答案；渲染不出来时，路由只能靠人记忆。 |
