# PAR-002 巴黎建筑生成：工作流程与交接说明

> **2026-09-26 源库纠错优先：** 3d节及旧细节报告的“97.9%实心填充”结论由空气调色板编号错误造成，已撤回。空气必须按方块名识别。不得默认把门叶 `half` 改成成对门：街区3使用门叶作薄窗面。参考源新拆件、84件历史裁件待重拆清单和已核对的状态清洗见 `paris-builder/reports/REFERENCE_DECOMPOSITION.md`；v3源裁件优先，游戏验收仍未运行。

> **2026-09-26 Atelier 转角任务已走到交付（新增）：** `runs/ATELIER-54E0BBBA` 从 research 走到
> **`stage = game`（等待用户游戏内验收）**，逐阶段视觉评审与交付独立复核见
> `paris-builder/reports/ATELIER_54E0BBBA_DELIVERY.md`。过程中门禁暴露并修复了三个真实缺口：
> ① 生成器没有“相邻两面沿街 + 相邻两面共墙”的形式 → 新增 `corner_house` 与
> `haussmann_reference.build_corner()`（`reports/ATELIER_CORNER_FORM.md`）；
> ② 底层店面与住宅窗共用开洞与窗套 → 店面专属语汇（连续橱窗带、门槛石、木招牌带、橱窗竖框）
> 与楼层窗高分级 6/5/4/3（`reports/ATELIER_SHOP_BASE.md`，由用户指出）；
> ③ `facade-3(palace_front)` 曾与 `facade-1` 渲染逐字节相同（转角构建器缺该方案分支），已补齐。
> **两条操作教训**：改 `src/` 之后必须重启 8765 服务，长驻进程不会热加载（否则重跑出无效候选）；
> 长管道读取会中断渲染，别用 `Select-Object -First N` 截断 python 输出。
> 未完成边界：转角无切角门面；`build()`（street_house）未同步店面语汇；游戏验收保持 PENDING。

> 给后续接手此任务的 AI：先通读本文件，再动手。用户验收在游戏内，未合格不要汇报。
> **旧线 PAR-001 已弃用**，全部归档在 `paris-builder/archive/PAR-001/`，只作追溯，不再迭代。
> **当前工作机已从作者的 macOS 换到 Windows**：接手前先读 `paris-builder/reports/WINDOWS_PORT.md`，
> 并按第 5 节在 Windows 上重新跑自检；`.venv/` 是 macOS 3.9 虚拟环境，Windows 用系统 `python`。

## 0. 任务与验收标准

- 目标：按 `paris-builder/WORKFLOW_STYLE_LEARNING.md` 的分层工作流，生成新建筑 **PAR-002** 与状态试验件 **STATE-LAB**，导出 `.schem`，目标 **MC 1.21.11 / DataVersion 4671**。
- 锁定要求见 `paris-builder/reports/PAR-002_execution.md`：生成系统与新建筑双交付；43 窗全部标注；14 源作品手法覆盖及排除理由；全谱系每族至少 3 变体；5 框架与 3 立面竞争；分三级细化；所有可见方向和院落、屋顶均设计；最后交用户在游戏内验收 PAR-002 与 STATE-LAB。
- 交付标准 = **强制对照**（每次生成后必须逐张对比，未对比不许继续）：
  - `参考图/标准_巴黎建筑素材2_外立面_正视.png`、`参考图/标准_巴黎建筑素材2_外立面_轴测.png`
  - `参考图/标准_巴黎民居街区3_外立面_正视.png`、`参考图/标准_巴黎民居街区3_外立面_轴测.png`（街面=back/z_max 视角，Front 视角露出的是未完成面，勿用）
  - `参考图/窗对照总览_街面.png` / `窗/`（43 个窗拆件；分解件的可视面=室外，即 axonometric_back 视角是街面）
- 硬规则：
  1. **每次生成后必须自己看渲染图**（至少与标准同视角的正视+轴测，再逐张过七视角），再写分析。
  2. 分析出问题就**继续改**，直到合格再来叫用户；**不许中途只汇报**。
  3. 用户只在游戏内粘贴/验收；最终合格由用户判定，代码与校验 PASS 不等于用户认可。

## 1. 目录与关键文件（弃用旧版后）

| 路径 | 说明 |
|---|---|
| `paris-builder/WORKFLOW_STYLE_LEARNING.md` | 强制工作流 G0–G8（本项目的流程规范） |
| `paris-builder/reports/PAR-002_execution.md` | PAR-002 锁定要求与真实进度（每轮更新） |
| `paris-builder/knowledge/styles/paris_haussmann_v0.1.json` | 现实建筑原型层（不含方块名与单栋坐标） |
| `paris-builder/knowledge/library-v1/` | 构件库：43 窗标注、14 源作品状态清点、14093 去重上下文裁件、45 族×3 变体 recipe、catalog；上下文不等于全语义拆件 |
| `paris-builder/src/paris_builder/production.py` | 框架/立面/细化的生成核心（按 stage 1–3 分层） |
| `paris-builder/src/paris_builder/architecture.py` | Scene / FaceGraph / 状态变换 / 冻结状态清单 |
| `paris-builder/src/paris_builder/preview3d.py` | 预览渲染（真实方块模型，七视角+环绕） |
| `paris-builder/tools/build_par002.py` | 构建入口：`frameworks / facades / tier / deliver` |
| `paris-builder/runs/PAR-002-vX.YY/` | 每版产物：`framework.schem` 或 `PAR-002.schem`、验证报告、`previews/*.png` |
| `paris-builder/runs/STYLE-LEARNING-PILOT-v0.1/` | 流程可行性试验（旧，供追溯） |
| `paris-builder/archive/PAR-001/` | 旧线全部材料（run、规格、旧报表、旧生成器、旧 grammar） |
| `巴黎建筑素材/`、`巴黎建筑修改版/`、`窗/` | 只读源素材，不要修改（构件库证据路径依赖这些目录名） |
| `参考图/` | 标准对照图 4 张 + 窗对照总览_街面.png（强制对照用） |
| `_原始压缩包/` | 源素材原始 zip 备份 |

## 2. 每轮迭代固定流程（不可跳步）

**Windows 自检优先**（首次接手或换机后必跑，可重复执行）：

```powershell
# 本机只有 Windows PowerShell 5.1（没有 pwsh），用：
powershell -NoProfile -ExecutionPolicy Bypass -File paris-builder\tools\setup_windows.ps1
# 装了 PowerShell 7+ 则可用：
pwsh -File paris-builder\tools\setup_windows.ps1
```

它做的事：装依赖 → 检查 UTF-8 文本 I/O → 检查 Node/字体解析 → 跑全部单元/回归测试 → 跑交付包独立复核。
下面每一步都假定已执行 `cd paris-builder` 且设置 `$env:PYTHONPATH = 'src'`。

```powershell
cd paris-builder; $env:PYTHONPATH = 'src'

# 1) 框架竞争（5 套种子） / 立面竞争（3 方案） / 三级细化 / 交付
python tools\build_par002.py frameworks --run PAR-002-vX.YY
python tools\build_par002.py facades   --seed 6521 --run PAR-002-vX.YY
python tools\build_par002.py tier      --seed 6521 --scheme 1 --stage 2 --run PAR-002-vX.YY
python tools\build_par002.py tier      --seed 6521 --scheme 1 --stage 3 --run PAR-002-vX.YY
python tools\build_par002.py deliver   --seed 6521 --scheme 1 --run PAR-002-vX.YY

# 2) 自看预览（必须逐个视角）：
#    runs/PAR-002-vX.YY/**/previews/{front,back,left,right,top,axonometric_front,axonometric_back}.png

# 3) 对照四张标准图 + 窗对照总览_街面.png，写差距分析

# 4) 交付后复核（不改动任何交付文件）：
python tools\verify_delivery.py --out runs/PAR-002-vX.YY/delivery_verification.json

# 5) 更新 reports/PAR-002_execution.md、README.md 的当前候选指针
```

模型驱动的完整阶段链（可选，与上面的确定性构建独立）：

```powershell
# 离线夹具：无网络跑通 research→retrieval→frameworks→facades→tier2→tier3→delivery
python tools\model_design_run.py --run MODEL-DESIGN-REPLAY-FULL-vX --action all `
  --provider configs\providers\replay.force-pass.json --size 80
# 离线夹具：验证"选中候选被否就停在原阶段"（应只跑 1 个动作）
python tools\model_design_run.py --run MODEL-DESIGN-REPLAY-vX --action all `
  --provider configs\providers\replay.json --size 80
# 实模型（需要 DEEPSEEK_API_KEY 与预算；产物才算实跑证据）
python tools\model_design_run.py --run MODEL-DESIGN-vX --action all `
  --provider configs\providers\deepseek.run.json --size 480
```

不合格 → 回到修改（`production.py` 或 `knowledge/`）→ 再走 1)–5)。合格 → 才向用户报告请求游戏内验收。

## 3. 已知坑（踩过的，别重犯）

- **状态必须显式完整**，否则独立 JS 校验 FAIL；`up=false` 且四向无连接的 wall 是幽灵方块，游戏内无模型，断缝至少留一侧 `low`。
- 预览必须用模块方式：`PYTHONPATH=src python -m paris_builder.preview3d`（直接 `python src/...` 会 ImportError）。
- 视角：**街面 = north/south**；街区3 标准 = `back/axonometric_back`；窗拆件的可视面 = 室外。
- `.schem` 只能保存状态，不能命令粘贴器关闭更新；游戏内粘贴必须由 WorldEdit/FAWE/服务端工具关闭邻接与方块更新，否则特殊模型可能重算。
- 冻结状态（强制 `outer_left/outer_right` 楼梯、单向 `low/tall` 墙肢、仅沿立面连接的玻璃板）只放在有明确建筑作用的位置，不要全墙铺开。
- 白色过量是雷区；使用兼容材族与多种窗构件，变奏服从面与楼层层级，禁止逐方块随机。
- 不要照抄 `巴黎民居街区素材/房子01–30` 的极简语汇。
- **`Scene.volume` 存的是调色板索引，不是状态字符串**：`str(volume[y,z,x])` 得到的是 `'6'`、`'7'`；
  正确读法是 `split_state(palette[int(volume[y,z,x])])`。把它当字符串读会谎报「0 个开口」（城市层犯过两次）。
- **判读街面不要用整排正视**：1000px 塞 200 格 = 5px/格，必然判读失败；用
  `tools/render_street_view.py --crop`，一次只看 1–3 户。北排街面在自身 `z_max`，转 180° 后 `front` 相机看到的正是它。
- **街面开口必须写在街道看得见的那一层**（`z = 地块立面线`）：街墙只有 1 格厚时，`z0+oz` 已经在街上，
  玻璃会被后写的内衬覆盖，于是「整条街没有窗」。
- 交付包冻结：`production.py` 的任何新行为都必须留在框架路径或显式参数之后，`PAR-002-v0.4` 保持字节复现。

## 3b. 单栋房屋设计生成：三层分离（本轮主任务，2026）

用户要求：*技法、立面样式、建筑结构是三份独立数据库*，先把「单栋房屋设计生成」做好，
再谈成为城市。落地为四个模块，完整记录见 `paris-builder/reports/HOUSE_DESIGN_LAYERS.md`。

| 层 | 文件 | 只负责 |
|---|---|---|
| 结构 | `src/paris_builder/house.py` | 体量：7 种形式（`street_house` / `corner_house` / `street_row` / `apartment_block` / `court_palace` / `civic_hall` / `slope_terrace`），参数取自 14 源实测。`corner_house` = 相邻两面沿街 + 相邻两面盲共墙，2026-09-26 新增（此前全项目没有任何形式能表达转角地块） |
| 立面 | `src/paris_builder/facade.py` | 构图：5 种方案，只决定开口位置与节奏，不含方块名与体量 |
| 技法 | `src/paris_builder/technique.py` | 方块与状态：10 种技法，前两个形参一律是 `(scene, wall)`，因此可作用于任何形式 |
| 装配 | `src/paris_builder/design.py` | 唯一同时知道三层的地方，顺序必须是 结构→立面→技法 |

```powershell
cd paris-builder; $env:PYTHONPATH = 'src'
python tools\design_house.py --matrix --json runs\HOUSE-DESIGN-vX\matrix.json   # 6×5 全组合正交性
python tools\design_house.py --form street_row --seed 1900                      # 单栋详情
python tools\check_house_facade.py --form street_house --seed 1900              # 街面实测
python tools\house_sheet.py --run HOUSE-DESIGN-vX --column form --scheme haussmann_apartment --size 1200
python tools\compare_reference.py --run HOUSE-COMPARE-vX --reference street3 `
  --form street_row --scheme haussmann_apartment --width 56 --depth 26 --storeys 6 `
  --px-per-block 7 --crop-blocks 56 --x-frac 0.15 --crop-top 0.1 --crop-bottom 0.95
```

**技法层的写入顺序就是正确性**：`window_surround` 若先于 `shopfront` 跑，会在店面玻璃上写一条
窗台带，店面当场从街面消失。按元素归属排序（店面/门先做，通用窗套只管普通窗）。
同理，一个形式若有多套剖面（退台建筑），每面墙只能组合**它自己高度以内**的楼层，否则会在屋顶之上开门。

## 3c. 城市层（2026）

单栋生成器永远只能产出一栋独立公寓楼，14 源里的连续街墙/转角楼/公共建筑复现不出来。城市层
（`src/paris_builder/city.py` + `tools/build_city.py` + `knowledge/city/`）补这一层，只负责
街道/地块/形式选择，不含单栋体量与立面构图。完整记录见 `paris-builder/reports/CITY_LAYER.md`。
**注意：城市层目前仍带自己的一份街面构图代码，尚未改用 3b 的三层系统，这是已知待办。**

```powershell
python tools\build_city.py --run CITY-vX.Y --seed 1900 --length 200 --size 1000
# 判读街面（务必裁剪）：
python tools\render_street_view.py runs\CITY-vX.Y\CITY.schem --out runs\CITY-vX.Y\house --crop 40 72 0 47
python tools\sample_preview_colors.py runs\CITY-vX.Y\house\street_face.png
```

门禁：`status` 含 `street_face`（此前只有文件与几何校验，两者 PASS 也可以是一面没有窗的墙）。
判据：玻璃占比 ≥10%、窗组 >0、街面层 0 空格，逐地块只量到自己的檐口。

## 3d. 细节数据库 v2：43 个源文件的清洗入库（2026）

用户交来 43 个 `.schem`（`_incoming_schematics/`：窗 9、民居街区 7、建筑素材 7、房子极简版 20），
要求把细节拆建进细节数据库。产物 `knowledge/library-v2/details/`（**770 件**，每件一个目录 +
`detail.schem`），完整记录见 `paris-builder/reports/DETAIL_LIBRARY_INTAKE.md`。
`knowledge/library-v1/` 是 PAR-002 的记录证据，**未被改动**。

```powershell
cd paris-builder; $env:PYTHONPATH = 'src'
python tools\survey_incoming.py --json runs\DETAIL-INTAKE-vX\survey.json   # 测量+判定+排除理由
python tools\extract_details.py --limit-per-source 40 --write-schem        # 抽取与导出
python tools\check_frozen_details.py --json runs\DETAIL-INTAKE-vX\frozen_check.json
```

判定按**类**分别做，不用一个阈值套所有：实心填充（填充率 ≥0.95）排除；构件类（每轴 ≤8）
不因小而排除，看有状态占比；建筑类看有状态占比是否 ≥0.06。43 件源 → **28 入库 / 15 排除**，
排除理由逐条入账。

### 硬规则：方块禁止更新

**有些手法是靠方块更新产出的，而粘贴环境禁止方块更新**，所以导出件必须自带正确状态，
不能指望游戏重算。禁止更新下必须逐格冻结写入的格数：**53,000+**（墙连接 1835、门 839、
楼梯形状 637、铁栏连接 416、玻璃板连接 244…）。

真实缺陷：源作品里大量门被导出成**两格都是 `half=lower`**（建时靠更新纠正成 upper，导出冻结
了那一刻的状态）。禁止更新下粘出来是两截半门。处理：导出前规范化为 lower/upper 配对
（**清洗 687 格**，原始状态留在 `normalisations.original_door_states`）；**裁剪边界切断、无法
配对的门整件拒绝**（555 条排除里含这类），绝不留半扇门出厂。

抽取三个坑：锚点表里放 `wall`/`slab`/`stairs` 会让连通生长吃掉整栋楼（出现 190×55×125 的
"窗"）；生长必须只走锚点格（不能穿过石墙）；封口函数若在**全图**找同名门会把裁剪框撑到
19×6×24，必须只允许接触当前框的格拉框。

残余缺口：`shopfront` 与 `roof` 两类锚点本轮 0 产出；`--limit-per-source 40` 是按需截取，
大源还能取更多；**770 件尚未接进 `technique.py`**，还没有被立面层按开间/楼层选取。

## 3e. 建筑 agent 网页（2026）

用户要求把流程做成一个前端网页。形态：**独立可访问的网页**，走 `webServer` 注册路由，
实现为一个动态 Cordis Plugin（仅宿主半边，包 `build-1`）。地址
**http://127.0.0.1:3080/building**，完整记录见 `paris-builder/reports/BUILDING_AGENT_UI.md`。

**架构第一原则：不新建数据库。** `runs/<RUN>/` 下的报告、预览图、校验收据已经是真相源，
页面只做投影——门禁算自报告字段、测量值取自报告、图片读自产物目录。命令行重跑之后页面自动
正确，不存在「界面显示通过但文件不是那样」的可能。

**宿主受限环境的四条硬约束**（都是本机实测出来的，不遵守就是坏页面）：

1. 动态 Host 半边只有 `ctx`/`harness`/`console`/`btoa`/`atob`/`TextEncoder`/`TextDecoder`：
   没有 `process`、`Buffer`、`fetch`、`setTimeout`、**`URL`**，也没有 Node 内建模块。
   文件走 `ctx.fs`、进程走 `ctx.shell`、计时走 `ctx.timer`；查询串手写解析。
2. **`ctx.fs` 的相对基准是 harness 的 Desktop，不是会话工作目录**。项目在
   `Desktop/巴黎街区素材 4/巴黎街区素材/paris-builder`，所以相对候选会全部落空；
   正解是从 `workspaceRegistry.list()` 推导工作区路径再拼子目录。
3. 图片不能直接回（无 `Buffer`）：资产端点返回 base64，页面转 blob URL。
4. 子进程输出三件套缺一不可：`python -u`（否则管道块缓冲，输出拖到进程结束才出现）、
   `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`（否则 Windows 无控制台时按 GBK 写、按 UTF-8 解码丢内容）、
   `2>&1`（脚本进度与错误多在 stderr）。

**验收通道**：`POST /building/api/acceptance` 是唯一写入 `runs/<RUN>/user_acceptance.json`
的入口，记录带 `authority: "USER_ONLY"`。系统与模型不得代为填写，界面也不得把 PENDING
渲染为已完成；无记录时显示 PENDING 是默认态。

执行与命令行等价（`python -u tools/<tool> <args>`），参数从该 run 的 `design_seeds.json` 推导。
插件停止时统一 kill 子进程；动态插件不跨进程重启，重启 DSH 后需 `cordis_run` 重新激活。

未完成：只有单阶段执行（没有一键整链+门禁停机）、输出靠轮询（无推送）、没有把
`compare_reference.py` 的同尺度对照做成默认视图、排除理由与冻结判读只能看原始 JSON。

## 4. 当前状态（PAR-002-v0.4）

- 五框架（种子6101/6211/6317/6421/6521）和三立面已完成渲染评审；选6521、方案1。细化一级为facades/1，二级tier-2，三级tier-3。delivery内为游戏验收候选双包，150个状态实验格（45度转角顶层阳台断口修复后新增3格）。
- 评审文件为framework_review.json、facade_review.json、detail_review.json；detail_review只允许进入游戏候选交付，不是最终认可。
- 178件生产构件文件独立检查PASS；954次最终构件装配没有整件覆盖；全14源语义穷尽尚未证明，不要混淆状态索引与构法理解。
- 所有 `game_acceptance`、构件库 `game_validation` 均为 **NOT_RUN/PENDING**；用户尚未游戏内验收。
- 24项单元/回归测试PASS。已补充14源全部1753113个非空气位置的局部扫描，697298个独特上下文保留源坐标及排除理由；不要冒称宏观语义全部学会。下一步根据用户的实验编号、局部坐标与视角诊断，回退相应阶段，不继续无目的叠装饰。
- 最终交付审计件在 `delivery/`：`需求-证据对照表.md`（计划逐条→证据，含PASS/PARTIAL/PENDING）、`逐视图诊断.md`、`变更记录.md`。checksums 102项已重算一致。除用户游戏内判定（状态更新A/B、区块重载、审美）外，其余要求均有文件/回归级证据；K3/K6/V5 边界为语义穷尽NOT_PROVEN、游戏验证PENDING、原创性抽样。

## 5. Windows 接手状态（在本机复核过，2026 交接）

- 本机自检：`powershell -NoProfile -ExecutionPolicy Bypass -File paris-builder\tools\setup_windows.ps1`
  （本机只有 Windows PowerShell 5.1，没有 `pwsh`；脚本本身已改为纯 ASCII 以免中文路径被 ANSI 读坏）；
  当前 **101 项单元/回归测试通过**（含 `tests/test_design.py` 14 项三层分离与写入顺序回归、`tests/test_city.py` 6 项城市层回归），UTF-8 文本 I/O 检查 0 缺失（129 处）。
- 交付包**未被修改**，独立复核 PASS：`runs/PAR-002-v0.4/delivery_verification.json`
  （102 项校验和一致、PAR-002.schem 与 STATE-LAB.schem 的 Python 回读 + prismarine 独立注册表 + 几何全 PASS、
  按 concept+seeds **字节级复现**交付 schem、150 个实验格中心状态一致、`交付/PAR-002-v0.4-游戏验收.zip` 103 个条目与 `delivery/` 逐字节一致）。
- 已修的真实缺陷（详见 `paris-builder/reports/WINDOWS_PORT.md`）：Windows GBK 破坏 UTF-8 读写、打包脚本硬编码 macOS 字体、
  本机 TrueType 渲染会硬崩溃（改为子进程探针 + 点阵回退）、POSIX 专用 Node/Keychain 解析、manifest 绝对路径、子进程输出编码。
- 执行器已补齐完整阶段链：`--action all` 走 research→retrieval→frameworks(5)→facades(3)→tier2→tier3→delivery，
  门槛不通过就停在原阶段；离线夹具 `configs/providers/replay.json` 的产物只能当测试夹具，不能当实模型证据。
- **仍然 NOT_RUN**：游戏内粘贴/更新 A/B/区块重载与审美验收（只能由用户判定）；本轮按用户意见以渲染图逐视角检查代替。
- **实模型已跑通完整阶段链**：`runs/MODEL-DESIGN-LIVE-v0.8` 真实跑通
  research→retrieval→frameworks→facades→tier2→tier3→**delivery**，停在 `game` 门槛；
  93 次真实调用 / 563k tokens；交付产物可用自身 concept+种子**字节复现**
  （`runs/MODEL-DESIGN-LIVE-v0.8/delivery_verification.json` PASS，140 个状态实验格）。
  评分口径记录在 `task['score_profile']='aggregate'`（五轴 14..20 且均值 ≥15.0）；
  细节层需要多轮重设计才收敛（`--attempts` / `max_stage_calls` 是必要预算控制）。
  密钥只用环境变量 `DEEPSEEK_API_KEY` 传入，未落盘。
