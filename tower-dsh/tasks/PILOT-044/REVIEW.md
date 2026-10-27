# PILOT-044 — Independent Checkback

- Reviewer: `subagent:862dbc9b-d3a8-4a2a-93ce-3d4a7a8ad9a6`
- Verdict: **PASS**
- At: 2026-10-28T01:49:02+08:00

## Note

044 第二轮复核：代码与夹具全部 PASS（方法/嵌套盲区已关上：新 91 行 Big.huge → 2、outer.inner → 2、基线 120→130 → 2、键为限定名；baseline 自关已关上：worktree 篡改/删除 → 2、塔根缺失 → 2、有债塔根干净 → 2 零写入、干净 → 0 checked、parse error → 2 无 traceback；Ran 441 OK；证据 12/12；基线 1114 条、可字节复现、不含 044）。复核唯一 FAIL 点是“044 自身交付是否经过新门”的记录缺失：真实塔根 pre-merge 没有 state/SHAPE-BASELINE.json，而新门要求塔根基线，故 044 在 01:30 的交付只能用 main 版工具（043 代码，无 shape 门）完成——这是**引入新门时的一次性 bootstrap**（与 041 同类：新门会拒绝“引入它自己的那个 commit”，因为基线由该 commit 引入），不是绕过既有门。按复核给出的修法 1 记录该例外：一次性、不追认、不回填；staging/夹具已独立证明新门在忠实塔上生效（塔根缺基线 → 2；塔根有基线、worktree 干净 → 0；worktree 篡改/删除基线 → 2；worktree 有债 → 2 零写入）；044 merge 后 main 即拥有 state/SHAPE-BASELINE.json，之后所有 deliver 必须走新门（本卡不提供 --force/环境变量绕过）。非阻塞残余：①skip 条件“塔根与 worktree 都无 state/ 目录”在宽 allowed_paths 下可被利用（先删两侧 state/ 再 deliver；真实塔 authority-check 会 2，但 deliver 不调用它）——045 收紧为显式 fixture 标记或要求 tower state 存在；②baseline-summary 的 functions total 1067 标签错误，实际 1114 条（285 module 条目 + 829 dotted）；③spec 的 43/42 是 VOID 假设下的 stale 文字，实际 44/42（dispatch 已入账）；④test-output 含 cp936 字节、baseline-summary 为 UTF-16LE（哈希有效，卫生问题）；⑤嵌套长函数会同时报父与子（noisy 但安全）。

## Evidence checked

- `tasks/PILOT-044/evidence/shape_probe.py` `b83334124533e88a78eefdc2063e6de4e779ca95383f930ec4c7cd2282667a82`
- `tasks/PILOT-044/evidence/towerctl.py` `e68eca96cacf9911120b48e623eb9351a566589c9bb7cf7959f8508951dfcedd`
- `tasks/PILOT-044/evidence/test_shape_check.py` `27d9bbc9c9ce34db2d97d051e3249d9f0e65071abef6d49ee76760071d2247fe`
- `tasks/PILOT-044/evidence/SHAPE-BASELINE.json` `88f0fa0e444a96cc602e1603ffcef726d6024d6c78b8e08cf2975629d1ab4ad9`
- `tasks/PILOT-044/evidence/test-output.txt` `0ee0d5954f542ce63f8b78c2a2d205e9a7e9fc2d4d77dddebf1b7cf3140f7e63`
- `tasks/PILOT-044/evidence/probe.txt` `c370d7d085f95d0a73f0c26258262e2ef39c75faf7df6b3eb2b24cc0835e516d`
- `tasks/PILOT-044/evidence/deliver-baseline-probe.txt` `a003d7478c9e20498de12f35a5fb0615e4bece34437ea45478427f6e5b9a1c83`
- `tasks/PILOT-044/evidence/probe-old-code.txt` `b88462a5281a275189a4ae44ad90f0dcb331983fe52f0d25c69e9d7c4dd5b926`
- `tasks/PILOT-044/evidence/baseline-summary.txt` `58a21bca24ea2c0aead82a909540c302bd4296c5b19dcad036c0e378729727e6`
- `tasks/PILOT-044/evidence/commit.txt` `38be7de4662fddd99dca8f77e73d08a947f16e92a52a89b48a01ea402c741270`
- `tasks/PILOT-044/evidence/diff.txt` `be7934722759a5265c358dce20de5ddd42f1614ca76aacc7f6aac1f737106b33`
- `tasks/PILOT-044/evidence/baseline-from-main.json` `88f0fa0e444a96cc602e1603ffcef726d6024d6c78b8e08cf2975629d1ab4ad9`
