# ATELIER-54E0BBBA：转角豪斯曼建筑的完整闭环记录

日期：2026-09-26（revision 5 于 09-27 重跑）　产物：`runs/ATELIER-54E0BBBA/`　末态：`stage = game`（等待用户游戏内验收）

## 0. 最终交付状态（revision 5）

用户要求"当前产品必须赶紧交付，全部保证无误"。交付前修掉了两个**确凿的几何错误**并重跑全链：

| 错误 | 事实 | 修法 |
|---|---|---|
| 屋顶坡度曲线 | `_corner_rise` 的 `profile(d)` 在 `d=2..4` 完全不升（5,5,5），28 格跨度只升 6 格 → 屋顶渲染成平顶平台 | 抽出 `_corner_slope()`：沿两个街面各做陡坡（`1 → roof_h//2 → 3·roof_h/4 → roof_h`），共墙侧保持满高，共墙高出屋面一格 |
| 老虎窗与坡面穿插 | 老虎窗从 `top+1` 硬编码起算、搭 4 格深盒子，而坡面在 4 格深处已升到 `top+5`，两者互相穿过 | 老虎窗改**嵌进坡面**：先按 `_corner_slope` 挖开坡面，再以 `base = top + _corner_slope(1)` 就位，侧壁 / 前脸玻璃 / 顶盖逐层对上 |

**最终交付件**（`revision-5/delivery/`）与独立复核：

| 项 | 结果 |
|---|---|
| `candidate.schem` | **PASS**，40×52×41，85 280 方块，36 个调色板状态，`roundtrip_changed_voxels = 0` |
| `STATE-LAB.schem` | **PASS**，34 720 方块，`roundtrip_changed_voxels = 0` |
| 技术验证 | file PASS / geometry PASS（含幽灵方块检查）/ `deterministic_rebuild = True` / registry PASS |
| 评审链 | frameworks → facades → tier2 → tier3 → delivery **全部 pass** |
| 选中方案 | `frame-2`（corner_house，pitch 5，入口居中，roof 7）+ `facade-1`（haussmann_apartment） |
| 状态实验件 | 30 个实验区块，`game_status = NOT_RUN`（未在游戏内验证，如实记录） |
| `delivery.zip` | 76 860 字节 |
| `game_acceptance` | **PENDING**（只能由用户判定） |
| 单元/回归测试 | **170 项通过** |

**"无误"的边界（不夸大）**：上表是文件级与流程级的证据；**游戏内实际粘贴效果与审美认可
只能由用户判定**，系统与模型不得代填。已知边界：转角无切角门面（四角直角）、两条共墙在
独立交付件中可见、`street_house` 路径未同步店面语汇、屋顶使用整块方块阶梯而非 stairs 坡面
（属 `ATELIER_DIRECTION.md` 的后续工作面 B）。


## 1. 任务

网页对话提出的需求：**"先帮我生成一段提示词我想设计一栋转角的巴黎豪斯曼建筑"**。
DSH 规划给出的硬件规格：`form = street_house`、`scheme = haussmann_apartment`、
`detail_profile = reference_haussmann`、28×28×6 层、目标 MC 1.21.11 / DataVersion 4671。
转角蓝图来自 DSH 的研究推论：**两条街相交，相邻两面为完整立面，非临街两侧为盲共墙；
转角是视觉支点，阳台、层线、檐口与壁柱需绕角回折。**

## 2. 阶段推进与两次回退

| 顺序 | 阶段 | 结果 |
|---|---|---|
| 1 | research / retrieval | software 评审 pass（4 条外部巴黎来源 + 四层检索） |
| 2 | frameworks（revision 0） | **reject**：五个候选拓扑全为"前后对街 + 两侧共墙"，无一表达转角 |
| 3 | frameworks（revision 1） | 无效重跑：服务进程仍运行旧 `plans()`，候选仍是 street_house |
| 4 | frameworks（revision 2） | pass，选中 `frame-2`（4 个转角候选 + 1 个街屋对照） |
| 5 | facades（revision 2） | 发现 `facade-3` 与 `facade-1` 渲染**逐字节相同**，竞争不成立 |
| 6 | facades（revision 3） | pass，选中 `facade-1`（haussmann_apartment） |
| 7 | tier2（revision 3） | pass |
| 8 | tier3（revision 3） | **用户指出底层店铺层缺细节**：店面与住宅窗同款 |
| 9 | frameworks → tier3（revision 4） | 店面专属语汇修复后全链重跑，各阶段逐一 pass |
| 10 | delivery | software 评审 pass → `stage = game` |

完整评审链（`workflow.json` 的 `reviews`）：
`research(pass/software) → retrieval(pass/software) → frameworks(reject/operator) →
frameworks(pass/operator) → facades(pass/operator) → tier2(pass/operator) →
frameworks(pass/operator) → facades(pass/operator) → tier2(pass/operator) →
tier3(pass/operator) → delivery(pass/software)`

## 3. 生成系统的三处变更

### 3.1 转角形式（`corner_house`）

缺口与修复详见 `reports/ATELIER_CORNER_FORM.md`：`street_house` 只有
"north 街面 + south 后院 + west/east 共墙"这一种组合，全项目没有"相邻两面沿街 +
相邻两面共墙"的形式。新增：

- `house.py`：`corner_house`，四墙为 `street_north(PRIMARY) / street_east(PRIMARY) /
  party_west(PARTY) / party_south(PARTY)`；`FORMS` 6 → 7。
- `haussmann_reference.py`：`build_corner()` + 面适配器 `at/cub`，四坡屋顶
  `_corner_rise()` 保证两条街面都保住檐口；`build()` 在 `form == 'corner_house'` 时分派。
- `design.py`：`DEFAULT_SCHEME` 与 `plan_for` 支持该形式；`reference_haussmann` 校验放宽。
- `atelier_workflow.plans()`：框架竞争改为 4 个转角候选 + 1 个街屋对照。

### 3.2 店面专属语汇

缺口与修复详见 `reports/ATELIER_SHOP_BASE.md`。要点：橱窗占满开间（`span = pitch - 1`）
形成连续商业带；门槛石（stall riser）、深木招牌带（`dark_oak_planks` sign band）、
橱窗竖框（mullion）、店面独立石墩与过梁；**不再套用住宅窗套与窗台**。

### 3.3 楼层窗型分级

店面 6 格 / 贵族层 5 格 / 标准层 4 格 / 顶层 3 格（受层高约束），
不再"所有楼层同一种窗"。

## 4. 交付件与独立复核

`runs/ATELIER-54E0BBBA/revision-4/delivery/`：

| 文件 | 内容 |
|---|---|
| `candidate.schem` | 转角建筑本体 |
| `STATE-LAB.schem` | 状态实验件（29 个状态实验区块） |
| `instructions.json` | 粘贴步骤与 `game_acceptance: PENDING` |
| `manifest.json` | 选中方案（`frame-2` + `facade-1`）与文件收据 |
| `technical_validation.json` | file / geometry / deterministic_rebuild / registry |
| `state_lab_tests.json` | 状态实验格记录 |
| `workflow_snapshot.json` | 末态工作流快照 |

独立复核（`tools/validate_schematic.cjs`，不读 Python 侧结论）：

- `candidate.schem`：**PASS**，43×53×43，97 997 方块，32 个调色板状态，
  `roundtrip_changed_voxels = 0`；
- `STATE-LAB.schem`：**PASS**，34 720 方块，`roundtrip_changed_voxels = 0`；
- `technical_validation`：file PASS / geometry PASS / registry PASS，`deterministic_rebuild = True`
  （同种子重建逐格一致）；
- `delivery.zip`：57 439 字节。

## 5. 边界（不得声称的部分）

1. **游戏内验收仍未进行**：`game_acceptance = PENDING`，只能由用户在游戏内判定。
   代码与文件级 PASS 不等于用户认可。
2. **转角形式没有切角门面**：四角为直角相接；巴黎转角楼常见的切角/圆角属尚未实现的形式参数。
3. **两条共墙在独立件中可见**：真实街景中该处被邻栋遮挡，这是单栋导出的固有边界。
4. **reference 路径与通用路径的店面做法目前不同**：`build()`（street_house）没有同步店面语汇，
   也未接入 `technique.shopfront`（技法库里本就有该技法，但 reference profile 绕过了技法层）。
   把 reference 路径并入三层系统是更大的重构，本轮未做。
5. **动态插件不跨进程重启**：3080 的 `/building` 页面（Cordis 插件 `build-1`）在本会话已不存在，
   需要重新 `cordis_run` 才会恢复。
6. **改代码后必须重启 8765 服务**：该服务是长驻进程，`plans()` 等模块改动不会热加载；
   本轮第一次重跑就是因此产出了无效候选。

## 6. 游戏内验收步骤（供用户）

1. 取 `runs/ATELIER-54E0BBBA/revision-4/delivery/candidate.schem`，用 WorldEdit/FAWE
   **在禁止方块更新与邻接更新的模式下**粘贴；
2. 先粘 `STATE-LAB.schem`，按 `state_lab_tests.json` 的 29 个实验区块记录：
   正常更新与禁止更新的差异、相邻方块变化、区块重载后的外观；
3. 验收记录通过 `POST /building/api/acceptance`（或网页的验收入口）提交，
   该通道是唯一写入 `user_acceptance.json` 的入口，`authority: USER_ONLY`，
   系统与模型不得代填。
