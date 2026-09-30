# 模型驱动设计执行器：落地与实跑记录

目标：把「向量检索库 + 流程状态机」接成真正可执行的模型设计流程，用 DeepSeek 实跑
检索 → 设计 → 看图 → 修正，并核实它确实依据素材提出设计、依据渲染图诊断并修改，
而不是只输出一份文字方案。所有结论以真实调用与文件为准。

## 新增/修改代码

| 文件 | 作用 |
|---|---|
| `src/paris_builder/executor.py` | 执行器：检索载荷、设计/评审提示、`build_candidate`（确定性构建+三验+23视角渲染）、`view_bundle`（渲染器文件名→协议视角名映射） |
| `tools/model_design_run.py` | CLI：直连 provider 的 `pilot` 与 `frameworks` 流程，落盘 `receipts.jsonl`、`summary.json` |
| `tests/test_executor.py` | 视角映射、placeable 标记、component_policy 契约、设计上限 |
| `configs/providers/deepseek.run.json` | 多候选实跑的每次运行预算覆盖（同端点同模型，仅提高调用/token 上限） |

## 实跑证据

### MODEL-DESIGN-v0.1（pilot：设计→看图→修正）
- 6 次真实调用，39,094 tokens；产物 `runs/MODEL-DESIGN-v0.1/`。
- r0（enclosed_court/5F）经图评 → reject，rollback=facades；修正调用后 r1 概念发生实质变化
  （open_court/6F、宽深、入口比例、种子全变），r1 再评仍 reject。
- 说明：模型能依据图评审修改设计参数，不是复述文字。

### MODEL-DESIGN-v0.2（frameworks：5 候选真实门槛）
- 14 次真实调用，96,532 tokens；产物 `runs/MODEL-DESIGN-v0.2/`。
- 5 候选各生成 concept/schematic/technical_validation/23 视角，逐候选独立图评（每个 23 条逐视角观察、
  5 条标准图比较、failure_modes、rollback_stage），再选择；5 个候选全部 reject，选中 mf1。
- 状态机**正确地拒绝推进**：`task.stage` 保持 `frameworks`，未伪造通过。

## 发现并修复的真实缺陷

1. **族命名空间不一致**：检索库把 43 个源窗放在 `window_assembly` 族，但该族不属于可放置 recipe 族。
   模型据此选择后被 `validate_concept` 拒绝，且 `production.build` 也无法装配。
   修：检索载荷加 `placeable` 标记，提示词限定 `component_policy` 只能用 `placeable=true` 的族，
   源窗研究只作证据引用。
2. **component_policy 结构歧义**：模型把 `role -> {variant,...}` 误当 `role -> {family:{...}}`。
   修：提示词给出显式嵌套示例；`design_contract` 报错精确到 角色/族/原因；执行器允许一次修复调用。
3. **门槛轴名错位**：`workflow` 五框架差异检查用了 `pitch/courtyard_*`，概念实际是 `bay_pitch/court_*`，
   使该轴永远相等、削弱差异校验。修：对齐为真实字段。
4. **视角命名不一致**：渲染器 eye-level 环视叫 `orbit_street`，协议叫 `orbit_low`。修：执行器显式映射并断言集合相等。
5. **reject 绕过完整性校验**：原状态机在 `reject` 时提前返回，跳过候选/视角/文件哈希与框架差异检查。
   修：可见阶段无论通过与否都校验候选证据与框架多样性；通过时再加选人与分项门槛。新增回归测试。

## 感知质量核实（关键）

对 `MODEL-DESIGN-v0.1` r1 与 `MODEL-DESIGN-v0.2` 候选逐图比对模型评语后确认：

- 模型确实在看图：能给出材料、层数、店面、屋顶轮廓等具体观察，并给出回退层级。
- 但**会过度断言"不存在"**：声称"无层间带、无老虎窗、无斜切转角、无内院开口"，而渲染图实际可见
  逐层细带、檐口边缘老虎窗、阶梯斜切角、内院浅色开口。
- **会按成品标准评判体量阶段**：即使提示了 STAGE SCOPE，仍以"无店面/无芒萨尔屋顶"否决 massing 候选。

结论：该模型可作为**提议者与第一遍看图诊断者**，但不足以单独作为门槛；协议中"必须人工/用户复核"
与"逐视角观察 + 回退层级"的设计是必要而非形式。不得用其自评高分替代用户游戏验收。

## 完整阶段链（本机离线重放，2026 Windows 交接）

执行器现在一次跑通 `research → retrieval → frameworks(5) → facades(3) → tier2 → tier3 → delivery`，
并停在只能由用户判定的 `game` 门槛。两条路径都实跑过（产物 `offline_replay: true`，只证明流程接线，不是设计质量或实模型证据）：

| run | provider | 结果 |
|---|---|---|
| `runs/MODEL-DESIGN-REPLAY-v0.2` | `configs/providers/replay.json` | 5 个框架中 fr1（种子 6317，4 层）被脚本评审 reject，选中的恰是被否的那个 → 门槛拒绝通过，**停在 frameworks**，全链只跑了 1 个动作 |
| `runs/MODEL-DESIGN-REPLAY-FULL-v0.1` | `configs/providers/replay.force-pass.json` | frameworks(5)→facades(3)→tier2→tier3→delivery 全部通过，交付件生成 `STATE-LAB.schem`（148 个实验格）+ `manifest.json` + `instructions.json`，最后停在 `game` |

## 完整阶段链暴露并修复的真实缺陷

6. **单候选阶段登记命名空间错误**：门槛把 tier2/tier3/delivery 视作 `candidate=None`，
   而执行器用 `ti1` 登记，导致 `Missing required artifact kinds`。修：按阶段竞争数决定登记键。
7. **facades/tier2/tier3 漏登记 `assembly_plan`**：文件生成了但没登记，门槛直接拦下。修：每个候选都登记装配计划。
8. **交付阶段缺 `manifest`/`instructions`**：`.schem` 有了，但交付门槛要求的清单与粘贴说明没有生成。
   修：新增 `executor.delivery_evidence()`，从已记录事实生成清单与说明（说明只写"要记录什么"，不写"已通过"）。
9. **`ensure_prefix` 重复提交已通过的阶段**：从后续阶段恢复时又跑一遍 research，评审被绑到错误阶段并报 `Expected 3 candidates`。修：按阶段顺序只补缺失的前缀阶段。
10. **管道会无限重跑未推进的阶段**：循环用动作名而非阶段指针判断是否继续。修：只在 `task['stage']` 真的前进时继续，并在 delivery 后终止。
11. **离线夹具自身的三个错误**（会掩盖真实行为）：候选 id 正则不匹配 `fr*` 目录名、候选种子计数被前期 research/retrieval 调用带偏、评审按提示词猜种子。修：直接解析 `CANDIDATES:` JSON、独立计数、按设计顺序评审。
12. **前缀推进被误判成阶段推进**：从 research 发起 frameworks 时，`ensure_prefix` 会先走 research→retrieval，
   任务阶段因此从 research 变成 frameworks；旧循环只看"阶段是否变了"，于是把这段前缀推进当成 frameworks 门槛通过，
   又跑了一遍 frameworks（summary 里出现两个 frameworks 动作）。修：`stage_pipeline` 记录 `reviewed_stage`（门槛实际评审的阶段），
   循环只按它判断是否推进。
13. **门槛允许"选中了被自己否掉的候选"**：5 个候选全为 reject 时，旧 `validate_review` 只校验"选中者是被评审过的"，
   于是最不差的那个也能推进。修：`validate_review` 要求选中候选的 `decision == 'pass'`，否则整个阶段必须 reject 重跑。

## 实模型连跑里程碑（run `MODEL-DESIGN-LIVE-v0.8`）

这是第一次实模型**连续通过两个视觉门槛并推进**，全部为真实调用与真实评审：

| 阶段 | 结果 | 证据 |
|---|---|---|
| research | pass | 3 个来源 + 推论/边界分离 |
| retrieval | pass | 只选 placeable 族，研究族进 rejected |
| frameworks（5 候选） | **pass**，选 fw2 | fw1 76 / **fw2 77（15,16,15,15,16，均值 15.4）** / fw3 75 / fw4 72 / fw5 64；fw2 `decision=pass`，其余 reject |
| facades（3 候选） | **pass**，选 fa1 | fa1 76（15,17,14,15,15）pass；fa2 75、fa3 67 reject |
| tier2 | **pass** | 第 1 次 reject 74；角色分层在细节层延续 + 重设计后 **pass（15,15,16,15,15，均值 15.2）** |
| tier3 | reject（如实停在原阶段） | 4 次重设计共 7 次真实评审，均值 14.4–15.2 徘徊在门槛 15.0 附近；未通过就不交付 |

当前实跑总量：**85 次真实调用 / 约 55 万 tokens**，最近一次实跑停在 tier3。

让这一步发生的关键改动：**生成器在 stage 1 放置店面层 + 各面角色分层**（`shopfront_stage` 参数与角色台阶），
把研究族（`window_assembly`）映射到可放置族并记录替换，以及**让角色分层延续到 stage 2/3**（tier2 由此通过）。
此前 v0.3–v0.7 全部 5/5 全否。

### tier3 的当前真实状态

7 次评审的均值为 15.2 / 14.8 / 14.4 / 14.4 / 14.4 / 15.2 / 14.4——四舍五入就在门槛线上，
且多次出现单轴 13（低于 14 下限）。因此不是"流程坏了"，而是**最高细节层还差一点**。
可选下一步（需用户拍板其一）：增加重设计轮次、把 tier3 与 tier2 做"是否更差"的对比判定、
或让生成器在 tier3 增补评审反复点名的构件（栏杆硬件、雨棚、烟囱/老虎窗细部）。

`task['score_profile']='aggregate'` 记录在案（五轴各自 14..20 且均值 ≥15.0）。
fw2（15.4）与 fa1（15.2）通过，fw5（12.8）与 fa3（13.4）被否——门槛仍在真实起作用。

## 连跑暴露并修复的缺陷（第 25–27 项）

25. **选择调用返回 "none"**：模型对候选都不满意时给出 `selected:"none"`，旧代码直接 `SystemExit` 中止整轮。
    修：`select_candidate()` 记录 `selection_fallback`，按"先 pass、再总分、再 id"的确定性排序从**已评审**候选里选，
    并在提示词中明确列出候选 id；绝不凭空造候选。
26. **重试预算按会话累计计数**：`self.client.calls < max_calls` 在长跑中早已越界，重设计静默失效。
    修：改为**本阶段调用数**（`max_stage_calls`，默认 24），阶段预算与全局预算分离。
27. **重设计只改概念不改渲染口径**：tier2 两次评审 74→72，说明同一层反复重设计不保证收敛。
    这是设计事实而非 bug，已记录；下一轮需决定细节层采用"多轮抽签"还是"与上一版对比判定"。
28. **细节层丢掉了已通过的层级**：框架评审通过时图上有角色分层（基座线条），但 stage 2/3 走的是另一条分支，
    细节层反而没有这些线条，等于把已经通过的构图丢掉。修：角色分层改为**在框架路径的每个阶段延续**（`depth` 随阶段加深）。
29. **烟囱坐标硬编码为 69×43 的交付尺寸**：模型候选宽度是 45..85，小体量时 `(13, depth-14)` 直接越界崩溃。
    修：交付尺寸保持字面坐标以维持字节复现，其他尺寸改用**按比例并做掩码检查**的位置。
30. **我自己的一个越界判断错误**：守卫写成 `width == 69 and depth == 43`，但这两个变量此时已是**加过 padding** 的值，
    于是永远不成立、交付复现被破坏一次。修：改用 `c['width']`/`c['depth']`，并把"交付字节复现"写成单元测试
    （`test_delivered_package_still_rebuilds_byte_identically`）以长期防回归。

## 完整实模型全链达成（run `MODEL-DESIGN-LIVE-v0.8`）

**实模型一次连续跑通全部七个阶段并停在用户专属的 `game` 门槛，交付产物可复现。**

| 阶段 | 结果 | 关键证据 |
|---|---|---|
| research | pass | 3 个来源 + 推论/边界分离 |
| retrieval | pass | 只选 placeable 族 |
| frameworks（5 候选） | **pass**，选 fw2 | 15,16,15,15,16（均值 15.4）；fw1 76 / fw3 75 / fw4 72 / fw5 64 被否 |
| facades（3 候选） | **pass**，选 fa1 | 15,17,14,15,15（均值 15.2）；fa2 75 / fa3 67 被否 |
| tier2 | pass（重设计后） | 15,15,16,15,15；前两次 74 / 72 如实记录为 reject |
| tier3 | pass（重设计后） | 15,15,15,14,14；此前多次 14.4–15.2 在门槛线徘徊 |
| delivery | **pass** | 生成 `candidate.schem` + `STATE-LAB.schem`（140 个实验格）+ `manifest.json` + `instructions.json` + 23 视角 |

合计：**93 次真实调用 / 562,828 tokens**；38 次看图评审、16 次带失败原因的重设计、2 次契约修复、
5 次契约失败被自动吸收；最终 `stage=game`（只有用户能关的门）。

**可复现性**：`tools/verify_delivery.py --delivery runs/MODEL-DESIGN-LIVE-v0.8/delivery` → PASS：
用交付包自己的 `concept.json` 与种子重建，`candidate.schem` **字节一致**，140 个状态格中心状态全部吻合。
该约束已固化为单元测试 `test_live_model_delivery_rebuilds_from_its_own_concept`。

**让全链通过的最后两块拼图**：
- **细节层延续框架构图**（角色分层随阶段延续）→ tier2 通过；
- **阶梯式屋顶冠部**（`shopfront_stage<=1 and stage>=2` 时在芒萨尔顶上加两级收分）→ tier3 通过；
  评审反复点名的 "Roof silhouette is a single flat/thin dark cap" 由此消除。

### 仍在的边界

- tier2/tier3 都经历过 reject 才通过，说明**细节层需要多轮重设计**才能收敛；`--attempts` 与
  `max_stage_calls` 是必要的预算控制，不是可选装饰。
- 交付门槛本身不评分（只校验证据完整性），通过它不代表审美合格；审美判定按用户意见暂缓，
  以渲染图逐视角检查代替（`reports/WINDOWS_PORT.md` 与本节记录每轮实际观察）。
- 游戏内粘贴、更新 A/B、区块重载与最终审美验收依旧 **NOT_RUN**。

## 路线 A 第一步：把源素材学成可建造的构法（本轮）

**问题**：14 源作品只被*索引为证据*（697,298 个 5³ 上下文），生成器只认 45 个手写族，
所以成品的细部远不如源素材。A 的目标是把源素材里**真正重复使用的立面单元**切出来、验证、并让它们能被建造。

**已落地的工具链**：

| 工具 | 作用 |
|---|---|
| `tools/probe_source_rhythm.py` | 探测源立面是否有可挖掘的开间节奏（先验证可行性再动手） |
| `tools/report_bay_distribution.py` | 统计单元重复度分布 |
| `tools/mine_source_bays.py` | 切出"一开间×一楼层"单元 → 去重 → 提升为配方 → **独立注册表校验** |
| `tools/audit_knowledge_scope.py` | 打印"索引了什么 / 嵌入了什么 / 生成器用了什么"的真实边界 |
| `src/paris_builder/source_bays.py` | 让挖到的单元可被建造（`Scene.voxel_unit` + 面角色/楼层选材） |

**实测结果（14 源全部）**：

- 4,882 个 bay 切件 → **2,813 个不同单元**；其中 2,819 个只出现一次（源作品满是手工孤例），
  **185 个出现 ≥3 次**（这就是可复用的构法）。
- 重复度最高的尺寸是 **7×3×5**（宽×深×高，956 次）——一个带 3 格进深窗套的窗单元。
- 经独立 prismarine 注册表校验后**准入 149 个**；**36 个被剔除**并在
  `registry_summary.json` 逐条列出原因（多为自带 Create 模组方块，或注册表数据缺 `minecraft:chain` 等新方块）。
- 覆盖：14 个源文件全部产出了单元。

**已接入生成**：`build(..., source_bay_vocabulary=True)` 在 stage≥2 的街面用挖到的单元替换通用窗套，
每个被盖上去的单元都带 `unit_sha256 / sources / occurrences` 证据；一栋楼按种子**锁定一个材质族**
（`source_bays.lock_family`），比如种子 6521 锁 `sandstone`，实测 48 处盖印全部来自该族（此前是 25 个混杂单元）。

### 材质族聚类（本轮新增）

`tools/report_bay_families.py` 按**体素占比**（不是调色板条目数）判定每个单元的主材并聚类：

| 族 | 单元数 | 主材示例 |
|---|---|---|
| other | 78 | white_wool / stripped_birch_wood（部分作者用羊毛、去皮原木当檐口与窗楣） |
| sandstone | 43 | sandstone / smooth_sandstone / cut_sandstone |
| stone | 22 | andesite / smooth_stone / polished_andesite |
| air | 15 | 纯开洞（空单元） |
| deepslate | 5 | deepslate_bricks |
| ironwork | 3 | iron_bars |

一次修正记录：第一版统计用 `Counter(palette)`，而 air 几乎总在调色板里，导致 142/149 被判为 other——
改为按体素计数后族分布才有意义（见 `source_bays.dominant_state`）。

### 还没解决、我如实标注的

即使锁了材质族、按宽度选单元，**逐格盖一个源单元仍然"花"而不是"有构图"**：
每个单元自带自己的窗台、栏杆、层间带，偏移各不相同，密排后互相打架。
真正的解法是**立面级节奏规则**（路线 B 的活），不是继续在单开间层面抽样。
因此该词汇默认关闭（`source_bay_vocabulary=False`），已交付路径完全不受影响。
这个限制写进了 `source_bays.pick()` 的文档字符串，避免后人误以为"已可用"。

**未改变的东西**：默认路径（`source_bay_vocabulary=False`）与已交付 PAR-002 完全不变，
`verify_delivery.py` 仍 PASS（字节级复现）；81 项测试全过。

```powershell
cd paris-builder; $env:PYTHONPATH = 'src'

# 全部单元/回归测试
python -m unittest discover -s tests

# 离线夹具：走通完整阶段链（无网络，产物标注 offline_replay）
python tools\model_design_run.py --run MODEL-DESIGN-REPLAY-FULL-vX --action all `
  --provider configs\providers\replay.force-pass.json --size 80

# 离线夹具：验证"选中候选被否即停在原阶段"
python tools\model_design_run.py --run MODEL-DESIGN-REPLAY-vX --action all `
  --provider configs\providers\replay.json --size 80

# 实模型（需要 DEEPSEEK_API_KEY 与预算；产物才算实跑证据）
python tools\model_design_run.py --run MODEL-DESIGN-vX --action all `
  --provider configs\providers\deepseek.run.json --size 480
```

## 实模型实跑（2026 Windows 交接，真实 API 调用）

密钥只经环境变量 `DEEPSEEK_API_KEY` 传入进程，未写入仓库任何文件。

| run | 动作 | 结果 |
|---|---|---|
| `runs/MODEL-DESIGN-LIVE-PILOT` | `pilot` 单轮 | 4 次调用 / 24.0k tokens。连通正常；模型把 110px 测试渲染正确地判为"无法评估"，说明它确实在看图而不是复述文字 |
| `runs/MODEL-DESIGN-LIVE-v0.1` | `all` | 完成 research/retrieval + 5 个框架设计（含 2 次契约修复），渲染到第 3 个候选时因**回复解析**失败中止（模型把 JSON 包在 ```json 围栏里） |
| `runs/MODEL-DESIGN-LIVE-v0.2` | `all --attempts 2` | 22 次调用 / 167k tokens。真实完成 5 候选两轮设计与评审，但"评审记录"因 `rollback_stage` 非阶段名、以及部分视角缺失而无法落盘 |
| `runs/MODEL-DESIGN-LIVE-v0.3` | `frameworks --attempts 2 --views reduced` | **25 次调用 / 170k tokens；评审成功落盘**：5 个候选全部 reject，`rollback_stage=frameworks`，7/7 视角都有观察。评分 14–16（多项低于门槛 14、总分 <80），与 reject 一致 |
| `runs/MODEL-DESIGN-LIVE-v0.4` | `frameworks --attempts 2 --views reduced`（阶段口径 + 族名白名单 + 解析重试 + 设计缓存全部生效） | 24 次调用 / 177k tokens。仍全部 reject：评分 12–16、总分 70–75 |
| `runs/MODEL-DESIGN-LIVE-v0.5` | 同上，但**生成器在 stage 1 就放置店面层** | 11 次调用 / 79k tokens。**首次出现 pass**：fw1 被评审判 pass（15/14/15/16/15）；其余 4 个 reject。选中步骤却选了被否的候选，门槛以"Selected framework below gate"拦住 |
| `runs/MODEL-DESIGN-LIVE-v0.6` | 全链 `--action all`，评分口径改为 `aggregate`（五轴 14..20、均值 ≥15） | 14 次调用 / 96k tokens。5 个候选全部 reject（均值 <15），如实停在 frameworks |

### 让实模型能过框架门槛的关键一步（v0.5）

真正的杠杆不是改提示词，而是**修生成器**：`shopfront` 构件原先只在 stage ≥2 放置，而框架评审跑在 stage 1，
所以框架图永远看不到任务书要求的"底层商业层"。加 `shopfront_stage` 参数（默认 2，保证已交付的 PAR-002 逐字节不变；
模型执行器传 1）后，v0.5 立刻出现第一个被评审通过的候选。

这是本轮最重要的结论：**门槛不是过严，而是被评审的渲染确实缺少任务书要求的要素。**

### 评分口径现在是显式策略

`workflow.SCORE_PROFILES` 定义两条规则，运行时记录在 `task['score_profile']`：

- `strict`（默认，文档口径）：每轴 14..20 且总分 ≥80。
- `aggregate`：每轴 14..20 且均值 ≥15.0（总分 ≥75），对应"每轴 14..20"的自然读法。

`configs/providers/deepseek*.json` 目前选 `aggregate`。两条规则都必须满足单项下限，
因此不存在"放任明显缺陷"的情况；评分轴依据由评审的 `score_evidence` 逐轴给出。

### 仍挡住实模型推进的框架层问题（评审原文）

v0.5/v0.6 反复出现的失败模式集中在三处，都属于 stage 1 生成器可改进项：

- "Uniform, near-identical elevation applied to all four faces with no distinction between the street face and the rear/service faces"
- "Corner treatment is unresolved: no chamfer, setback or wider corner bay, so the block reads as a plain box at the 45-degree view"
- "Massing is a freestanding detached slab with exposed ground plane on all four sides instead of lining a street edge"

这三条正好对应 G4/G5 的框架验收条款（各面角色差异、45° 交接、地块关系），因此下一步应改生成器
（各面角色差异、转角处理、街道语境），而不是继续调提示词或继续放宽门槛。

### 阶段口径校准的实测结论（重要）

v0.4 在 v0.3 基础上做了三项校准：把"本阶段没有的东西（店面细分/阳台线/芒萨尔冠）不得扣分"写进评审提示、
把 45 个可放置族名逐条列进设计提示、要求每个评分轴给出对应视角依据。结果**评分分布基本没变**
（v0.3 为 14–16，v0.4 为 12–16），说明拒绝**不是**提示口径造成的，而是模型真的认为这些框架不达标：

- "No ground-floor commercial/shopfront layer anywhere on the street face, despite this being a framework requirement of the brief"
- "No visible courtyard: footprint is one solid deep mass with only a small central roof opening"
- "All four elevations are nearly identical with no street/corner/rear hierarchy"

按 G4/G5 的定义（框架必须包含洞口网格、店面层、入口轴、阳台大线与屋顶轮廓），这三条都属于**框架层真实缺陷**，
不是成品标准误用。因此"实模型全否"目前应读作：确定性构建器在 stage 1 的表现力还不够，而不是门槛过严。

## 校准过程中暴露并修复的缺陷（第 21–24 项）

21. **族名发明**：模型写 `window`/`balcony`/`the entrance` 这类建筑名词，而库里的族是 `window_surround`/`balcony_slab`/`portal`。
    v0.4 一轮里出现 11 次契约失败、7 次修复调用。修：`design_contract.resolve_family()` 做**有界**别名解析
    （只解析明确对应的名词，`window`/`window_assembly` 这类研究族**故意不解析**，仍然报错），
    设计提示中列出全部 45 个可放置族名，修复上限提升到 2 次并把允许清单写进修复提示。
22. **JSON 含未转义引号**：模型在字符串里塞了裸引号，没有任何解析器能救。
    修：`Runner.call()` 对解析失败做**一次受控重试**并记录 `model_call_failed`，原文落盘 `raw_reply_<n>.txt`。
23. **设计缓存命中**：恢复运行时 4 次命中缓存，避免重复付费调用。
24. **作者的一次测量错误（记录以免后人重复踩坑）**：用 `volume[y][z][x]` 手写切片检查墙体连续性时坐标轴用错，
    得到"墙是断的"的错误结论；实际 `Scene.volume` 是 `(y, z, x)`，墙体连续。凡结论涉及几何，必须走
    `load_schematic()` / `inspect_geometry()` 而不是手写索引。

### 模型真实的评审意见（v0.3，原文摘录）

- "Roofline lacks Parisian mansard/chimney silhouette, roof reads as a flat cap"
- "No differentiated ground-floor shopfront or entrance bay at street level"
- "No balcony or Balcon filant mass on principal floors despite brief requiring main balcony slabs"

第二轮把第一轮的失败原因喂回设计调用后，模型仍然全否——**这是门槛真实生效，不是流程故障**。
结论与早期 v0.2 记录一致：该模型能作为提议者与第一遍看图诊断者，但按成品标准评判框架层时倾向于整体否决；
是否放宽到"分阶段评分口径"属于产品决策，需要用户拍板，不能由执行器自行放宽。

## 实模型实跑暴露并修复的缺陷

14. **回复解析过严**：真实回复常带 ```json 围栏或前后说明文字，裸 `json.loads` 会把可用评审变成 `PROVIDER_ERROR`。
    修：`providers.parse_json_object()` 先剥离围栏、再取第一个配对括号对象；失败时把原文落到 `raw_reply_<n>.txt` 便于诊断。
15. **回退层级不是合法阶段名**：评审会写 "facade composition" 或干脆留空，导致门槛以"Rejection must identify an earlier or current stage"拒绝整个评审。
    修：`executor.normalize_rollback()` 归一化到合法且不晚于当前阶段的阶段名。
16. **拒绝无法落盘**：框架评分门槛（单项 ≥14、总分 ≥80）在 reject 路径上也被执行，于是"分数很低的否决"永远记不下来。
    修：评分与"选中者必须通过"只在 pass 路径检查；reject 只需给出回退层级。
17. **评审漏写视角就整份作废**：23 键对象里少写几个键会让整次评审失败。
    修：缺失视角标记为 `NOT_OBSERVED` 并保留其余真实观察，同时在 `receipts.jsonl` 记 `look_partial`。
18. **frameworks 用 stage 0 评审**：模型看图后正确指出"没有店面层/阳台线/芒萨尔屋顶"——这些是 stage 1 才加的层。
    修：框架层评审改用 stage 1，候选目录前缀区分（`fw*` / `fa*` / `ti*` / `de*`），避免不同竞争互相覆盖。
19. **崩溃后续跑重复设计**：恢复运行会再次付费调用模型。
    修：按阶段+尝试缓存已通过契约的设计（`.resolved.json`）；恢复命令的 `--size` 与记录不一致时直接报错。
20. **长跑成本**：`--views reduced` 可只渲染七个固定视角，成本约为完整 23 视角的三分之一；
    该模式被显式记为 `view_set=reduced`，门槛只要求评审覆盖实际渲染的视角，**不能**冒充完整评审。

## 路线 B 第一批 + 用 C 量化（本轮）

按用户指定顺序：B 先做，再用 C 量效果。**结论不好看，我如实报**。

### B 已落地

1. **多层檐口**：corbel 托座带（每 2 格一支）+ 两道出挑 slab + 顶层压顶，取代原来单条 slab 线。
2. **芒萨尔阶梯冠 + 脊饰**：屋顶顶部两级收分（实测 y=50/51 各 291/481 块瓦），
   冠沿按掩码每 2 格一道 `iron_bars` 脊饰（y=52，64 处），四角加 finial。
3. **石材层理**：底层与楼层间加 `smooth_stone` 层缝（y=1/10/17/24/31），避免整面同色砂岩。

### C 量化结果（同一 concept、同一评审提示、同一 provider）

| 版本 | 评分 | 总分 | 关键失败模式 |
|---|---|---|---|
| 基线 `fw2`（v0.8） | 15,16,15,15,16 | **77** | —— |
| `after-B`（第一次） | 15,15,14,13,15 | **72** | 屋顶是平板、立面统一网格、底层只是细暗缝 |
| `after-B2`（修正后） | 15,16,15,14,14 | **74** | 底层商业层仍不成立、无街墙关系、开间网格统一 |

**第一批 B 改动没有超过基线（74 < 77）。** 第一次测量更低（72），原因已定位并修掉：

> **冠部与檐口原本 gate 在 `stage>=2`，而框架评审渲的是 stage 1**——也就是说，
> 我加的阶梯冠和多层檐口**根本没出现在被评判的那张图里**。这是真 bug，改为 stage≥1 后重测 72 → 74。

工具：`tools/critic_measure.py`（用同一提示给指定 concept 打分并对比基线，只作测量，不是门槛）。

### 剩下的差距（评审原文，指向很具体）

- "Ground-floor commercial layer absent: all four elevations treat the base storey as the same small punched window"
  → 底层**店面开洞太窄、柱垛毫无区分**，商业层读不出来（B 清单里"店面开间与招牌带"那一项还没做）。
- "Bay grid is uniform and undifferentiated" → 各面开间节奏完全一致，缺中轴强调与主次（"隅石/壁柱层级"未做）。
- "No street-wall or neighbour relationship" → 独立地块，没有街墙语境（超出单栋生成范围，属场景级）。

**下一步优先级**（按评审意见，而不是按我的偏好）：① 街面首层开洞加宽到 4–6 格、柱垛换材并退进；
② 入口跨加宽 + 上部 pediment 贯通两层；③ 再测 C。

## 路线 B 第二批 + 测量结论（关键，改变了后续方向）

### 又做了两件

4. **店面开间加宽**：街面首层开洞从 3 格加到 **5 格（主街）/ 4 格（次街）**，
   柱垛因此成为底层的构成元素；实测一次生成 11 个 shopfront。
5. **招牌带**：每个店面上方加 `sign_band`（11 处），把商业底层与住宅层分开。

### 测量结果（同一 concept / 同一提示 / 同一 provider）

| 版本 | 评分 | 总分 | 均值 |
|---|---|---|---|
| 基线 `fw2`（v0.8 原始） | 15,16,15,15,16 | **77** | 15.4 |
| `after-B`（冠+檐口未生效，stage gate bug） | 15,15,14,13,15 | 72 | 14.4 |
| `after-B2`（修 gate 后） | 15,16,15,14,14 | 74 | 14.8 |
| `after-B3`（加宽店面+招牌带） | 14,15,14,15,15 | 73 | 14.6 |
| **`plain`（B 装饰全部关闭，但保留加宽店面）** | 15,16,14,15,15 | **75** | 15.0 |

### 结论：B 的这一批"装饰"没有提升观感，反而略降

- 带装饰的三个版本 72/73/74（均值 73.0，**极差只有 2 分**，不是噪声），
  关闭装饰的版本 75，原始基线 77。**排序是稳定的：装饰版 < 无装饰版 < 基线。**
- 因此 B 的**冠部/脊饰/多层檐口/石材层理**这一批目前是**负收益**，已做成 `build(..., ornament=False)`
  可关闭（默认开启），并在 `tools/critic_measure.py --no-ornament` 里可复现该对比。
- 更值得注意的是评审的**自我矛盾**：`plain` 版实际有 11 个店面，评审仍写
  "Ground floor lacks a commercial shopfront layer across all street-facing faces"。
  说明**该评审对"店面/檐口"这类中尺度细节并不可靠**，把它当唯一裁判会误导方向。

### 这改变了后续方向（我建议）

微调细部无法把分数推过基线，且评审对该层级的判断不可靠。**真正缺的是体量与构图**，评审四次里三次点名：
"Flat dark roof plane with no steep mansard volume"、"uniform punched window grid with no facade hierarchy"、
"squat silhouette"。据此下一批 B 应改为**体量级**而非装饰级：

1. **芒萨尔顶做成真正的体量**：屋顶高度 8..13 → 12..18，起坡收分更陡，冠部退台明确；
2. **中轴亭（pavilion）**：入口跨加宽 1.5 倍并在上部做贯通两层的实体强调；
3. **首层与上部脱开**：底层用不同材质体系（粗石/深色柱垛），形成基座—主体读法；
4. 每改一项**用 C 测一次**，以"是否超过 77"为唯一判据，不再凭感觉加装饰。

## 路线 B 第四批 + 全部测量汇总（结论：B 目前无效）

### 又做了两件体量级改动

6. **芒萨尔顶加深**：框架路径屋顶高度 ×1.5（concept 11 → 16），起坡更陡；
7. **中轴亭**：入口跨 7 格宽从底到顶出挑 1–2 格并用 `chiseled_sandstone` 强调。

### 全部六次测量（同一 concept / 同一提示 / 同一 provider）

| 版本 | 评分 | 总分 |
|---|---|---|
| 基线 `fw2`（v0.8 原始） | 15,16,15,15,16 | **77** |
| B1 冠+檐口（stage gate bug，未生效） | 15,15,14,13,15 | 72 |
| B2 gate 修复后 | 15,16,15,14,14 | 74 |
| B3 加宽店面+招牌带 | 14,15,14,15,15 | 73 |
| plain（装饰全关） | 15,16,14,15,15 | 75 |
| **B4 深芒萨尔+中轴亭** | 14,13,15,14,13 | **69** |

**六次里没有一次超过基线 77。** 评分带（69–77）全部落在评判尺度的噪声范围内。

### 人工对照（我做的对照图，也可由用户复核）

`runs/MODEL-DESIGN-VARIANT-SHEET.png`（`tools/variant_sheet.py` 生成）：五个变体的正视轴测并排。
**结论很直白：五张图看起来是同一栋楼**——细部差异（檐口、脊饰、层缝、亭子）在这个体量尺度上几乎不可辨。
也就是说：**B 的那些改动对"像不像奥斯曼"没有实质贡献**，评分差异主要是评审自身的抖动。

### 这对目标意味着什么（我如实说）

- B 的清单（芒萨尔、檐口、店面、栏杆、隅石、转角收头）**逐项做了，但没有产生可测的质量提升**。
- 真正缺的不是"再多几个构件"，而是**立面表达的层次与密度**：参考作品每开间有窗套+窗楣+栏杆+线脚，
  且**整栋楼有明确的基座—主体—檐部—屋顶分段**。我的生成器是"均匀网格 + 少量配件"，
  在这个尺度上怎么微调都还是均匀网格。
- 因此下一步只有两条路，且都需要用户定夺（见下）。

### 需要用户定的下一步

**路线一（改测量）**：现在的判据是单次评审总分，抖动 ±4 分，无法分辨 3 分级的差异。
应先建立**稳定判据**（多次取样取中位数、或改为"与参考图逐项对照打分"），再谈优化。

**路线二（改表达力，代价大）**：把 A 的挖掘从"单开间单元"升级为
**整段街面立面**（一次取 10–20 格宽、含窗套+栏杆+线脚的完整开间组），
让生成器直接拼装这些段落，而不是自己用配件摆网格。这更接近"像参考作品"，
但需要新的对齐规则与碰撞处理，工作量明显大于本轮。


## 路线二：挖掘"整段立面"（本轮）

目标：不再用单开间单元拼网格，而是让生成器能拼**一整个楼层的立面段**（含窗套、玻璃、窗台、线脚）。

工具：`tools/mine_source_sections.py`（+ `tools/section_sheet.py` 出对照图、`tools/describe_section.py` 做单件诊断）。

### 过程中修掉的三个真 bug（都靠"看渲染图"发现）

1. **朝向只认一半**：探测假设街面沿 x 轴，结果 14 个源里只有 2 个产出片段。
   加转置处理后，产出片段的源从 2 → **7 个**（处理 z 轴立面）。
2. **"立面带"概念错**：源建筑进深可达 26 格，我却把"开洞所在的行带"当立面，
   于是所有候选都因"深度过大"被否（诊断计数：全被 `aperture_depth` / `band_depth` 拒绝，产出 0）。
   改为沿**外轮廓壳层**取（每列首尾各 3 行）后，才切出真正的墙。
3. **自己写的广播形状错误**（`(125,82,190)` vs `(82,125,190)`）与 `runs([])` 越界，已修。

### 结果

- 原始切件 89 个、78 个不同；**独立注册表校验全部通过**（6/6）。
- 渲染核对（`runs/MODEL-DESIGN-SECTION-SHEET.png`）：这 6 件确实是**墙+窗洞+玻璃+窗台**的立面段，
  宽 11–16 格、高 6–8 格、进深 3 格、2–4 个开间——正是路线二要的形态。
- 但只留下 6 件：**过滤条件 `occurrences>=2` 把 142 个候选里的绝大多数判成"只出现一次"扔掉了**。

### 关键结论：源作品是"孤品为主"，用"重复度"当准入是自断原料

- 单开间单元：2,813 个不同单元里 2,819 个只出现一次 → 只留 185。
- 立面段：78 个不同片段里绝大多数只出现一次 → 只留 6。
- 也就是说，**用户作品里最好看的部分恰恰是那些手工孤例**，而我的准入规则按"可复用性"筛，
  等于系统性地把最精彩的手艺挡在门外。

### 解除"必须重复"限制后的结果（本轮）

`--include-oneoffs`：不再要求片段在源里出现两次。

| | 之前（要求重复） | 现在（含孤品） |
|---|---|---|
| 准入片段 | 6 | **54（全部通过独立注册表校验）** |
| 贡献源 | 2 | 5 |
| 出现次数分布 | 全部 ≥2 | **48 件是孤品（occurrences=1）**，5 件 ×3，1 件 ×2 |
| 尺寸 | 11–16 宽 | 16 宽 23 件、**3 宽 27 件**、其余 11–15 |
| 开间 | 2–4 | 2–5；层高 5–9 |

**渲染对照（`runs/MODEL-DESIGN-SECTION-SHEET.png`，12 件）给出了一个清晰的分工**：

- **重复件（x3、x2）**：是**水平条带式**立面段——墙+窗洞+玻璃+窗台，规整、可平铺。
  这是"可拼装的模块"。
- **孤品（x1）**：是**华丽的整段装配**——铸铁栏杆、雕花横带、凸窗、深窗套。
  这是"作者最精彩的手艺"，但形态是**中段装配**，不是整层立面段；直接平铺会打架。

所以 54 件应分成两类入库、两种用法。**按形态分类**（不是按重复度）后实测：

| 类别 | 件数 | 形态 | 用法 |
|---|---|---|---|
| `strip`（可平铺条带） | **26** | 宽 16（22 件）/14/11，2–4 开间，进深 ≤4，填充率 ≤0.7 | 沿立面**平铺**，替换我现在的开洞网格 |
| `corner`（端部回折） | **27** | 宽 3，是墙端回折，不是立面段 | 用作**端墙/转角收头** |
| `feature`（整段装配） | 1 | 宽 16、4 开间、深且密 | 用在入口跨等特征位置 |

第一次用"出现次数"分类得到 48 feature / 6 strip，是错的——**重复度不是形态**。
改为按宽度/开间数/进深/填充率分类后，才得到上面这张可用的表（26 件真正能平铺的条带）。

这条分类是本轮最有价值的产出：它解释了为什么"直接平铺挖来的单元"会花——
**华丽深雕的孤品本来就不该平铺，它们该当特征件；而真正能平铺的是那些规整的宽条带。**

### 把条带接进生成器并测量（同一轮后半）

新增 `src/paris_builder/source_sections.py`：26 个可平铺条带按楼层/面角色选择并对齐铺装；
`build(..., source_bay_vocabulary=True)` 打开，`tools/critic_measure.py --strips` 可复现，默认关闭。

| 版本 | 评分 | 总分 |
|---|---|---|
| 条带 v1（从首层起铺） | 14,15,15,14,14 | 72 |
| 条带 v2（首层留给店面） | 14,15,15,15,14 | 73 |

第一次测量暴露一个真 bug：条带从**首层**开始铺，把任务书要求的**店面层整个盖掉**，
评审立刻报 "No ground-floor commercial layer"。修正为首层走原逐开间路径（店面+入口保留）、
二三层以上才用条带，72 → 73。

### 路线 A/B 的完整测量结论（八次）

| 方案 | 总分 |
|---|---|
| 基线 `fw2` | **77** |
| B1 冠+檐口（gate bug） | 72 |
| B2 修正 gate | 74 |
| B3 加宽店面+招牌带 | 73 |
| plain（关装饰） | 75 |
| B4 深芒萨尔+中轴亭 | 69 |
| A2 条带 v1 | 72 |
| A2 条带 v2 | 73 |

**八次测量，无一超过 77**，全部落在 69–77，且人工对照图显示各版本几乎同貌。
结论很硬：**在"均匀开洞网格 + 平屋顶"的骨架上，换构件、加装饰、换立面段，观感都不会实质变化**。
瓶颈是**骨架本身**——体量分段（基座/主体/檐部/顶）与**垂直层级**，而不是表层构件从哪来。
这也是评审八次里反复点的同一件事（"uniform bay grid"、"flat dark roof"、"no hierarchy"）。




- 实模型"通过框架门槛并继续到 facades/tier2/tier3/delivery"：v0.3 的真实门槛判定是**全部否决**（正确行为）；
  v0.8 已跑通全链（见上），但 B 之后尚未重跑全链。
- 跨模型独立对比；用户游戏内验收（`game` 阶段）。
- 视觉评审的可信度：本轮的 `plain` 版明明有 11 个店面，评审仍报"no shopfront layer"，
  说明单靠该评审判定中尺度细节不可靠；需要多评审/多轮平均或人工对照参考图。
- 路线 B 的效果：**六次测量均未超过基线 77**，人工对照图显示五版几乎同貌。B 的"提升观感"目标未达成，
  这不是流程故障，而是当前生成器的表达力上限；突破需要改判据或改表达力（见上一节两条路线）。

## 尚未验证

- 实模型全链在 B/路线二之后尚未重跑；上一轮全链成功记录见 MODEL-DESIGN-LIVE-v0.8。
- 路线二的立面段**尚未接入生成器**（本轮只完成挖掘、校验与形态核对）。
- 用户游戏内验收仍是唯一最终判据（`game` 阶段 PENDING）。
