# ATELIER 交接文档 — 巴黎转角建筑自动设计流水线

> 生成时间：2026-09-28 15:40
> 运行标识：`ATELIER-A9B3C7EE`
> 交接范围：`paris-builder/` 自动设计流水线的**流程正确性**与当前卡点
> 阅读顺序：§1 现状 → §5 当前卡点 → §6 下一步。§4 是本轮已修的流程缺陷，供追溯。
> **配套文档：`reports/ATELIER_WORKFLOW_LOGIC.md`（逻辑流程 + 开工说明，行号已交叉验证）。
> 要把活交给另一个 AI，先给它那一份，本文作为状态快照补充。**

---

## 1. 一句话现状

**流水线本身现在是通的、可自动跑的、发现真问题的**；但**交付物尚未产出**：建筑卡在 `facades`（立面）
阶段第 48 修订，第 9 次立面评审。评分已达到门槛（81/80），却被"任一检查项 fail 即拒绝"的硬规则拦下。
**当前服务已停止**（8765 无监听），需要按 §7 重启 + 续跑。

**没有交付，`game_acceptance` 保持 `PENDING`，用户尚未游戏内验收。**

---

## 2. 交付物与验收状态

| 项 | 状态 |
|---|---|
| 建筑 `.schem` 交付包 | **未产出**。`delivery.zip` 仅在走完全部门禁后才存在 |
| 状态试验件 `STATE-LAB.schem` | 未产出（依赖交付阶段） |
| 自动评分门禁 `score_profile = strict` | 每轴 14..20 且总分 ≥80 |
| 各阶段门禁 | frameworks 已过；**facades 未过**；tier2 未过；tier3 未开始 |
| `game_acceptance` | **PENDING**（只能由用户在游戏内判定，系统不得代填） |
| 单元/回归测试 | **170 项通过，5 项跳过**（跳过的 5 项是"五候选竞争"旧夹具，等重写） |

### 已确定的建筑方案（`selected.frameworks`）

```json
{"form": "corner_house", "scheme": "haussmann_apartment",
 "width": 24, "depth": 30, "storeys": 6, "seed": 1900,
 "detail_profile": "reference_haussmann", "bay_pitch": 6,
 "entrance_fraction": 0.5, "roof_height": 9, "chamfer": 6}
```

相邻两面沿街（北 `z_min`、东 `x_max`），相邻两面为盲共墙（西、南），转角切除 `chamfer=6`（pan coupé）。

---

## 3. 运行状态（数字）

```
stage          : facades            revision : 48
awaiting       : VISUAL_REVIEW      generator: ade35453498e
generator 版本 : 48 个              last write: 10:13:47
评审总数       : 49                 artifacts: 12
review_policy  : layered-v2         execution_mode: autonomous
```

各阶段评审轨迹：

| 阶段 | 评审次数 | 最后一次 | 评分 |
|---|---|---|---|
| frameworks | 37 | rev 45 **pass** | `[18,18,18,18,17]` |
| facades | 9 | rev 48 reject | `[16,17,15,16,17]` = **81** |
| tier2 | 1 | rev 43 reject | 触发回滚到 frameworks |
| tier3 | 0 | — | 未开始 |

**立面评分收敛轨迹**（总分 / 门槛 80）：

```
rev 15 → 12      rev 30 → 39~40    rev 43 → 80  PASS
rev 17 → 47      rev 40 → 55       rev 45 → 81  reject  ← 分够，被检查项拦下
rev 29 → 45                         rev 47 → 76
                                    rev 48 → 81  reject  ← 同上
```

即：**分数已经达标，卡的不是分数**（详见 §5）。

---

## 4. 本轮已修的流程缺陷（7 项，均已测试通过）

这些是"让流水线能自己跑对"的修复，都在 `src/paris_builder/` 内。

### 4.1 立面评审门禁自相矛盾 → 无解循环（**根因级**）

`atelier_workflow.py` 的评审 scope 里，立面阶段写的是"栏杆、店面 dressing、粗石属后续 tier2/tier3，
不得因其缺失而拒绝"，但同一段又要求评审"栏杆、粗石、隅石是否真的被使用"。评审把这个矛盾判成了
拒绝——`rev 30/40` 的失败项里反复出现"长阳台铁艺缺失""檐口托饰缺失"，而这两项 tier1 **本来就不建**。

实测证据（`tools/_tier_probe.py`）：

```
tier 0 (frameworks): 11909 blocks, 11 种方块
tier 1 (facades)   : 12251 blocks, 13 种方块   ← +342
  cut_sandstone   0 → 217   (窗套)
  sandstone_slab  16 → 841  (窗台/线脚)
  sandstone_wall   0 → 380  (栏板)
```

**修法**：给 `facades` 阶段补上与 `frameworks` 同等强度的**禁止清单**，逐项点名
"其缺失 MUST NOT 成为失败项、MUST NOT 扣分，请记 `not_applicable`"；并把"完整词汇在 tier2/tier3
才判"写成条件分支，不再对框架/立面阶段生效。

**效果**：修复后首次评审即通过（rev 43，`[16,17,16,16,15]` = 80，正好压线）。

### 4.2 一次 provider 返回坏 JSON 就整轮 run 猝死

`agent_review` 的 verdict 批（最后一批）连续 3 次校验失败就抛异常，把整个 run 带走，
`awaiting` 还停在旧值上（现场：`operations/1a6e2442443645c19a7f1a9d1bbc3750/raw_reply_21.txt`）。

同时发现真实误因：模型把 **5 个评分轴**和 **7 个建筑层**搞混，返回了 7 个分数
（`verdict-1.json` → `scores: [16,12,11,15,15,17,13]`），而校验器只回一句"输出不完整"，
重试提示里没有任何有效信息。

**修法**：
- verdict 的校验器改为**抛出具体原因**（"scores must be a list of EXACTLY 5 numbers … got 7"），
  该原因会被原样写进下一次重试的 `format_reminder`；
- verdict 提示词显式写明"两张表不要混：scores 恰好 5 个、layers 恰好 7 个，7 个分数永远是错的"；
- verdict 批重试次数 3 → 5（它是纯文本调用，便宜）。

### 4.3 传输失败 = 基础设施停止，不是建筑结论

新增 `run_autonomous.reviewed()`：`ValueError`（评审结论）直接放行到修复循环；
其他异常（`ProviderError` 等）按 **10/30/60/90 秒**递增退避重试。
批内退避也从 1 秒改为 `min(30, 4*(n+1))` 秒，图片批 3 → 4 次。

现场：一次 provider 网络窗口让 run 连续失败 4 次（用户截图所见）。修复后退避足以穿越该窗口。
若最终仍失败，写入 `awaiting = AGENT_REVIEW_ERROR_<stage>` + `history` 里带错误与当前生成器版本，
**保留现场供续跑**，而不是甩一个 traceback。

### 4.4 候选自身技术校验失败会直接杀死 run

`build_stage` 抛出的技术校验失败原本直接终止 run。新增：捕获后走**和评审拒绝同一条修复路径**
（合成一个 `{'decision':'reject', 'failure_modes':[...]}` 交给 `apply_generator_repair`），
并复用同一套收敛计数（`hard_limit=8`，生成器版本不再变化即 `AGENT_BLOCKED_<stage>`）。

**效果**：现场已真实触发 2 次，agent 据此修掉了真缺陷
（例："upper street windows filled with unpaired source door states `minecraft:iron_door`" ——
禁止方块更新环境下会导致半扇门，属交付级缺陷）。

### 4.5 清单谎报能力：声称"已接入手法库"但几何里没有

生成器写了 `technique_library_stamp_dispatch: active`，实际只做了
`from .technique_library import registry` 然后 `len(registry())` 存进一个**从未使用的局部变量**，
导出的 `.schem` 里一个库方块都没有。（我上一轮的 grep 验证被这行 import 骗过。）

**修法**：
- `technique_library.py` 新增 `verify_stamp_audit(read, audit)`：要求生成器在 manifest 里写
  `stamp_audit: [{id,x,y,z,turns}]`，审计**重新加载库条目**并逐格与导出几何比对。
- 自测证据：假锚点 → `FAIL matched 0`；真 stamp → `PASS matched 34`；空声明 → `FAIL`。
- `atelier_workflow.py` 在导出前审计并**就地改正**清单（`active` → `not_applicable` + 审计理由），
  审计结论留在 `technical_validation.stamp_audit`。

> **设计取舍**：不把"谎报"做成 build 失败。否则 run 会在一个纸面字段上死锁，而真几何缺陷还需要
> 修复轮次。改成"改了它"——假声明永远进不了交付物，诚实结论留在技术记录里，生成器仍会收到
> "把声明变真"的修复指令。

### 4.6 手法库对修复 agent 不可见（三个叠加原因）

`technique_library.py` 不在 `MODULES`、导入被禁、且没有名为 `registry` 的函数。
三处都已修好，现在**生成器版本确实在调用手法库**（`haussmann_reference.py:394` 等），
指令里也明确允许整函数替换。

### 4.7 评审门禁的其它一致性修复

- `score_gate_failure` 只在 frameworks 阶段强制——已确认口径为 `strict`（每轴 14..20、总分 ≥80）。
- `checked_call` 的返回提示、`reviewed()` 的阻塞落盘、`budget_check()` 抽取（供 build 失败与
  评审失败共用收敛计数）。

---

## 5. 当前卡点（**这是下一步唯一要做的事**）

### 现象

`rev 45` 和 `rev 48` 的立面评审**都拿到了 81 分**（门槛 80，每轴 ≥14 全部满足），
但两次都被判 `reject`。原因不是分数，是 `agent_review` 里的这条硬规则：

```python
if any(check['status'] == 'fail' for group in groups for check in group.values()):
    row['decision'] = 'reject'
if any(check['status'] == 'fail' for check in verdict['layers']):
    row['decision'] = 'reject'
```

而失败项清一色是**"视图证据不足"**，不是"几何做错了"：

```
rev 45: storey-2/storey-4 层间线脚沿两街连续贯通并与切角交圈缺乏视图证据，仅有泛化提及；证据不足记 fail
        storey-2/storey-4 窗洞凹陷深度/窗套侧壁缺乏可核验的透视或剖面证据，无法断言凹陷而非齐平，按不确定记 fail
        storey-4 与切角的对齐关系无可用视图证实
rev 48: noble_floor 长阳台带在转角处断开（orbit_low_315），未满足贯通两街并在切角连续的构图要求
        upper_floors（storey-3）窗洞凹入缺少独立可核证证据；切角屋顶交圈被遮挡，按不确定记 fail
        attic/roof section mansard 陡下坡—坡折—缓上坡剖面在给定视图中不可独立读出
```

### 根因

评审 scope 里有一句我对**所有**阶段生效的指令：

> "Use side/high/top views and geometric section data; **record uncertainty as fail rather than guessing pass**."

而实际上，tier1 导出的 23 张渲染图**无法**判读"1 格凹进深度""切角背后线脚是否连续""坡折剖面"——
这些属性需要**剖面数据或测量值**，而当前 `technical_validation.geometry` 里只有
连通性/门叶配对信息（`face_connected_components`、`largest_component_fraction`…），
**没有任何立面剖面测量**。评审唯一能拿到的"数据"是 manifest 里的**散文声明**，
而 manifest 的声明刚刚被证明不可信（§4.5）。

所以：**门禁在索取一种它拿不到的独立证据**，于是每次都在"不确定→fail→硬拒绝"上打转。

### 为什么不能只改那句话

把"不确定记 fail"直接删掉，等于允许评审在看不见时给 pass——这会重蹈用户此前指出的
"我审得比 agent 还松"的错误（漏过盒子老虎窗、把缺切角当"已知边界"放过）。
正确做法是**把证据补上**，不是把要求放低。

---

## 6. 下一步（建议按序执行）

### 6.1 首选：为立面阶段补**实测剖面报告**（治本）

在导出 `.schem` 之后、渲染之前，从**导出的几何**（不是生成器的散文）测出一份
`facade_section` 报告，塞进评审 evidence：

- **逐层线脚**：每个 storey 的 y 高度上，突出墙面 ≥1 格的方块在两条街面各自的最长连续段长度，
  以及是否绕过切角连续；
- **洞口凹进深度**：每个 storey 的开洞相对墙面的内凹格数（0 = 齐平）；
- **切角对齐**：切角面各层开洞中心线与两翼开间轴线的关系；
- **屋顶剖面**：沿垂直于屋脊的采样线，逐格输出坡面高度序列（可判定陡下坡—坡折—缓上坡）。

然后 scope 里加一句：**这些属性以 `facade_section` 的实测值为证据；渲染图被遮挡不构成 fail，
只有实测值不成立才记 fail。** 这既补上了门禁要的证据，又不放松标准——
因为测的是导出几何本身，和渲染图同源。

### 6.2 备选（更快但较弱）：把"证据不足"与"几何错误"分开

给 `DETAIL_CHECKS` 的 status 增加第三态语义，或在 scope 里明确：
"当某属性无法由给定的视图集判读时，记 `not_applicable` 并在 observation 里写明无法判读的理由，
**不要记 fail**；只有几何确实错误或缺失才记 fail。"

风险：给了评审放水的口子。建议只在 6.1 之后作为补充，不单独使用。

### 6.3 收敛保护

`run_autonomous` 现有 `hard_limit = 8`（同阶段修复轮次上限）+ "生成器版本不再变化即停"。
立面阶段当前已用掉 2 轮。**如果 §6.1 不做，很可能在余下轮次内反复拿到 76~81 分后
`AGENT_BLOCKED_facades` 停下**——这不是 bug，是设计好的"停下等人工判断"。

另外两项待办（不影响本轮交付）：
- 重写 5 个被 `@unittest.skip` 的五候选旧夹具；
- 生成路径合并：`design.build → haussmann_reference.build_corner`（参考路径）目前**没有独立立面层**，
  tier 0/1/2/3 硬编码在一个函数里；通用路径（`house.FORMS → facade.SCHEMES → technique`）与之并存。
- 风格维度（巴黎/日式/中式）——用户明确说**先验证巴黎**，之后再谈。

---

## 7. 操作手册

### 7.1 服务当前是停的，先重启

```powershell
cd "C:\Users\blackvccat\Desktop\巴黎街区素材 4\巴黎街区素材\paris-builder"
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
$p = Start-Process -FilePath "C:\Python312\python.exe" `
  -ArgumentList "-u","tools\serve_learning.py","--port","8765" `
  -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput "runs\LEARNING-WORKBENCH-v1\ux-server.stdout.log" `
  -RedirectStandardError  "runs\LEARNING-WORKBENCH-v1\ux-server.stderr.log" `
  -PassThru -WindowStyle Hidden
```

**改 `src/` 之后必须重启**：长驻进程不热加载，否则会用旧代码跑出无效候选。

### 7.2 续跑当前 run

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/workflow/autonomous' -Method Post `
  -Body '{"run":"ATELIER-A9B3C7EE"}' -ContentType 'application/json'
```

续跑是**幂等**的：它从 `workflow.json` 的 `stage` 继续，并保留已积累的
`generator_version`（48 个版本的工作量不会丢）。

### 7.3 看状态 / 看进展

```powershell
# 运行状态
python -u -c "import io,json;w=json.load(io.open('runs/ATELIER-A9B3C7EE/workflow.json',encoding='utf-8'));print(w['stage'],w['revision'],w.get('awaiting'))"

# agent 推理链（页面右上「轨迹」也是这个）
#   runs/LEARNING-WORKBENCH-v1/agent-sessions/e507b24d1f14410b.json  → kind == 'agent_progress'

# 单个候选的技术记录（含 stamp 审计）
#   runs/ATELIER-A9B3C7EE/revision-<N>/<stage>/<candidate>/technical_validation.json
```

页面：`http://127.0.0.1:8765`（前端是静态 JS，刷新即可见最新措辞）。

### 7.4 复核工具

```powershell
$env:PYTHONPATH='src'
python -u -m unittest discover -s tests -p "test_*.py"     # 期望：170 通过 / 5 跳过
python -u tools\_tier_probe.py                              # 各 tier 实际建了什么
python -u tools\_provider_probe.py                          # 模型连通性与余额
python -u tools\_vision_probe.py                            # 用真实评审图跑一次视觉调用
```

> `tests` 名字会被 site-packages 里的 `ultralytics` 抢走，**必须**用 `discover -s tests`，
> 不要用 `python -m unittest tests.test_x`。

### 7.5 已知环境坑

- 每个 pwsh 调用是**新进程**，`cd` 不保留，用 `workdir` 或每次 `cd`。
- 读 python 输出**不要**接 `Select-Object -First N`（会截断管道、中文乱码）；
  需要编码就设 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`。
- `Scene.volume` 存的是**调色板索引**不是状态字符串；
  读法 `palette[int(volume[y,z,x])]`，注意 shape 是 `(height, depth, width)`。

---

## 8. 本轮改动的文件

| 文件 | 改动 |
|---|---|
| `src/paris_builder/atelier_workflow.py` | 立面 scope 重写；verdict 校验器与提示词；`reviewed()` 退避重试；build 失败改走修复；`stamp_audit` 审计与清单改正；`budget_check()` |
| `src/paris_builder/technique_library.py` | 新增 `verify_stamp_audit()` / `_state_at()` |
| `src/paris_builder/generator_repair.py` | 修复指令：明确"import/计数不等于使用"，给出 `stamp_audit` 写法与失败条件 |
| `tools/_tier_probe.py` | 新增：逐 tier 几何差异探针（本次定性的关键证据） |
| `tools/_provider_probe.py` | 新增：模型连通性 / 余额探针 |
| `tools/_vision_probe.py` | 新增：真实评审图视觉调用探针 |

---

## 9. 边界与风险（不要含糊过去）

1. **没有交付物**。任何"已完成"的说法都不成立；`game_acceptance` 是 `PENDING`，只能用户判定。
2. **立面门禁目前是"分数够、检查项拦"的状态**，不解决 §5 的取证问题就会周期性空转，
   最终以 `AGENT_BLOCKED_facades` 停下等人工——这是设计行为，不是崩溃。
3. **模型侧仍会偶发传输失败**。§4.3 的退避能穿越数分钟级窗口，但长时间断网仍会停下
   （留下 `AGENT_REVIEW_ERROR_<stage>` 现场，可续跑）。余额 2026-09-28 查为 ¥41.16。
4. **manifest 的散文声明一律不可信**，包括被审计过的部分。交付前应以导出几何为准复核一遍。
5. `tier2` 阶段只跑过 1 次（rev 43）就因屋顶结构问题回滚到 frameworks；
   **屋顶剖面（mansard 陡下坡—坡折—缓上坡）是反复出现的失败主题**，在 frameworks 与 facades
   都出现过，属于结构性风险点，§6.1 的剖面报告应优先覆盖它。
