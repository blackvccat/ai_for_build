# Atelier 生成器：造型能力方向设计（2026-09-26）

针对用户指出的三件事——**屋顶/立面/店铺都不太对**、**agent deepseek 在立面几何阶段没被调用**、
**可以用方块属性与冻结更新手法做造型**——给出一套有依赖关系、每步可验收的方向。

## 0. 流程主线（用户确认，本方向以此为准）

用户定义的流程是**三步**：

1. **几何外观**：agent 理解用户需求后，**先生成对应的几何外观**；这一步用
   **调试棒手法**（方块状态属性）把体量、坡面、檐口、转角这些"形"直接做出来；
2. **细节**：在几何外观之上再细化窗户等一切所需细节；
3. **输出**：导出、验证，交用户在游戏内验收。

现状与这条流程有三处不符：

| 差距 | 事实 | 位置 |
|---|---|---|
| **① agent 无法表达几何** | 模型产出的 `framework_candidates[].parameters` 被硬校验**只允许 `bay_pitch` / `roof_height` / `entrance_fraction` 三个标量**，出现其它键直接 `raise ValueError`。模型能理解需求（`confirmed_brief`、`architectural_contract` 都产出了），却**没有词汇把几何意图说出来**，几何外观因此完全由固定模板决定 | `atelier_workflow.prepare_framework_contract()` |
| **② 几何没用调试棒手法** | 几何由手写构建器用**整块方块**堆出：屋顶是逐格 `put(ROOF)` 抬升的阶梯平台，檐口是一排整块，老虎窗是一个整块盒子。stairs / slab / wall / pane 的状态属性**一处未用** | `haussmann_reference.build_corner()`、`house._mansard()` |
| **③ 几何与细节未分离** | 体量、开洞、窗套、店面、阳台、檐口、房间**交错在同一个循环**里，靠 `tier >= 1/2/3` 分叉；几何外观无法独立评审，细节也无法独立迭代 | 同上 |

**因此第一步的改造重点是"给 agent 一套几何词汇 + 让几何用状态方块实现"，而不是继续修手写几何。**

### 0a. 输入侧：提示词之外还有现实参考图（用户补充）

用户提供的输入**不只是提示词，还可能包含现实参考图**。查证结果：参考图的通路在
"理解意图"和"设计规划"两处是通的，一到**"几何外观"与"验收"就断了**——而这两步恰恰最需要它。

| 环节 | 参考图可见 | 证据 |
|---|---|---|
| 上传与保存 | ✓ | `save_reference()`：≤2 张、单张 ≤2 MB 的 PNG/JPEG，存 `agent-sessions/<id>/` |
| 多模态分析 | ✓ | `inspect_agent_references()` → `MultimodalClient.complete(..., images=paths)`，产出 `reference_analysis.observations`，按 `image_hashes` 缓存 |
| 意图分类 | ✓ | `classify_turn(..., reference_analysis=...)` |
| 设计规划 | ✓ | `plan_turn(..., reference_notes)`（参考条目 + `visual_observation`） |
| **几何外观规划** | ✗ | `prepare_framework_contract()` 的 payload 只有 `conversation / brief / intent`；而 `conversation` 按 `kind in ('user','assistant','plan')` 过滤，**`reference_analysis` 被滤掉** |
| **视觉评审** | ✗ | `agent_review()` 的 `data['references']` 来自 `summary()`，只有项目自带的 5 张标准对照图，**用户上传的参考图不在其中** |

**结论：现实参考图观察不到几何规划，也进不了评审——这正是"agent 对提示词生成对应几何外观"
做不到的第二个原因**（第一个原因是 §0 的差距①：几何词汇只有三个标量）。

## 0b. 一句话根因

`reference_haussmann` profile 走的是**手写构建器** `haussmann_reference.build()/build_corner()`，
它**绕过了结构/立面/技法三层**。后果是三重的：

1. `technique.py` 那 10 种**带方块状态**的技法（含连接状态、线脚、店面、栏杆）对它**全部不可用**；
2. `house.py` 的 `Structure / Wall / Level` 抽象（`point/inner/bands`、墙角色）也用不上，
   于是屋顶、檐口、老虎窗、阳台、店铺只能**手工堆整块方块**；
3. 这一步一旦写下，任何造型改进都只能**再写一遍手写几何**，无法被复用、测试或让 agent 修。

这与 AGENTS.md 已记录的"城市层自带一份街面构图代码、尚未改用三层系统"是**同一类断层**，
只是长在 reference profile 上。**屋顶平、立面薄、店铺素，都是这一个根因的不同表现。**

## 1. 总方向：风格无关的形制系统，"先形制后细节"

**系统不只为巴黎建筑服务**：日式、中式以及后续其它风格都要能长出来。因此"先形制后细节"
不只是先后顺序，而是**分层归属**：

- **形制（风格无关的骨架）**：平面轮廓、竖向分段、屋顶形制、开间柱网、转角处理、挑出关系。
  这一层是**跨风格可复用、可对比、可单测**的——巴黎的"芒萨尔 + 老虎窗 + 连续阳台带"、
  日式的"切妻/入母屋 + 深挑檐 + 缘侧"、中式的"台基-屋身-斗拱-反宇屋顶"，说的是**同一套字段**。
- **细节（风格特有的肉）**：窗型、门、栏杆、装饰件、材料与色彩。每个风格一套，互不通用。

当前架构与这个定位的差距：**风格是写死在名字和语汇里的，没有风格维度这一层**——
`haussmann_reference.py`（连模块名都写着风格）、`house.FORMS` 的 `street_house / court_palace`、
`facade.SCHEMES` 的 `haussmann_apartment / palace_front`、`technique.py` 的
`rustication / pilaster / quoins / cresting` 几乎全是欧洲古典语汇，
`roof='mansard'` 更是硬编码在 `street_house()` 的默认参数里。
新增一个风格目前只能**再写一个手写构建器**。

### 1.1 形制层要抽象的六个维度（同一套字段，三种风格）

| 形制维度 | 巴黎豪斯曼 | 日式町屋 | 中式院落 |
|---|---|---|---|
| 平面 | 连续街墙、单进深地块 | 鳗鱼床式细长平面 | 合院、多进院落 |
| 竖向分段 | 基座 / 夹层 / 贵族层 / 标准层 / 阁楼 | 土间 / 座敷 / 小屋组 | 台基 / 屋身 / 斗拱层 / 屋顶 |
| 屋顶形制 | `mansard` 陡坡 + 老虎窗 + 烟囱 | `kirizuma`/`irimoya` + 大挑檐 + 瓦葺 | `yingshan`/`xieshan`/`wudian` + 反宇起翘 |
| 开间柱网 | 5 开间、2 格宽窗 | 格子户、面阔 2–3 间 | 面阔 3–5 间 × 进深 2–3 间 |
| 转角 | 直角 / 切角 | 深出檐转角 | 翼角起翘 |
| 挑出关系 | 檐口线脚、阳台带 | 缘侧、庇 | 斗拱、飞椽 |

**这张表就是"形制 spec"的字段来源**——`roof.type` 是枚举（`mansard` / `kirizuma` / `yingshan` …），
而不是某个风格的专名写死。

### 1.2 库的组织：形制库与细节库都按风格分开

```
knowledge/forms/<style>/     形制预设（平面/分段/屋顶/开间/转角/挑出）
knowledge/details/<style>/   细节库（窗/门/栏杆/装饰/材料）
knowledge/styles/<style>.json 现实原型层（现有 paris_haussmann_v0.1.json 是第一个）
```

**新增一个风格 = 加一套形制预设 + 一套细节库**，而不是写一个新的手写构建器。
巴黎现有的 v3 源样本技法（薄窗面、上层阳台带、檐口、老虎窗、烟囱、厚基座、壁柱）
属于**细节库**，应当从构建器里抽出、归到 `knowledge/details/paris/`。

### 1.3 agent 在这套结构里的位置

agent 的工作是**把需求证据翻译成形制**：

```
提示词 + 现实参考图
   → [参考图多模态观察]          （已有，但没接进形制环节）
   → [风格判定 + 形制 spec]        ← agent 产出，用 §1.1 的字段
   → [调试棒手法实现形制]          ← 状态方块，冻结写入
   → [细节层按风格填充]            ← 第二步
   → 输出
```

这样换风格时，**agent 的推理方式不变**（还是"看证据 → 定形制 → 选细节"），
变的只是形制预设与细节库。这也是"先形制后细节"最终要买到的东西。

### 1.4 与 §2 工作面的关系

§2 的工作面照旧，但归属重排：**A（架构收敛）**要顺带把风格维度建起来；
**B（屋顶形制）**是形制层的第一个试点（也最适合，因为屋顶是风格最强的标识）；
**C（立面）/ D（店铺）**属细节层，且**必须先在巴黎上验证，再用同一接口验证日式/中式各一个最小样例**，
否则无法证明形制层真的风格无关。

## 1b. 原总方向（保留其技术判断）

**把 reference profile 收敛回三层系统**：让"造型"由**技法层**产出，而不是由构建器手写几何。
reference 目前的价值（v3 源样本的技法翻译：`s3-window-bay / s3-upper-balcony / s3-cornice /
s3-dormer / s3-chimney / s3-roof-section / b2-base / b2-pilaster`）应当**升格为技法库条目**，
而不是写死在构建器里。这样：

- 城市层、reference profile、通用路径**共用同一套造型语汇**；
- 方块属性手法天然可用（technique 层本来就是写状态的）；
- 造型问题变成**可单测、可对比渲染、可让 agent 修复**的模块问题。

## 2. 五个工作面

### A. 架构收敛（地基，其余各项的前提）

| 编号 | 内容 | 产出 |
|---|---|---|
| A1 | 把 v3 源样本技法从 `haussmann_reference` 里**抽出为 `technique.py` 条目**（薄窗面 iron_door `half=lower`、上层阳台带、檐口退距、老虎窗、烟囱收头、厚基座、层间壁柱），签名统一为 `(scene, wall, opening/spec)` | 技法库 10 → 17+ |
| A2 | `corner_house` 改走 `design.build()` 通用路径：`house.corner_house()` 出 `Structure/Wall` → `facade.compose(wall, levels, spec, rng, role)` 构图 → `_cut_opening` 开洞 → `technique.*` 施加 | reference 不再手写几何 |
| A3 | `build_reference()` 退化为**薄适配器**（只负责选技法组合与参数），几何全部来自 A2 | 两条路径合一 |

**验收**：同一 plan（corner_house / pitch 5 / ent .5 / roof 7 / tier 3）在迁移前后各渲染一次，
逐视角对比；`tests/` 全绿；`design.matrix()` 正交性仍成立（7 形式 × 5 方案）。

### B. 屋顶形制（用户第一个指出的问题，收益最大）

现状：`_corner_rise()` 的 `profile(d)` 在 `d=2..4` **完全不升**（5,5,5），28 格跨度只升 6 格 →
读成"边缘矮台阶 + 中间大平台"；每格 `put(ROOF)` 一个整方块；老虎窗从 `top+1` 起搭 4 格深盒子，
而坡面在 4 格深处已升到 `top+5`，**两者穿插错位**。

| 编号 | 手法 | 冻结状态要点 |
|---|---|---|
| B1 | 芒萨尔下段陡坡：`deepslate_tile_stairs` 逐层内收，`facing` 朝外 | `half=bottom`，逐格显式写 facing |
| B2 | 上段缓坡收脊：`slab` + `stairs`，脊线用 `ROOF_RIDGE` | `type=top/bottom` 显式 |
| B3 | 檐口挑出：`stairs` 倒挂 + 转角 `shape=outer_left/outer_right` | `half=top`，**转角 shape 必须按相邻格算** |
| B4 | 老虎窗：`slab` 侧壁 + `glass_pane`（连接）+ `stairs` 顶 + `trapdoor` 收边，**按坡面 rise 定位** | pane 写四向连接 |
| B5 | 烟囱：`slab`/`stairs` 收头 + `bars` 烟道帽 | 底部按屋面 rise 落座 |

**关键设计**：转角楼是**两个街面各有檐口**，所以屋顶不能沿用"沿 z 双坡 + 东西山墙"，
必须沿两个街面都收檐（现用的四坡方向是对的，要修的是**坡度曲线与手法**）。

**验收**：与 `参考图/标准_巴黎建筑素材2_外立面_轴测.png` 同视角对比，屋顶必须读出**坡面 + 檐口阴影线 + 老虎窗凸出**；
新增测试：屋顶剖面单调性（不允许连续 ≥2 格不升）、老虎窗包围盒与坡面相交检查。

### C. 立面比例与层次

现状：窗宽 2 格、高 4~6 格（1:2~1:3），开间 5 格 → 窗占 40%；只有一块玻璃 + 四面窗套，无窗楣窗台挑出。

| 编号 | 内容 |
|---|---|
| C1 | 窗组宽度：窗 2 格 + 两侧各 1 格窗套 = 视觉 4 格，占开间 5 格的 80%；或直接窗宽 3 格 |
| C2 | 窗楣/窗台用 `slab`、`stairs` 挑出 1 格，形成阴影线（现在窗台只是平铺 slab） |
| C3 | 层线用 `stairs` 做线脚（现在只是一条 slab） |
| C4 | 贵族层窗加高、顶层窗压低、阁楼层只留老虎窗——**逐层窗型表**取代当前 6/5/4/3 的粗略分级 |

**验收**：正视图与 `标准_巴黎建筑素材2_外立面_正视.png` 同尺度并排；新增测试：窗高宽比落在设定区间。

### D. 店铺与基座

现状：框架阶段底层是一排等宽洞（tier 0 无细节，属阶段边界）；细化阶段有连续橱窗带但缺层次。

| 编号 | 内容 |
|---|---|
| D1 | **框架阶段就给出节奏**：橱窗宽开间 + 窄门 + 石墩的分组，而不是等宽洞（洞口节奏属框架层定义） |
| D2 | 雨棚：`stairs` 挑出 + `iron_bars` 支架（细化阶段） |
| D3 | 橱窗分格：`glass_pane` 连接状态做竖梃与横档 |
| D4 | 招牌：`sign band` 之上加 `lantern`／`bars` 招牌架；门头加 `stairs` 门套 |
| D5 | 门槛石与基座：`slab`/`stairs` 做勒脚线脚，`polished_andesite` 基座加浅浮雕层（`wall` 连接状态） |

**验收**：裁切放大底层（`render_street_view` 同法），对照 `标准_巴黎民居街区3_外立面_正视.png` 的连续商铺带；
新增测试：底层洞口宽度分组数 ≥2、招牌带贯通率。

### E. 让 agent 真正进场（流程面）

现状：`execution_mode = None`、`framework_proposals = False`、`generator_version = None` —— 
模型的三个入口（框架规划、阶段评审、生成器修复）**一个都没走**。

| 编号 | 内容 |
|---|---|
| E1 | 框架规划交给 `prepare_framework_contract()`：模型读生成器源码 → `architectural_contract` + 5 候选 + **`unsupported_decisions`（屋顶形制等缺口显式声明）** |
| E2 | 阶段评审交给 `agent_review()`（`model_image_input=True`），采用 `layered-v2` 口径：**必须给出屋顶形制与逐层细节证据** |
| E3 | 评审不通过 → `repair_generator()` 让模型改生成器源码，产出 `generator_version`，跑测试后 rollback 重跑 |

**时序要求**：E 应在 **A 完成后**接管，否则 agent 修的生成器与人工改动会互相覆盖。
B/C/D 阶段可由我按本方案手工推进，A 完成后交给 E 做长程迭代。

## 3. "冻结更新"的硬约束清单（所有手法共同遵守）

游戏内是**禁止方块更新**粘贴，所以造型不能依赖游戏重算：

1. `stairs`：`facing` / `half` / `shape` / `waterlogged` 四向显式；转角与端部的
   `outer_left|outer_right|inner_left|inner_right` **按相邻格计算**，不能一律 `straight`。
2. `slab`：`type=top|bottom|double` 显式；上下叠放注意 `double` 合并语义。
3. `wall`：`up` / 四向 `none|low|tall` 显式。**`up=false` 且四向无连接 = 幽灵方块，
   游戏内无模型**，几何检查会拒绝（项目已踩过）。
4. `glass_pane` / `iron_bars`：四向连接显式；单格孤立必须至少留一侧连接。
5. `door`：`half=lower|upper` 成对；源样本里 `half=lower` 的装饰薄窗面**保持原状**，
   不得擅自改成成对门（AGENTS.md 明文）。
6. 每个手法改完都要跑：几何检查（幽灵方块）+ 独立 JS 校验（`validate_schematic.cjs` 回读零差异）。

## 4. 依赖关系与建议顺序

```
A（架构收敛）──┬──> B（屋顶）
               ├──> C（立面）
               └──> D（店铺）
                        │
         A~D 稳定后 ────┴──> E（agent 接管长程迭代）
贯穿全程：E6 验证（渲染对比 + 单测 + 独立校验 + 冻结状态检查）
```

| 阶段 | 内容 | 判据 |
|---|---|---|
| 1 | A1+A2 打通一条技法通路（试点：檐口 B3） | 檐口由 technique 层产出且渲染正确 |
| 2 | B 屋顶全套 | 屋顶读出坡面/檐口/老虎窗；剖面单调性测试通过 |
| 3 | C 立面 + D 店铺 | 同尺度对照参考图；窗比与洞口分组测试通过 |
| 4 | A3 收敛 + E 交给 agent | `run_autonomous` 跑通并停在 `game`，`game_acceptance = PENDING` |

## 5. 边界（本方向不做／不得声称）

1. **不代填游戏验收**：`game_acceptance` 始终 PENDING，只能用户判定。
2. **切角（chamfer）门面**本轮仍不在范围内——转角四角暂为直角；若要做，属 A1 的形式参数扩展。
3. **共墙在独立件中可见**：真实街景被邻栋遮挡，属单栋导出的固有边界。
4. **迁移会改变现有产物**：A2 之后 `runs/ATELIER-54E0BBBA` 的旧 revision 不再字节复现，
   必须保留旧 revision 目录作对照，不得声称"同一产物"。
5. **不引入 Create 等外部模组方块**，仍限于原版方块状态。
