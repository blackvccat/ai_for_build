# 底层店铺层缺陷：诊断与修复

日期：2026-09-26　run：`runs/ATELIER-54E0BBBA`

## 1. 用户指出的问题

> "为什么底层的店铺层没考虑到细节啊这些窗户全部都使用是不是太怪了，是不是工作流哪里没考虑到"

## 2. 事实核实（先看图，不凭印象）

放大 tier3 候选（revision 3）的街面下层与轴测图后确认，用户描述的现象成立：

- 底层每个开间的洞口**与上层住宅窗做法完全相同**：同一块 `light_gray_stained_glass`，
  外加**同一套砂岩窗套**（`window-jamb` / `window-head` / `window-sill`），
  顶部也走同一条 `window-head` 线。
- 底层与上层只有**高度差 1 格**（5 格 vs 4 格）这一点区别，所以底层读起来就是"放大的住宅窗"。
- 店面**没有任何店面专属构件**：没有门槛石（stall riser）、没有招牌带（sign band）、
  没有橱窗分格（mullion）、没有店面自己的框（pier / lintel）。
- 所有楼层共用同一套窗型：只有"底层+贵族层 5 格、其余 4 格"两档，楼层之间没有真正的窗型分级。

## 3. 根因：工作流确实有三处没考虑到

### 3.1 生成器（直接原因）

`src/paris_builder/haussmann_reference.py` 是 `reference_haussmann` profile 的**专用手写构建器**。
它的立面循环里，底层只做了：

```python
kind = 'door' if (face['entry'] and bi == entry_index) else 'shop'
...
for du in (0, 1):
    if kind not in ('door', 'cafe_door'):
        ...GLASS...                      # 店面与住宅窗共用玻璃
if tier >= 1:
    for uu in (bu - 1, bu + 2):
        ...jamb_state...                 # 店面也被套上住宅窗套
    for uu in range(bu - 1, bu + 3):
        put(... 'window-head')
        if kind not in ('door', 'cafe_door'):
            put(... 'window-sill')       # 店面也有住宅窗台
```

即：`kind == 'shop'` 这个分支**被算出来了却没有被用**——店面与住宅窗走同一条代码路径。

### 3.2 架构断层（结构性原因）

`src/paris_builder/technique.py` 里**本来就有**完整的店面技法：

```
'shopfront'   glazed shop bay with its sign band and stall riser
def shopfront(scene, wall, opening, owner='technique')
    # stall riser、glazing、sign band、jambs
```

`design.py` 的**通用三层路径**也确实在 tier ≥ 2 调用它：

```python
if opening.kind == 'shop':
    if tier >= 2 and 'shopfront' in wanted:
        used.append(technique_layer.shopfront(scene, wall, opening).__dict__)
```

但 `reference_haussmann` profile 在 `design.build()` 里就走另一条路：

```python
if plan.detail_profile == 'reference_haussmann':
    return build_reference(plan, tier)     # ← 完全绕过 technique 层
```

**所以技法库里现成的店面技法，对 reference 路径不可用。**
这与 AGENTS.md 已记录的"城市层仍带自己一份街面构图代码、尚未改用三层系统"是同一类断层，
只是这次出现在 reference profile 上。

### 3.3 门禁与评审（流程原因）

`facades`（revision 3）与 `tier2`（revision 3）两次视觉评审，我记录的失败模式只有
"转角未提供切角门面"与"共墙在独立件中可见"，**没有把"店面与住宅窗同款"列为失败模式**，
所以门禁没有拦住它，一路推进到了 tier3。这是评审的漏项：评审只看"转角拓扑是否成立、
参考语汇是否对应"，没有按"每一层是否被正确表达"逐层核对店面。

## 4. 修复

### 4.1 店面专属语汇（`haussmann_reference.py`）

- `SIGN_BAND = 'minecraft:dark_oak_planks'`：深棕木招牌带，与米黄石材形成对比。
- **橱窗占满开间**：`span = max(2, pitch - 1)`。pitch 5 时橱窗宽 4 格，
  相邻开间之间只留 1 格石墩，底层因此读成**连续的商业带**，而不是一排独立窗。
- **门槛石**（tier ≥ 2）：洞口最下一格用 `BASE`（polished_andesite）填实，
  玻璃从其上开始——真实橱窗就立在这样一段矮墙上。
- **招牌带**（tier ≥ 2）：洞口顶部整条改用 `SIGN_BAND` 覆盖原来的石过梁。
- **橱窗竖框**（tier ≥ 2，span ≥ 3）：大玻璃中间加一根竖向石框分格。
- **店面独立的框**（tier ≥ 1）：两侧用 `BASE` 石墩（`shop-pier`）、顶部用 `BASE` 过梁
  （`shop-lintel`），**不再使用住宅的砂岩窗套与窗台**。

### 4.2 楼层窗型分级

```python
if kind == 'shop':
    h = 6                      # 店面：最高
else:
    h = 5 if li <= 1 else (3 if li == len(floors) - 2 else 4)   # 贵族层 5 / 标准层 4 / 顶层 3
h = max(2, min(h, ceiling - bottom))   # 受层高约束
```

不再"所有楼层同一种窗"：店面 6 格、贵族层 5 格、标准层 4 格、顶层 3 格。

### 4.3 冒烟验证

`runs/SMOKE-CORNER/smoke_shop.py`（tier 2）：

```
ground floor openings by kind: {'cafe_door': 1, 'shop': 8, 'door': 1}
widths: [2, 4]          # 门 2 格，橱窗 4 格
heights: [3, 4, 5, 6]   # 顶层/标准层/贵族层/店面
walls: street_north(primary,30) street_east(primary,30) party_west(0) party_south(0)
```

渲染确认：底层为连续橱窗带 + 深木招牌带 + 门槛石 + 深灰石墩 + 橱窗竖框，
与上层住宅窗在材料与构件上都已分开。

## 5. 流程处置

店面开洞宽度属于框架层定义的"洞口"（`WORKFLOW_STYLE_LEARNING.md` 第 9 行：
地块、轮廓、各面角色、层级、开间、**洞口**、入口轴、阳台大线、屋顶），
因此已通过的 `frameworks`（revision 2）评审对象与新代码不再一致。
按门禁语义不带着不一致继续，故：

1. `rollback` 到 `frameworks`（revision 3 → 4），理由入 `history`；
2. 重跑 frameworks → facades → tier2 → tier3 → delivery 全链；
3. 重新逐视角评审，并在失败模式里**补上店面层核对**这一项。

## 6. 仍未解决 / 不得声称

- 参考路径（`build()` 的 street_house）**没有同步这次店面改动**，两条路径目前店面做法不同；
  是否把 reference 路径并入三层技法系统（让 `technique.shopfront` 真正可用）是更大的重构，
  本轮未做。
- 店面仍无雨棚、无独立招牌文字、无橱窗陈列；这些属于可选装饰，不是本次缺陷的必需项。
- 游戏内验收（`game_acceptance`）仍为 PENDING，只能由用户判定。
