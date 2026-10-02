# 一次性产出：从「建完再看」到「建之前算清楚」

2026-10-02。本次交付四个模块、三个性能/正确性修复、22 项新测试。
验证：**387 项测试通过，5 项既有夹具跳过**（96 秒）。

---

## 1. 做了什么

| 模块 | 作用 |
|---|---|
| `atlas_geometry.py` | 从导出产物**稳健测量**：把屋面与附属体量（烟囱/老虎窗/塔亭）分开 |
| `atlas_rules.py` | 把 `knowledge/styles/paris_haussmann_v0.2.json` 里**已声明的 9 条 `frame_check` 规则**变成代码 |
| `atlas_slots.py` | **dry-run 槽位解析**：走同一条组装代码路径，不写一个方块，产出可校验的槽位计划 + 谓词 |
| `atelier_workflow.candidate()` | 接入：候选技术校验里跑风格规则，FAIL 即技术 FAIL 并进入修复 |

---

## 2. 为什么原来的循环不可能收敛（实测数据）

ATELIER-A9B3C7EE 在立面上跑了 27 个修订，分数在 72~86 之间摆动（门槛 80），**零净进展**：

- **步长是重写整个代码库**，不是改参数 → 设计没有持久身份，每次都是重掷骰子
- **缺陷在像素上才发现** → 建完、渲染完、看完才知道，代价最高、噪声最大
- **判据不确定** → 同一个产物两次评审给 74 和 86

atlas 线已经换了架构（30 行的 composition spec + 92 件人工件 + 确定性组装），
但没人用上这个变化。本次把循环搬到规格上。

---

## 3. 关键发现：规则早就在，只是没人执行

`knowledge/styles/paris_haussmann_v0.2.json` 里**每一条规则都带 `frame_check` 字段**，
写明机器可检的判据：

```
roof_share     (total_top_y - roof_datum_y) / total_top_y ∈ [0.25, 0.38]；剖面必须有坡折
cornice_ratio  cornice_top_y / total_top_y ∈ [0.72, 0.80]
corner_family  family ∈ {chamfer, rounded, prow, pavilion, recessed_court}；非默认须 justification
balcony_levels 恰好两条连续阳台带，对齐 noble_base 与 cornice_base
bay_rhythm     |Δpitch| ≤ 1
composition_hierarchy  凸出体 / 转角强调 / 屋顶中断，三者至少居一
base_treatment 基座与主体分材；基座占 12-20%
party_walls    共墙 glazing_allowed=false 且逐面声明
vertical_system 层序存在且顺序正确
```

**此前没有任何代码读它们。**评审被要求用散文判断"像不像豪斯曼"，而九条数值不变量躺在 JSON 里没人看。

用真实产物（`ATLAS-FRAME-PROBE-v5`）一跑，结果 **6 PASS / 2 FAIL / 1 UNMEASURED**：

```
[OK  ] bay_rhythm              pattern=[4,5,5,4] deltas=[1,0,1,0]
[OK  ] composition_hierarchy   有凸出体分组
[FAIL] corner_family           用了 turret（非默认族）却未声明 justification
[OK  ] balcony_levels          两条带对齐贵族层与檐口
[  ? ] party_walls             6 个面未显式声明 glazing_allowed
[OK  ] roof_share              0.370，界内；且检出坡折（steep=2.50 shallow=0.00）
[FAIL] cornice_ratio           0.587，要求 [0.72, 0.80]
[OK  ] vertical_system         层序正确
[OK  ] base_treatment          0.133，界内
```

**`cornice_ratio = 0.587` 就是我此前在渲染图上看到的"屋顶压倒一切"的量化根因**：
檐口只到总高的 61%，规则要求 72~80%，屋顶多吃了 11~17 个百分点。
这次它是**项目自己声明的规则**给出的，不是我的意见。

---

## 4. 测量本身先要正确（这一步我错了两次）

第一次用**局部窗口百分位**：假设屋面局部平坦。这个屋顶跨越足迹爬升 17 格，
于是每一列都高于邻域的低百分位，**整个屋顶被判成"附属体量"（一个 197 格的"烟囱"）**。

第二次用**到包围盒边缘的距离分带**：但转角楼是 **L 形**（两翼），
按包围盒分带会把两条街的屋面混在一起，北→南走一遍先爬北翼、再横穿西翼，
读出一个并不存在的"平顶"。

第三次才做对：**按到最近檐口的距离分带 + 每带最低百分位**，并且**限定在单翼范围内**。
结果两翼剖面一致，坡折清晰：

```
北翼 29,31,33,37,37,37,37,42,42,43,43,43,44,44,44,44,45,45,45,45
     └── 陡 1.6~2.0 格/格 ──┘└── 缓 0.3~0.5 格/格 ──┘
```

**这确认了 v5 的屋面确实是两段式曼萨德**（我此前"没有坡折"的判断是错的，
那是被烟囱和老虎窗污染的原始剖面骗的）。

还有一个测试抓出来的真限制：方形四坡屋顶**最内圈只有 1 列**，
1 个样本的百分位就是它自己，烟囱会被当成屋面。
修法：`PLANE_MIN_SAMPLES`，样本不足的带**从邻带插值**，不假装测到了。

---

## 5. dry-run 槽位解析

`Assembler(dry_run=True)` 走**完全相同的组装代码路径**，只是不写体素：
每一件仍然解析、仍然对源文件哈希校验、仍然记录槽位。

> 为什么不做成独立的"规划器"：独立规划器会和构建器漂移，
> 而**同一份几何有两份互相矛盾的说法**正是这个项目一路在付代价的事。

实测（真实 composition）：

```
槽位     154
角色     32 种（base-arcade / bay-noble / bay-standard / balcony-lower / balcony-upper /
                cornice / roof / dormer-lower / dormer-upper / dormer-pavilion /
                chimney / turret-base / turret-shaft / turret-cap / turret-finial /
                pier-noble / pier-standard / plant-noble …）
派生件   44
写入体素 0        ← 断言过
耗时     29 s
```

槽位谓词（本次新增 5 条）：

| 谓词 | 判什么 |
|---|---|
| `slots_resolved` | 每个槽位都真的放下了东西（0 格 = 选到死件） |
| `scene_fit` | 没有件越出场景边界 |
| `required_families` | 9 个必需元素族都有槽位 |
| `piece_fits_storey` | 立面件不高于任何楼层带 |
| `band_continuity` | 同一条带的瓦片之间没有缝 |

结果：**7 PASS / 1 FAIL / 2 UNMEASURED**，唯一 FAIL 是 `corner_family`（真实：塔亭未声明理由）。

---

## 6. 顺带修掉的三个真缺陷

| 缺陷 | 影响 | 修法 | 效果 |
|---|---|---|---|
| `technique_library.catalogue()` 每次重建 1018 条目（233k 次 `Path.relative_to`+`stat`） | 一次组装重建 **220 次**，占 200 秒里的 167 秒 | 进程内缓存 + `refresh=True` 出口 | 干跑 **200s → 29s**；全套测试 **231s → 96s** |
| 源文件哈希无缓存，44 个派生件各重算一次大文件 SHA256 | 显著但非主因 | 按 (路径,size,mtime_ns) 缓存 | — |
| `register_derived` 每次都写 .schem + 起 node 校验 | 44 次子进程 | 可复现时复用；dry-run 下登记为 deferred | — |

还有一个**设计缺陷**：`build_composed` 里有一处**回读场景**判断
"塔亭顶帽是否被冠饰接触"。这让检查依赖绘制顺序，也让 dry-run 不可能（空场景=0 接触）。
改为**从件自身的格子算接触**——精确、与顺序无关、两种模式一致。

---

## 7. 诚实的边界

- **能一次性的**：几何合规、件库兑现、承重与比例制度。九条规则里 6 条现在就能判。
- **不能一次性的**：审美（像不像豪斯曼、构图是否失衡）。但只需评一次，
  且失败时应改 **spec**，不是重写代码。
- **本次没做完的**：
  - `balcony_levels` / `party_walls` 在 dry-run 里 `UNMEASURED` ——
    因为 composed 线**不产出 frame_spec**（`balcony_baselines` / `party_faces` 都在 frame_spec 里）。
    这是真实的接口缺口，不是检查器的 bug。
  - `atelier_workflow` 的接线只覆盖 atlas 档；旧 `haussmann_reference` 档仍走旧路径。
  - **29 秒还不够快**做"毫秒级规格循环"——剩余开销在 44 个派生件的源件加载。
    要真正快，需要把派生件缓存到磁盘并按源哈希索引。

---

## 8. 命令

```powershell
cd paris-builder; $env:PYTHONPATH='src'

# 九条声明规则 vs 真实产物
python -u tools\_rules_probe.py

# 屋面测量（区分屋面与烟囱）
python -u tools\_roof_plane_probe.py [schem]

# dry-run 槽位解析 + 谓词（不写方块）
python -u tools\_slots_probe.py
#   -> runs/ATLAS-SLOTS-PROBE/slot-validation.json

# 全套
python -u -m unittest discover -s tests -p "test_*.py"    # 387 passed, 5 skipped
```

---

## 9. 下一步

1. **让 composed 线产出 frame_spec**，把 `balcony_levels` / `party_walls` 从 UNMEASURED 变成可判。
2. **加 spec 修复通道**：算术失败走算术修正（`cornice_ratio` 低 → 抬高檐口或压低屋脊），
   不重写代码。
3. **派生件磁盘缓存**：把干跑压到秒级，规格循环才真正便宜。
4. **旧档接入**：`haussmann_reference` 档也应该跑同一套规则。
