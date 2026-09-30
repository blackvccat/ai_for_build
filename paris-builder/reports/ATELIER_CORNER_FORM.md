# 转角形式（corner_house）：缺口、修复与验证

日期：2026-09-26　run：`runs/ATELIER-54E0BBBA`

## 1. 门禁暴露的问题

ATELIER-54E0BBBA 的 brief 是"两条街相交处的转角巴黎豪斯曼建筑"。框架阶段产出五个候选，
逐张判读后确认：**五个候选的体量拓扑完全相同**——north 为街面、south 为后院面、
west/east 为盲共墙，即一栋位于连续街墙中的街屋；候选之间只差开间间距、入口位置与屋顶高度。

判读记录：`runs/ATELIER-54E0BBBA/review-aids/FRAMEWORK_READING.md`
评审记录：`runs/ATELIER-54E0BBBA/review-aids/framework-review-revision0.json`
（决定 `reject`，`rollback_stage = frameworks`，工作流 revision 0 → 1）

## 2. 根因

| 位置 | 事实 |
|---|---|
| `src/paris_builder/house.py` | `street_house` 的墙角色硬编码为 `street(north, PRIMARY) / party_west / party_east(PARTY) / rear(south, SECONDARY)`，即"一个街面 + 一个后院面 + 两侧共墙" |
| `src/paris_builder/haussmann_reference.py` | `reference_haussmann` 专用构建器同样把东/西侧写成 `party-wall`，街面逻辑只作用于 z0 面，manifest 也硬编码 `('street','primary'),('rear','courtyard'),('party_west','party'),('party_east','party')` |
| `src/paris_builder/house.py` | `chamfer` 参数只挂在 `apartment_block`（四可见面的独立公寓）上 |

因此 `atelier_workflow.plans()` 无论怎样变化 bay_pitch / entrance / roof_height，
都不可能产生转角候选。**这是形式层缺口，不是候选质量问题**：
按 `workflow.py` 的门禁注释，不得把一个自身评审未通过的候选推过闸门，
正确做法是回退该阶段并修生成器。

## 3. 修复

### 3.1 新增结构形式 `corner_house`（三层系统的通用路径）

`house.py`：新增 `corner_house(wid, dep, storey_count, seed, entresol, roof)`，
四个墙面为 `street_north(PRIMARY) / street_east(PRIMARY) / party_west(PARTY) / party_south(PARTY)`。
因为两面都标 PRIMARY，立面层对两条街面都做完整构图；共墙为 PARTY，不带任何开口。
`FORMS` 由 6 项增至 7 项。

### 3.2 reference_haussmann 的转角分支

`haussmann_reference.py`：新增 `build_corner(plan, tier)`，`build()` 在
`plan.form == 'corner_house'` 时分派过去。要点：

- **面适配器**：`at(u, y, d)` / `cub(ua, ub, ya, yb, da, db)` 把"沿 u 轴的一榀立面"
  映射到世界坐标。`d` 是从外表面往里的进深，负值表示悬挑到街面之外。
  north 面 `at(u,y,d) = (u, y, z0 + d)`，east 面 `at(u,y,d) = (x1 - d, y, u)`。
  同一段立面代码因此可以作用于两个相邻朝向。
- **四坡屋顶** `_corner_rise(dx, dz, wid, dep, roof_h)`：rise 同时受两个方向的收坡约束，
  四条边都保持檐口。这样两条街面都不会变成山墙——若沿用原来的沿 z 双向坡，
  east 街面正好落在山墙一侧。
- 两条街面各自拥有：底层铺面/入口、开间窗阵、层线（storey-course）、檐口（cornice）、
  绕角连续的阳台带（balcony-plate + 栏杆 + 托座）、老虎窗排、rustication（tier 3）。
- 共墙侧：`party-west` 与 `party-south` 为石砖实墙，**没有任何开口**；
  烟囱移到两条共墙线上；排水链改挂在两个街面上而不是后墙。
- manifest 的 `walls` 输出 `street_north(primary) / street_east(primary) / party_west(party) / party_south(party)`，
  并新增 `bay_u`（每个街面的开间位置）。

### 3.3 规划层

- `design.py`：`DEFAULT_SCHEME` 增加 `corner_house`；`plan_for` 增加转角地块的默认尺寸
  （两个街面各需自己的铺面与开间，故 20..30）；`reference_haussmann` 的校验从
  "只能是 street_house"放宽为 "street_house 或 corner_house"。
- `atelier_workflow.plans()`：框架竞争改为 **4 个转角候选 + 1 个街屋对照**，
  仍满足"每对候选至少三个建筑轴不同"（转角候选之间差 bay_pitch / entrance / roof_height 三轴，
  与街屋对照差 footprint_type 加这三轴）。
- `tests/test_design.py`：形式数量断言由 6 更新为 7，并加入 `corner_house`。

### 3.4 未改动的部分

`build()`（street_house 路径）逐字节保持不变；新增代码只在
`plan.form == 'corner_house'` 时进入。因此既有 run 的产物与冻结交付不受影响。

## 4. 验证

- `python -m unittest discover -s tests` → **129 项通过**
  （含遍历 `house.FORMS` 的三层正交性回归，即 `corner_house` 在通用路径上同样可构建）。
- 冒烟件 `runs/SMOKE-CORNER/`：`design.plan_for('corner_house', width=28, depth=28, storeys=6,
  bay_pitch=5, entrance_fraction=.5, roof_height=7, detail_profile='reference_haussmann')`
  → `walls = street_north(primary, 30 开口) / street_east(primary, 30 开口) / party_west(party, 0) / party_south(party, 0)`，
  7 视角 + 16 环绕 + 接触表渲染完成，肉眼确认：
  相邻两面为完整米黄立面（含窗阵、底层铺面、绕角连续阳台带），另外两面为灰色盲共墙，
  屋顶四坡且四边有檐口。
- 过程中的一个真实缺陷已修：north 面的进深符号最初写成 `z0 - d`，
  与 `Wall.point()` 的约定（`d=0` 是外表面、`d` 增大向建筑内部）相反，
  会让玻璃与阳台落到墙外/墙内错误的一侧；改为 `z0 + d` 后修正。

## 5. 边界（不得声称的部分）

- 转角形式尚未经过游戏内粘贴验证；`game_acceptance` 仍为 PENDING，只能由用户判定。
- `build_corner` 目前不提供切角（chamfer）门面，角部为直角相接；
  巴黎转角楼的切角门面属于后续可加的形式参数。
- 两个共墙侧在独立交付件中可见（会被邻栋遮挡的部分在此为空），这是单栋导出的固有边界。
