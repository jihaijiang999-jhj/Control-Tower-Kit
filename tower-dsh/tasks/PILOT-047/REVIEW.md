# PILOT-047 — Independent Checkback

- Reviewer: `subagent:adf9823d-0837-480c-949c-90a6c8707149`
- Verdict: **PASS**
- At: 2026-10-29T12:49:45+08:00

## Note

047 PASS（独立亲跑，88/88 夹具）。14/14 证据哈希+字节数；5 文件 scope；spec 哈希；亲跑 Ran 518 OK(skipped=1)、shape-check exit 0、campaign-check exit 0；position 模型：schema=tower/position@1、index=2/total=6、current/next=047、nodes 顺序=roadmap、枚举 done/active/blocked/planned、all done index=total next=null、current 无 record=active、blocked 列表正确；E8（roadmap 缺失/空/重复/current 不在）与 E9（无 campaign/无 active）均 exit 2 无 Traceback；--json 键排序/枚举/无时间戳/纯 JSON；人视图 7 行含位置条 [✅045][✅046][▶047][ 048][ 049][ 050] 与 位置 2/6 · 下一站 047、为什么/交付/风险/建议；--md 同源；注入 checkback（JSON position + REVIEW.md ## Position）、close（index 推进 3、next 048）、post-merge（成功/失败同一 with_position 行）、status-snapshot（- position: 2/6；无 roadmap 写 -）、brief 2/6（旧码 2/3、无 roadmap 回退 1/1）；无 roadmap 旧夹具无 position 键/段；旧码无 where（invalid choice 2）；真实塔只读 47/45 drift []、authority configured+required、ledger 0（425/233）、coverage 27/27、lint 6/6、787 文件哈希不变；status 真实性：副本重跑 snapshot/index 字节相同。关键判断：index 取 done 计数（=2）与验收/brief/status 一致，spec 文字“第一个非 done 的 1-based”会得 3，属 spec 笔误——**需在 closeout 或 048 记 errata：index=done 节点数，非偏移量**；E8 leniency（campaign-check 对缺 roadmap 保持 legacy 绿、where 严格 E8）判可接受。残余（非阻塞）：①同一条 status 并存 campaign 2/3（task_forces）与 position 2/6（roadmap）两个分母，建议下一卡统一或改名；②where 对无法解析的 campaign 报 E9 而非 E1（干净但误导）；③skipped 枚举不可达；④wip 全塔口径 vs campaign limit；⑤campaign 正文“卡序 045→046”已过时（按 spec 保留）；⑥post-merge 成功路径仅静态确认同一 with_position 行。合并后 main 的 where 应为 3/6（047 已 close），next=048。

## Evidence checked

- `tasks/PILOT-047/evidence/towerctl.py` `2369e49b5996040063b3a1259c65ce1902c153e8133fe9092403899a2f7fa276`
- `tasks/PILOT-047/evidence/test_position.py` `26f5a06360d3f2f6db262e6be5ec0ddf5047fea19d8ed2797e5bc45510a191e9`
- `tasks/PILOT-047/evidence/C-2026-Q4-01.md` `e5e0ca3d092a0dc05f56fa3c159c5c1dde14c5d5e03385e52fc5d496b2267e30`
- `tasks/PILOT-047/evidence/2026-10-29.md` `e39d3623e438c67bf139481158305d5282e0410baab25d3333d797e315142ffc`
- `tasks/PILOT-047/evidence/index.json` `5ed69a00f41baa9a13d73d75d45c9a0c17c9a4ac3b421505cc5c3bce58a53475`
- `tasks/PILOT-047/evidence/test-output.txt` `90725e1fafca30271be3ce03c83c0ba873de120f9f1f03ff1d718adb50fe99ef`
- `tasks/PILOT-047/evidence/position_probe.py` `558a22a1247a9506889a7be6bdbfc8df48bf0dfed3380a49a087595f6d5499ec`
- `tasks/PILOT-047/evidence/probe.txt` `8900ba232b9429da83193ba59008623d27a641d486c0e169354c92bddd797f3b`
- `tasks/PILOT-047/evidence/probe-old-code.txt` `ba9e1e909c8b3dfc24a6b72c36d44ddcfdb6a8e0e0e6e6cc52b8cf8ea01da3b4`
- `tasks/PILOT-047/evidence/commit.txt` `c5492665d5349314447b3d57952ce46fd7eadf2be67cfb6f29cfa307eb7ce42a`
- `tasks/PILOT-047/evidence/diff.txt` `35c0b1c2e3f188f0f24986408058e2b782dde35eb7f10d3ca5cb6dc91821373a`
- `tasks/PILOT-047/evidence/where-sample.txt` `bb72f8448ebc33e7ebe656839135323a3e859a61d7d01204724d1589b01e3366`
- `tasks/PILOT-047/evidence/where-json.json` `01eb6f919bbbc64ac876b9e919c795eeb2d90bd9870b1cec8328a427d434e01d`
- `tasks/PILOT-047/evidence/shape-report.txt` `39a0578e0642472d36dbb4b0da31dd5af3b917d0823d7b64806746c7cf5ecfc8`

## Structure review（五问）

1. 新抽象是否有 ≥2 个使用点？
2. 有无死代码/永久开关？
3. 有无 ≥15 行重复？
4. 测试是否只镜像实现？
5. 新增 TODO 是否有卡号？

reviewer 回答：未提供（044 起建议填写，暂不阻塞）
