# 手法图谱与细节层改造 — 进度总结与交接（2026-10-02）

> **2026-10-02 更新**：④a 已由接续会话（GPT-6）完成并通过全部技术门槛，当前候选 `runs/ATLAS-HOUSE-v0.2/`（SHA-256 `05b58a77…`）；④b 视觉评审已由主线完成（结论见 §5 末尾）。
> **口径以 `reports/TECHNIQUE_ATLAS_IMPLEMENTATION.md` 为准**：17 类（非 18）、14 主源已拆 11（非 9）、对照卡 19 张；本文 §2 的旧数字作废。该报告即项目详尽总报告 v1。

> 写给接手 AI（或额度恢复后的主线）。读完本文 + `reports/TECHNIQUE_ATLAS_STUDY.md` 即可开工。
> 项目总交接见根目录 `AGENTS.md`；本文是 2026-10 手法图谱工作的专项交接。

## 0. 一句话现状

**手法学习阶段（①②③）已全部完成并沉淀为库与文档；细节层改造（④）刚开工**——库件组装引擎的首栋实现任务（agent-12）因 5 小时额度中断，设计规格完整保留在本文 §5，可直接续做。

## 1. 项目目标与核心理念（用户原话校准过）

- 终态：用户给需求 → agent 产出**发散创造**的建筑，符合风格 + 符合建筑技法 + 符合用户技法审美。巴黎是首个验证案例。
- 核心理念：**调试棒冻结状态 + 小方块全构造**——每个细节在方块状态层面显式处理（薄窗面门叶、单向墙肢、强制楼梯转角），任何视角都有构造、有进深、有写实感；反对"笼统表达"（挖洞贴框）。
- 全部构件都要有处理决策（含"此面不可见从简"的显式声明）；转角是独立设计问题。
- 反例校准：`巴黎建筑修改版/` 小房子群（含转角房子）**不合格**（一面贴片三面毛坯、屋顶是壳），只作反例，不是手法源。
- 游戏内验收只能用户本人做，一切 `game_acceptance=NOT_RUN`，系统不得代填。

## 2. 已完成工作（①②③，全量验收通过）

### ① 全源普查（`runs/TECHNIQUE-ATLAS-v0.1/`）
- 123 个 .schem → 80 独立源（`_incoming_schematics/` 43 件全是重复）；36 栋建筑级 × 7 视角共 288 张渲染零失败。
- 数据：`source_inventory.json`（尺寸/垂直材料剖面/街面方向/转角判定/状态指纹）；摘要 `SURVEY.md`。工具 `tools/atlas_survey.py`（幂等）。

### ② 逐源元素级拆解（8 批 84 件，入 `knowledge/library-v4/atlas-techniques/`）
每件含 `source-crop.schem`、`detail.schem`（清洗：只显式 chain→iron_chain 改名，门叶/楼梯/连接全保留）、`record.json`（v3 schema 全字段）、`registry.json`、`previews/`（7 视角，全部目检过）。索引 `index-*.json` × 8。

| 批 | 件数 | 报告（runs/TECHNIQUE-ATLAS-v0.1/） | 要点 |
|---|---|---|---|
| 素材2 转角 | 6 | DECOMPOSE-building2-corner.md | 圆弧阶梯逼近法、雪层磨砂橱窗、穹顶铜壳 |
| 街区1 | 17 | DECOMPOSE-street1.md | 转角塔亭四段、四层窗面三明治、蘑菇块烟囱墙、山花、内院 |
| 街区4 | 16 | DECOMPOSE-street4.md | 船头非对称收头、圆角两级半径、彩色店面×3、M 形双脊 |
| 街墙 5/6/7 | 10 | DECOMPOSE-streetwalls.md | 店面语汇体系、6 层橡木薄窗面、立面壳实证 |
| 素材1 市政 | 12 | DECOMPOSE-building1.md | 角亭纪念化、巨柱、链条线脚、双屋顶制度 |
| 素材5+7 | 8 | DECOMPOSE-b5b7.md | L 形凹角（纠偏切角情报）、拱窗拱环前挑法、钟亭 |
| 素材6 府邸 | 11 | DECOMPOSE-building6.md | 柱廊圆柱（2×2 墙冻结连接）、双层立面、内院全素负发现 |
| 店面补裁 | 4 | DECOMPOSE-shopfronts-extra.md | 45° 斜面店面（facing 按踏步二选一）、矿石货架灯 |

加上 `library-v3/reference-techniques/`（25 件，街区3+素材2 正面，此前已审计），**图谱共 109 件、258 种基础方块**。

### ③ 跨源对照研究（已完成，两个产物）
- **对照卡**：`runs/TECHNIQUE-ATLAS-v0.1/sheets/`（18 类 × 109 件同尺度并排 + `_index.png` + `manifest.json`），工具 `tools/atlas_sheets.py`。
- **研究报告**：`paris-builder/reports/TECHNIQUE_ATLAS_STUDY.md` —— 跨源规律（薄窗面三明治/转角五族/店面语汇/老虎窗双排制/烟囱成组收头/檐口齿饰/阳台绕角/柱廊双层/屋顶肌理）、**调试棒手法总表**、**手法选择矩阵**（形态类 × 元素）、负发现 6 条、对生成器的 6 条要求。**④ 的选件依据全在这份文件里。**

### 另：竖向原型（早期验证，已被④取代）
`runs/PART-PROTO-v0.1/`（tools/build_part_prototype.py）：s3 件组装的 23×49 立面——窗楼层工艺达标，证明"库件组装"路线成立；屋顶因 roof-section 件夹带污染源未修完（中断）。仅作证据保留。

## 3. 手法认知精华（30 秒版；详见 STUDY）

- **窗面 = 三明治**：外层百叶/栏 → 门叶薄窗面（两列 facing 相对、全 half=lower）→ 玻璃背衬 → 深色内衬（多达 6 层）。
- **转角五族**：切角 / 圆弧（45° 对角阶梯逼近）/ 船头（非对称收头）/ 角亭纪念化 / L 形凹角。按地块与形态类选择。
- **屋顶成套**：曼萨德剖面 + 坡面肌理杂混（单一深色壳=死刑）+ 双排老虎窗（颊板材料编码等级）+ 烟囱组（花盆/铁砧收头）+ 脊饰 + 檐口齿饰（绊线钩/链条）。
- **店面**：橱窗/竖梃/招牌带(y4-5)/雨棚/门槛五要素 + 真假交替（真空气壁龛 vs 假窗面）+ 彩色木作。
- **开间服从件**：节距=件宽+墙墩宽，手法决定开间（反转现行 facade.py 顺序）。

## 4. 环境操作手册

- Windows + Git Bash；`cd paris-builder && PYTHONPATH=src`；`python -X utf8`（或 PYTHONUTF8=1）。
- 渲染：`python -m paris_builder.preview3d <schem> --out <dir>`（资产已缓存 `assets/cache/minecraft-1.21.11`）。街面视角：outside=south/+z 的件看 back/axonometric_back，north/-z 看 front 系。
- 测试：`python -m unittest discover -s tests -p "test_*.py"`（272 项 + 既有 5 跳过；**必须 discover -s tests**，否则 tests 包名被 ultralytics 抢走）。
- 校验：`load_schematic(p).validation()`；`technique_library.verify_stamp_audit(read, audit)`。
- 纪律：源素材只读；knowledge/ 与 runs/ 在 gitignore；knowledge 已有目录（v1/v2/v3）不得修改，新件入 library-v4；不用 `| head` 截断 python 输出；文件 IO 显式 utf-8。

## 5. 进行中：④ 库件组装引擎与首栋（中断点，接手直接续）

**任务**（agent-12 中断，其上下文可 `Agent(resume="agent-12", prompt="continue")` 恢复；或按本规格重做）：

新模块 `src/paris_builder/atlas_assembly.py` + CLI `tools/build_atlas_house.py`；`technique_library.py` 加 V4 索引（唯一允许的 src 修改点）。

**首栋 = 街区1 语汇的 C 类转角公寓**（同源件保证协调）：
1. 转角在西北角（街面=北 -z、西 -x）：st1-corner-turret-base/shaft/cap 竖向叠放（塔亭自带北/西两面）。
2. 竖向分层按各件 record 的源 y 区间：st1-base-arcade/base-entry（两翼基座拱廊）→ st1-window-bay-noble（贵族层）→ st1-window-bay-standard ×2 → st1-balcony-band → st1-cornice → 屋顶。
3. 横向：节距 4/5 交替（4、5、5、4），半墙墩自动咬合；每翼 4~6 开间，两翼可不等长。
4. 朝向：st1 件 outside=south/+z → 北面 stamp 用 turns=2，西面 turns=1 或 3。**先小测试场景验证旋转约定再铺开**。
5. 内芯 smooth_sandstone 实体填充（先填后 stamp）；东南两面共墙素面（显式决策，参照素材2 先例）。
6. 屋顶：st1-roof-section 横铺两翼（注意转向）→ st1-dormer-lower（坡脚）+ st1-dormer-upper（坡折上）按 4~6 间距 → st1-chimney-group ×2 屋脊 → 凸出体处用 st1-dormer-pavilion（深颊板）。
7. 排除 7 件含 create 模组壁柱的 st1 件（record 的 compatible_vanilla=false），用 vanilla 件替代。
8. 产物 `runs/ATLAS-HOUSE-v0.1/`：schem、assembly.json、previews、ASSEMBLY.md；校验 PASS + stamp 审计 + 确定性；测试全绿。

**验收标准（主线目测用）**：对照 `参考图/` 与用户的转角作品集基准——窗面三明治可读、阳台带绕角、屋顶成套（肌理+双排老虎窗+烟囱组+脊饰）、共墙是显式素面、无"贴片感"。

## 6. ④ 后续路线（首栋合格后）

1. **引擎泛化**：形态类 × 元素矩阵选件（STUDY §4）；C 类其余转角族（圆弧 b2/st4、切角 b7 系）；D 类街墙（st5/6/7 店面带+薄窗面）；A/B 类（b1/b6）。
2. **跨源混编规则**：材料族协调约束（砂岩系可混、深色市政系慎混）；等级编码变奏（颊板材料/窗高分级/招牌带颜色）。
3. **接入主流水线**：atlas_assembly 挂进 design.build（新 detail_profile）或替换 technique.py 的符号画法；门禁加"街面开口实测""屋顶成套检查"（architectural_conformance 扩展）。
4. **街段生成**：城市层接三层系统（已知待办），共享楼层线/檐口线 + 逐地块变参数。
5. **STATE-LAB 游戏验收**（用户）：770 件与图谱件的冻结状态白名单终验——大规模装配前的必要闸门。
6. **素材3/4 补拆**（府邸类第二源）、街区6 玩家头店等遗留裁件（清单在各 DECOMPOSE 报告）。

## 7. 给接手 AI 的开工清单

1. 读本报告 + `reports/TECHNIQUE_ATLAS_STUDY.md`（§4/§6 是选件依据）。
2. 跑测试确认环境：`python -m unittest discover -s tests -p "test_*.py"`。
3. 续④：`Agent(resume="agent-12", prompt="continue")` 或按 §5 规格重建；渲染出来**必须自己看图**（项目铁律：每次生成后逐视角目检再写分析）。
4. 不合格 → 改装配逻辑/换件 → 重渲；合格 → 更新本文档与 `AGENTS.md` 状态行，向用户请求验收。
5. 任何"完成了"的汇报必须附证据（渲染路径、校验输出、stamp 审计）；`game_acceptance` 永远 PENDING 等用户。
