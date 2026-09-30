# ATELIER 逻辑流程 — 交给接手 AI 的开工说明

> 适用对象：**接手运维/主控的 AI**。读完本文即可开工，不需要读完全部源码。
> 配套文档：`reports/ATELIER_HANDOVER.md`（当前状态快照）。本文讲**逻辑**，那份讲**状态**。
> 工程根目录：`巴黎街区素材/paris-builder/`

---

## 0. 先明确角色，别越界

| 角色 | 职责 | 边界 |
|---|---|---|
| **用户** | 提需求、提供参考图、**在游戏内验收** | 唯一有权判定 `game_acceptance` |
| **设计 agent** | 读生成器源码、诊断、改生成器、重跑 | 在流水线内**自动**跑，不是你 |
| **你（接手 AI）** | 监督流水线、**修流程缺陷**、保证门禁自洽 | **不要替设计 agent 设计建筑** |

> **本文所有行号已用 `tools/_check_doc_refs.py` 对源码交叉验证（19 处，0 不符）。**
> 你改完源码后请重跑该脚本，它会告诉你文档里哪些行号已经失效。

用户的原话是：*"不是要你做，而是让你安排 agent 去做，并且你在这个流程当中找出问题并修正。"*
所以你的产出是**流程正确**，不是建筑方案。判断依据永远是**证据**（导出几何、测试、实测数据），
不是散文声明。

---

## 1. 一句话逻辑

```
形制(frameworks) → 立面(facades) → 细化二级(tier2) → 细化三级(tier3) → 交付(delivery) → 游戏验收(game)
   每个阶段都是：  生成 → 技术校验 → 渲染 → 多模态视觉评审 → ┬ 过 → 前进
                                                            └ 不过 → 修生成器 → 重来
```

三条底层设计原则（都是用户明确要求的，**破坏它们就是流程 bug**）：

1. **先形制后细节**：屋顶剖面、体量、开间网格在 frameworks 定死；立面和细节**不允许**反过来掩盖形制错误。
2. **一个阶段只做一个设计**：不搞多候选择优。"五框架竞争并不是五个对比，而是我们只做一个，
   并且要求这一个必须达到要求。"
3. **不合格不前进**：门禁不过就修生成器重来，**不许**把"最不差的那个"放过去。

---

## 2. 状态机与产物契约

阶段列表（`atelier_workflow.STAGES`，第 22 行）：

```
('frameworks', 'facades', 'tier2', 'tier3', 'delivery')
```

`workflow.STAGES` 更长（含 `research / retrieval / game / accepted`），但自动流水线只跑上面五个。

### 每阶段必须齐备的产物（`workflow.REQUIRED`，缺一不可）

| 阶段 | 必需 artifact kinds |
|---|---|
| frameworks | `concept`, `schematic`, `technical_validation`, `views` |
| facades | `assembly_plan`, `schematic`, `technical_validation`, `views` |
| tier2 | `assembly_plan`, `schematic`, `technical_validation`, `views` |
| tier3 | `assembly_plan`, `schematic`, `technical_validation`, `views` |
| delivery | `instructions`, `manifest`, `schematic`, `state_lab`, `technical_validation` |
| game | `state_experiments`, `user_acceptance` |

### 阶段与细化层级的对应

`candidate()` 里一行写死（第 245 行附近）：`tier = {'frameworks': 0, 'facades': 1, 'tier2': 2, 'tier3': 3}[stage]`

**这行是判断"某阶段到底建了什么"的第一现场。** 想知道 tier1 有没有建窗套，就跑
`tools/_tier_probe.py` 看 tier0 与 tier1 的方块差异——不要相信文档或清单。

### 视图集

`workflow.VIEWS` 共 23 张：7 张定视（front/back/left/right/top/axonometric_front/axonometric_back）
+ 16 张环绕（orbit_low/high × 0/45/…/315）。

`frameworks` 阶段只渲染 7 张（`structural = stage == 'frameworks'`，第 300 行附近），
走 `fixed_view_bundle()`；其余阶段 23 张，走 `view_bundle()`。
**这两条路径不能互串**——串了会 `KeyError: 'orbit_street_000'`（踩过）。

---

## 3. 单阶段完整数据流

入口：`run_autonomous()`（第 779 行）。每轮循环做四件事。

### 3.1 `build_stage()`（第 343 行）

```
for (ident, spec) in plans(task):        # frameworks→['frame-1'], facades→['facade-1'], 其余→[(None, ...)]
    if 该候选的产物已齐备: continue        # ← 缓存：产物齐全就跳过，不重建
    candidate(task, out, ident, spec, size, emit)
```

⚠️ **产物是缓存的**。你改了校验代码之后，已存在的候选**不会**用新代码重跑。
要让新校验生效，必须让 revision 前进（修复/回滚）或删掉该候选目录。

### 3.2 `candidate()`（第 242 行）——技术校验在这里

```
operation = Operation('build.' + stage, ...)
if task['generator_version']:                      # 有修复版生成器
    generated = worker(version, 'build', spec, tier, folder)   # 子进程跑修复版
    if generated['status'] != 'PASS': raise ValueError('修复版生成器构建失败：...')
else:                                              # 无修复版，用主库
    scene, manifest = design.build(plan, tier=tier)
    write_schematic(...); repeat, _ = design.build(plan, tier=tier)
    same = 逐格比对两次构建完全一致                  # 确定性
read       = load_schematic(schematic)
validation = read.validation()                     # 1) 文件级：状态完整、无幽灵方块
geometry   = inspect_geometry(read, ...)           # 2) 几何级：连通性、门叶配对
registry   = subprocess.run([node, tools/validate_schematic.cjs, ...], timeout=300)  # 3) 独立注册表
stamp_audit= technique_library.verify_stamp_audit(read, manifest['stamp_audit'])     # 4) 声明 vs 几何
technical  = {'status': PASS/FAIL, ...}
record(...); if FAIL: raise ValueError('Candidate technical validation failed: ...')
render_previews(...) → view_bundle / fixed_view_bundle → record('views', ...)
```

**技术校验失败是"生成器缺陷"，不是"模型不听话"**——它一定对应几何里的真问题。

### 3.3 `agent_review()`（第 494 行）——视觉门禁在这里

```
for candidate:
    scope = 按阶段拼的评审口径（第 ~500 行起，见 §4.2）
    for 每 7 张图一批:
        checked_call('views-N', ...)      # 逐图事实观察，不打分
    checked_call('references', ...)       # 与 5 张参考图对比
    collect_architectural_verdict(...)    # 第 664 行
        ├ groups = 5 个 layer-check + 每个 storey 一个 storey-check（各 8 项 DETAIL_CHECKS）
        └ checked_call('verdict', ...)    # 5 个评分 + 7 个 layer + failure_modes
    row = {...}
    if 任一 check status == 'fail': row['decision'] = 'reject'   # ← 第 625-626 行，硬规则
eligible = 决策 pass 且（非 frameworks 或分数过 gate）
chosen   = 分最高的 eligible；没有就 reject
w.submit_review(task, review)             # workflow.validate_review 再验一遍
if reject: raise ValueError('Agent 阶段检查未通过：...')
else: advance(task)
```

### 3.4 门禁的四种失败与各自的归宿 ← **本节是全文最重要的一节**

| # | 失败类型 | 抛出点 | 谁处理 | 落盘状态 |
|---|---|---|---|---|
| 1 | **技术校验失败** | `candidate()` 第 308 行 | `run_autonomous` 捕获 → 合成 reject → `apply_generator_repair` | 修生成器，继续 |
| 2 | **视觉评审未通过** | `agent_review()` 末尾 | `run_autonomous` 捕获（认 `'Agent 阶段检查未通过：'` 前缀）→ `apply_generator_repair` | 修生成器，继续 |
| 3 | **评审基础设施失败** | `reviewed()` 用尽退避 | 不修生成器 | `awaiting = AGENT_REVIEW_ERROR_<stage>`，**停下可续跑** |
| 4 | **评审要求回滚** | review 里的 `rollback_stage` | `workflow.rollback()` | 回到更早阶段重建 |

另有一条**隐式**路径：生成器修复本身失败（`proposal` 不是 dict、补丁校验不过），
`repair_generator()` 内部有界重试，不污染 run。

---

## 4. 门禁口径（改了这里就等于改验收标准，务必谨慎）

### 4.1 分数门禁

`workflow.SCORE_PROFILES`（**第 17 行**），当前 run 用 `strict`：

```python
'strict':    {'axis_min': 14, 'axis_max': 20, 'total_min': 80, 'mean_min': None}
'aggregate': {'axis_min': 14, 'axis_max': 20, 'total_min': None, 'mean_min': 15.0}
```

**注意**：`score_gate_failure` 目前**只在 frameworks 阶段被强制**（第 634 行）：

```python
eligible = [row for row in rows if row['decision'] == 'pass' and
            (task['stage'] != 'frameworks' or w.score_gate_failure(row.get('scores'), ...) is None)]
```

也就是说 **facades/tier2/tier3 阶段分数不设卡，只看检查项**。这是当前卡点的一半原因（见 §6）。

### 4.2 阶段 scope（`agent_review` 第 ~500 行）

每个阶段一段口径，**这段文字就是评审的验收标准**。历史教训：

- `frameworks` 的口径一直写得很好——有**明确的禁止清单**（"以下缺失 MUST NOT 成为失败项、
  MUST NOT 扣分，请记 `not_applicable`"）。
- `facades` 原本只有一句软话（"栏杆、店面 dressing、粗石属后续 tier2/tier3，不得因其缺失而拒绝"），
  同一段却又要求评审"栏杆、粗石是否真的被使用"——**自相矛盾**，导致评审拿"长阳台铁艺缺失"
  连拒 5 轮，而 tier1 **按设计就不建铁艺**。这就是 §6 卡点的前身，已修。

**改 scope 时的铁律**：任何"后续阶段才做"的东西，必须写成
**"其缺失 MUST NOT 成为失败项、MUST NOT 扣分，请记 not_applicable"**，
不能只写"不得因此拒绝"——模型会把这个软话和后面的要求句做加权，然后判 fail。

### 4.3 事实与判断分离

评审分三步，不要合并：逐图**事实**观察（不打分）→ 与参考图**对比** → **判定**与打分。
`checked_call` 的校验器必须**抛出具体原因**（哪个字段、期望什么、实际什么），
因为该原因会被原样写进下一次重试的 `format_reminder`。只回一句"输出不完整"等于没有重试。

真实案例：模型把 **5 个评分轴**和 **7 个建筑层**搞混，返回 7 个分数
（`scores: [16,12,11,15,15,17,13]`）。改成抛
`'scores must be a list of EXACTLY 5 numbers (one per scoring axis), got 7'` 之后才自愈。

---

## 5. 收敛控制（防止无限烧钱）

`run_autonomous` 第 807 行起：

```python
hard_limit = 8            # 同阶段修复轮次上限
attempts = {}             # 每阶段计数；评审通过时归零
seen_versions = set()     # 见过哪些 generator_version

def budget_check(reason_label):        # 第 839 行，build 失败与评审失败共用
    attempts[stage] += 1
    current = task['generator_version']['id']
    stalled = current in seen_versions          # 生成器版本不再变化 = 修不动了
    seen_versions.add(current)
    if stalled or attempts[stage] > hard_limit:
        awaiting = 'AGENT_BLOCKED_' + stage      # 停下等人工
        raise ValueError(...)
```

**判据是"有没有产出新版本"，不是"跑了几轮"**——只要每轮都产出新生成器版本，
就认为还在收敛，允许继续跑（历史上一轮 run 跑到 22 修订/21 版本却零产出，才加的这道闸）。

`reviewed()`（第 811 行）的退避：`(10, 30, 60, 90)` 秒，
**只对非 `ValueError` 重试**（`ValueError` = 评审结论，必须立刻走修复路径）。

---

## 6. 当前卡点与精确修法（**开工先做这个**）

### 6.1 现象（有数据）

`ATELIER-A9B3C7EE` 卡在 `facades`。评分轨迹：

```
rev 43 → 80  PASS        rev 47 → 76  reject
rev 45 → 81  reject ←┐   rev 48 → 81  reject ←┐
                     └─ 分数都过 80，被检查项拦下
```

失败的检查项清一色是**"视图证据不足"**，不是"几何做错了"：

```
storey-2/storey-4 层间线脚沿两街连续贯通并与切角交圈缺乏视图证据，仅有泛化提及；证据不足记 fail
storey-2/storey-4 窗洞凹陷深度/窗套侧壁缺乏可核验的透视或剖面证据，无法断言凹陷而非齐平，按不确定记 fail
storey-4 与切角的对齐关系无可用视图证实
attic/roof section mansard 陡下坡—坡折—缓上坡剖面在给定视图中不可独立读出
```

### 6.2 根因

评审 scope 里有一条对我**所有**阶段生效的指令：

> "Use side/high/top views and geometric section data; **record uncertainty as fail rather than guessing pass**."

但 tier1 导出的 23 张渲染图**判读不了**"1 格凹深""切角背后线脚连续性""坡折剖面"。
这些需要**测量数据**，而 `technical_validation.geometry` 里只有**连通性/门叶配对**信息
（`face_connected_components`、`largest_component_fraction`…），**没有任何立面剖面测量**。

于是门禁在索取一种它拿不到的独立证据，每轮都停在"不确定 → fail → 硬拒绝"（第 625-626 行）。

### 6.3 修法（治本，推荐）

在 `candidate()` 导出 `.schem` **之后**、`render_previews` **之前**，
从**导出的几何**（不是生成器的散文）测一份 `facade_section` 报告，塞进评审 evidence：

| 字段 | 测什么 | 回答哪个失败项 |
|---|---|---|
| `storey_courses[y]` | 每个层高上突出墙面 ≥1 格的方块，在两条街面各自的最长连续段长度 + 是否绕过切角连续 | 层间线脚连续性 |
| `opening_recess[storey]` | 每个开洞相对墙面的内凹格数（0 = 齐平） | 窗洞凹陷深度 |
| `chamfer_alignment[storey]` | 切角面开洞中心线与两翼开间轴线的关系 | 切角对齐 |
| `roof_profile[sample]` | 沿**垂直于屋脊**的采样线，逐格输出坡面高度序列 | mansard 陡下坡—坡折—缓上坡 |

然后在 scope 里加一句：

> 这些属性以 `facade_section` 的**实测值**为证据；渲染图被遮挡不构成 fail，
> **只有实测值不成立才记 fail**。

**为什么这是对的**：测的是导出几何本身，和渲染图同源，所以不是放松标准——
是把"看不见"和"做错了"分开。评审仍然不能凭空给 pass。

### 6.4 修法（备选，弱，不建议单用）

在 scope 里写："当某属性无法由给定视图集判读时，记 `not_applicable` 并在 observation 里
写明无法判读的理由，**不要记 fail**；只有几何确实错误或缺失才记 fail。"

风险：给了评审放水的口子，会重蹈用户此前批评的"审得比 agent 还松"。

### 6.5 收敛现状

立面阶段已用掉 2 轮修复（上限 8）。**若 §6.3 不做，很可能在余下轮次内反复拿到 76~81 分后
`AGENT_BLOCKED_facades` 停下**——这是设计好的"停下等人工"，不是崩溃。

---

## 7. 不变量（碰了就是真 bug）

1. **生成器只允许改白名单模块**：`generator_repair.MODULES`（第 19 行）=
   `design.py / house.py / facade.py / technique.py / haussmann_reference.py / technique_library.py`。
   每次修复产出**新的不可变版本**，写在 `runs/<RUN>/generator-versions/<sha>/`，
   `task['generator_version']` 指向当前版本；**永不覆盖旧版本**（要能回滚）。
2. **`validate_edit()` 的约束**：只能**新增** `technique_library` 相关 import，
   删改既有 import 一律拒绝。改测试、改校验、改门禁阈值、改验收——全部禁止。
3. **冻结状态**：导出 `.schem` 必须**显式写全每个方块的状态**，因为游戏内粘贴时
   方块更新是**关闭**的（靠更新生成的手法在禁止更新下会失效）。
   禁止更新下必须逐格冻结的格数：**53,000+**。
4. **门叶必须成对**：源作品里大量门被导出成两格都是 `half=lower`，
   禁止更新下粘出来是两截半门 → 交付级缺陷。技术校验会抓（现场已真实触发并修好）。
5. **`game_acceptance` 只能用户填**，系统与模型一律 `PENDING`；页面也不得把 PENDING 渲染成完成。
6. **改 `src/` 之后必须重启 8765 服务**：长驻进程**不热加载**，否则用旧代码跑出无效候选。
7. **`Scene.volume` 存的是调色板索引，不是状态字符串**：
   正确读法 `palette[int(volume[y,z,x])]`，且 shape 是 `(height, depth, width)`。
   当字符串读会谎报"0 个开口"（城市层犯过两次）。
8. **manifest 的散文声明一律不可信**，包括被审计过的部分。
   判断"某能力是否真的接进来了"必须看**导出几何**。
   已提供的工具：`technique_library.verify_stamp_audit(read, manifest['stamp_audit'])`。

---

## 8. 命令速查

```powershell
cd "C:\Users\blackvccat\Desktop\巴黎街区素材 4\巴黎街区素材\paris-builder"
$env:PYTHONPATH='src'
```

### 8.1 重启服务（改过 src 必做）

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-Sleep -Seconds 3
Start-Process -FilePath "C:\Python312\python.exe" `
  -ArgumentList "-u","tools\serve_learning.py","--port","8765" `
  -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput "runs\LEARNING-WORKBENCH-v1\ux-server.stdout.log" `
  -RedirectStandardError  "runs\LEARNING-WORKBENCH-v1\ux-server.stderr.log" `
  -PassThru -WindowStyle Hidden
```

### 8.2 续跑（幂等，保留已积累的生成器版本）

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/workflow/autonomous' -Method Post `
  -Body '{"run":"ATELIER-A9B3C7EE"}' -ContentType 'application/json'
```

### 8.3 看状态

```powershell
# 一行状态
python -u -c "import io,json;w=json.load(io.open('runs/ATELIER-A9B3C7EE/workflow.json',encoding='utf-8'));print(w['stage'],w['revision'],w.get('awaiting'))"

# agent 推理链（页面右上「轨迹」同源）
#   runs/LEARNING-WORKBENCH-v1/agent-sessions/e507b24d1f14410b.json  → kind == 'agent_progress'

# 某候选的技术记录（含 stamp 审计）
#   runs/ATELIER-A9B3C7EE/revision-<N>/<stage>/<candidate>/technical_validation.json

# 某个生成器版本到底改了什么
#   runs/ATELIER-A9B3C7EE/generator-versions/<sha>/version.json
```

### 8.4 诊断探针（本轮新增，都在 `tools/`）

```powershell
python -u tools\_tier_probe.py       # 逐 tier 几何差异（判断"这阶段到底建了什么"）
python -u tools\_provider_probe.py   # 模型连通性 + 余额
python -u tools\_vision_probe.py     # 用真实评审图跑一次视觉调用（区分"网络问题"与"代码问题"）
python -u tools\_check_doc_refs.py   # 本文档行号是否还对准源码（改完代码就跑它）
```

### 8.5 测试

```powershell
python -u -m unittest discover -s tests -p "test_*.py"      # 期望 170 通过 / 5 跳过
```

⚠️ **必须**用 `discover -s tests`。`python -m unittest tests.test_x` 会被 site-packages 里的
`ultralytics` 抢走 `tests` 包名，报 `ImportError: cannot import name 'ASSETS'`。

---

## 9. 不要做的事（都是踩过的坑）

1. **不要把"不确定"直接判 fail，也不要直接判 pass**。见 §6——要补证据，不是放松要求。
2. **不要在 `build_stage` 之外直接调 `design.build` 去"看看效果"**：产物是缓存的，
   你看到的不一定是流水线用的那份。要看得走 `_tier_probe.py` 或直接 `load_schematic` 读产物。
3. **不要用 `Select-String`/grep 判断"某库是否被接入"**。本轮就吃过这个亏：
   grep 到 `from .technique_library import registry` 就以为接进来了，
   实际生成器把 `len(registry())` 存进一个**从未使用的局部变量**，导出几何里一个库方块都没有。
4. **不要用 `Select-Object -First N` 截断 python 输出**：会中断管道、中文乱码。
5. **不要每次改完 src 就跑长任务**：先跑 §8.5 的测试（约 53 秒）。
6. **不要在没有证据的情况下说"已交付"**。当前状态是：**无交付物，`game_acceptance` PENDING**。
7. **不要合并两条生成路径**（除非你打算重做立面层）：
   当前活跃路径是 `design.build → detail_profile=='reference_haussmann' → haussmann_reference.build → build_corner`，
   它**没有独立立面层**，tier 0/1/2/3 硬编码在一个函数里；
   通用路径 `house.FORMS → facade.SCHEMES → technique` 与之并存。合并是大工程，别顺手做。
8. **风格维度（巴黎/日式/中式）暂缓**：用户明确说"当前我只是先验证巴黎，后续是其他"。

---

## 10. 开工顺序建议

1. 读本文 §6，确认当前卡点没变（`workflow.json` 的 `stage` / `awaiting`）。
2. 按 §8.1 重启服务（**现在服务是停的**），按 §8.2 续跑，观察是否还在 §6 的循环里。
3. 做 §6.3 的 `facade_section` 实测报告（这是唯一能真正解开当前死结的改动）。
4. 实施后跑 §8.5 测试 → 重启 → 续跑 → 观察 `facades` 是否能过。
5. `facades` 过后注意 **`tier2` 只跑过一次（rev 43）就因屋顶结构问题回滚到 frameworks**——
   **屋顶剖面（mansard 陡下坡—坡折—缓上坡）是反复出现的失败主题**，
   在 frameworks 与 facades 都出现过。§6.3 的 `roof_profile` 应优先覆盖它。
6. 走到 `delivery` 后，交付物在 `runs/<RUN>/revision-<N>/delivery/`，
   打包为 `delivery.zip`；**然后停下等用户在游戏内验收**，不要自己填 `game_acceptance`。
