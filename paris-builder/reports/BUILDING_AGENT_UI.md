# 建筑 agent：把现有流程投影成一个网页

用户要求：设计一个前端网页，作为「建筑 agent」，把当前流程纳入进来。选定形态是
**独立可访问的网页**（走 `webServer` 注册路由），执行范围包括单阶段构建、整条链与门禁、
以及一条只能由用户填写的验收通道。

地址：**http://127.0.0.1:3080/building**

实现方式：一个动态 Cordis Plugin（宿主半边，无浏览器半边），包 `build-1`。
动态插件只活在本进程；但页面不持有任何自有状态，重启后重建界面不丢任何东西。

## 1. 架构：不新建数据库

现有流程的真相已经活在文件约定里：`runs/<RUN>/` 下的报告、预览图、校验收据。所以界面的
第一原则是**只做投影**：

| 流程概念 | 页面元素 | 真相源 |
|---|---|---|
| 阶段 | 左侧清单 + 门禁徽章 | 该阶段报告是否存在 + 报告里的 `status` |
| 测量值 | 卡片数字 | 报告字段（玻璃占比、窗组、空格、方块、开口…） |
| 证据 | 预览图 | `runs/<RUN>/tier-3-previews/`、`previews/` |
| 竞争 | 评分卡 + 选中标记 | `facade_competition.json` 的 `entries` / `selected` |
| 待用户判定 | 独立通道，系统不可写 | `runs/<RUN>/user_acceptance.json` |

这样用命令行重跑之后，页面自动正确，不需要同步——不存在「界面显示通过但文件不是那样」的
可能，而这是本项目最不能容忍的失败模式。

## 2. 执行权留在宿主

浏览器只发意图（"跑这个阶段"），宿主用 `ctx.shell.start()` 起子进程，命令与命令行**完全等价**：

```
python -u tools/build_house.py --run <RUN> --seed <seed> --form <form> --width <w> --depth <d>
```

参数从该 run 的 `design_seeds.json` 推导，所以界面不需要用户填一堆参数。长任务不依赖页面
开着；进程句柄存在插件闭包里，插件停止时统一 kill。

## 3. 宿主受限环境：实测出来的四条

动态 Host 半边**只有** `ctx`、`harness`、`console`、`btoa`/`atob`、`TextEncoder`/`TextDecoder`。
没有 `process`、`Buffer`、`fetch`、`setTimeout`、`URL`、也没有 Node 内建模块。因此：

1. **文件走 `ctx.fs`，进程走 `ctx.shell`，计时走 `ctx.timer`** —— 不是可选项。
2. **`ctx.fs` 的相对路径基准是 harness 的 Desktop，不是会话工作目录**。
   本会话工作区是 `Desktop\巴黎街区素材 4`，而项目在其下的 `巴黎街区素材/paris-builder`，
   所以相对候选全部落空。做法：从 `workspaceRegistry.list()` 里找路径含工作区名的项，
   拼上子目录；相对候选与绝对路径只作兜底。
3. **没有 `URL`**：查询串手写解析（`queryOf`）。
4. **图片不能直接回**：`Buffer` 不存在，所以资产端点返回 base64，页面转 blob URL 渲染。

执行子进程另有三条 Windows 实测经验，缺一条输出就是空的：

- `python -u`：否则管道下 stdout 是块缓冲，输出拖到进程结束才出现，看起来像卡住；
- `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`：无控制台时 Python 按 GBK 写 stdout，
  按 UTF-8 解码会把内容丢掉；
- `2>&1`：脚本的进度与错误大多写在 stderr。

## 4. 验收通道：只能由用户写

`POST /building/api/acceptance` 是唯一写入 `user_acceptance.json` 的入口，记录形如：

```json
{ "status": "accepted|rejected|pending", "by": "...", "note": "...",
  "at": "...", "scope": "game_acceptance", "authority": "USER_ONLY" }
```

硬约束（写在记录里，也写在页面上）：**系统与模型不得代为填写，界面也不得把 PENDING
渲染为已完成**。没有记录时页面显示 PENDING，这是默认态而不是待办勾选框。

## 5. 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/building` | 页面（自包含 HTML，零构建步骤） |
| GET | `/building/api/runs` | 列出 `runs/` 下每个 run 的完成阶段数 |
| GET | `/building/api/run?name=` | 一个 run 的全部阶段：门禁、测量值、图片清单、报告原文 |
| GET | `/building/asset?run=&path=` | 单张预览图，base64 回传 |
| POST | `/building/api/build` | 起一个阶段的子进程 |
| GET | `/building/api/build/out?job_id=` | 增量读该进程输出 |
| POST | `/building/api/acceptance` | 记录用户判定 |

阶段表（`STAGES`）就是依赖图：立面竞争 → 三级细化 → 城市层 → 细节入库 → 禁止更新判读 →
交付复核。新增阶段只需在 `STAGES` 里加一行。

## 6. 实测验证

| 检查 | 结果 |
|---|---|
| 页面 | HTTP 200，10,103 字节，`text/html; charset=utf-8` |
| run 列表 | 42 个 run，含完成阶段数（`root` 也回显，便于排查路径） |
| run 详情 | `HOUSE-001-v0.7`：3/7 阶段，seed=7101 apartment_block 26×30，8 项测量值、4 张图 |
| 预览图 | 68,780 字节，PNG 魔数正确 |
| 阶段执行 | `frozen_check` 真实跑通并写出 `frozen_check.json`（325,027 字节，门禁 PASS） |
| 实时输出 | `verify_delivery` 运行中即读到 3,251 字节（含 stderr 的 traceback） |
| 验收写入 | POST 写入成功并可读回；测试记录已删除，状态回到 PENDING |

## 8. 首次真实启动（CHAIN-v1.0）暴露的设计层缺陷

用网页启动了一条完整的新链（`runs/CHAIN-v1.0`，seed 8201、`street_row` 52×26×6 层），
按依赖顺序跑到第 2 阶段。**暴露了一个比 UI 重要得多的问题**，记在这里。

### 已跑通的

| 阶段 | 结果 |
|---|---|
| 立面竞争 | PASS。三套方案各生成三级并全部渲染；评分 `haussmann_apartment=65`、`palace_front=63`、`plain_terrace=59`，**选中 haussmann_apartment** |
| 三级细化 | PASS。文件校验 / 几何 / **字节复现**全过；44,884 方块、308 个开口、65×37×43；10 种技法全部落地（`window_surround` 4067、`string_course` 900、`guard_rail` 720、`shopfront` 400…） |

也就是说：**网页驱动 → 子进程执行 → 门禁判定 → 报告落盘 → 页面读回**这条链是通的。

### 找到并修掉的真实 bug：`Wall.point` 的方向符号

`Wall.point(u, y, d)` 的 `d` 本意是「从墙外表面往里的进深」，但实现用的是 `+ normal * d`，
而 `normal` 指向室外——于是 `d` 越大越往**建筑外面**走。后果：

* 街面开口被切到建筑外（`z0=6` 的墙，`d=0..4` 覆盖 `z=2..6`，而建筑从 `z=6` 开始）；
* 实墙留在里面、凹进落在街上，街面的窗看起来像"从外表面一路通到内部"的竖条；
* 我因此误判过街面朝向（把它改到 `z_max` 侧），`front.png` 随即变成一面完全没有窗的墙——
  这个反向证据才让我定位到符号。

修法：`point` 改为 `- normal * d`，并新增 `Wall.inner(u, y, d)` 明确表示"墙里侧第 d 格"。

### 同时发现的覆盖冲突

`window_surround` 的 soffit（过梁底面）原本写在 `d=1`，而玻璃也在 `d=1`——**过梁正好压在玻璃上**，
窗被读成一条缝。已把 soffit 移到 `d=0`（与窗台、过梁同一层）。

### 还没解决的（不要当成已完成）

* **窗仍然偏小**：校准后街面上可见玻璃的纵向行程实测为 `2 格 × 20 处`，只有个别到 3–5 格。
  参考图的窗明显更高。层高已从 3–4 提到 5–6、底层 6–7，但**这只改了比例，没有解决根本的
  层次划分问题**——窗高、窗台、过梁、层线四者在同一立面上的分配还需要重新设计，而不是再调一个常数。
* `street_row` 的楼层表是**各段合并**的（诊断输出里能看到每段的 levels 被接到了同一个列表上），
  每面墙虽然按自身高度过滤，但过滤是"高度 ≤ wall.height+1"，可能把邻段的楼层也算进来。
  这需要单独查。
* **整条链只跑到第 2 阶段**。城市层、细节入库、禁止更新判读、交付复核都还没在这条链上跑过。
* 设计层改了 `point` 的语义之后，`tests/test_design.py` 的 14 项回归**需要重跑**（本次未跑）。

### 结论

网页本身是可用的、经过实测的；**设计层的几何还不合格**。这两件事必须分开说：
"能启动"不等于"产出合格"，而后者才是项目真正的验收线。


- **只有单阶段执行**，没有「一键重建整条链并按门禁停在失败处」。现有 `tools/model_design_run.py`
  已经实现了阶段机与门槛，界面外壳可以直接复用它的产物，但本轮没接。
- **没有实时推送**：输出靠 1 秒轮询。宿主有增量文件观察能力可用，但轮询已够用。
- **没有对照区**：AGENTS 要求「每次生成必须与标准图逐张对比」，`compare_reference.py` 已能
  产出同尺度并排图，但页面还没把它作为默认视图。
- **没有排除理由浏览**：`survey.json` 的 15 件排除源、`exclusions.json` 的 555 条被拒裁切、
  774 件构件的冻结判读，目前只能看原始 JSON，缺一个可点开的清单。
- **动态插件不跨进程重启**：重启 DSH 后需重新激活（`cordis_run`）。
- 游戏内验收：仍然 **PENDING**，只能由用户判定。

## 9. 页面卡在「载入中…」：一个转义错误

首次打开页面时只有顶栏渲染出来，主区永远停在「载入中…」。

### 根因

页面脚本由宿主模板字符串生成。v0.7 里我写了：

    const header = '$ ' + j.command + '\n(cwd ' + j.root + ')'

宿主模板字符串先把 `\n` 消化成**真实换行**，浏览器收到的 JS 于是变成字符串字面量断行：

    SyntaxError: Invalid or unexpected token

**整段脚本一行都不执行**，`loadRuns()` 从未运行，页面停在初始 HTML。

最麻烦的是**这种错误在页面上完全不可见**：没有报错框、没有控制台可看（我只能读页面源码），
表现像"加载慢"，很容易被误判成接口或性能问题。

### 定位方式

不靠肉眼读 10KB 模板字符串，而是取回页面、抽出 `<script>`、交给 `node --check`。
修复前它 `exit 1` 并直接指出 `line 129: Invalid or unexpected token`，一眼定位。

### 修复

1. 换行改为 JS 侧拼接 `const NL = String.fromCharCode(10)`，不让宿主转义参与；
2. 页面加 `window.onerror`，把这类错误直接渲染到主区——**下次它自己会说话**；
3. 初始化与刷新都包 try/catch，不再静默停在「载入中…」；
4. `tools/check_web_page.py` 保留为常备工具：校验脚本语法 + 顺带核对 runs / run / asset 三个接口。
   **每次改页面都该先跑它**，因为这类错误在浏览器里是无声的。

## 10. 当前状态

| 检查 | 结果 |
|---|---|
| 页面 | HTTP 200，11,354 字节 |
| 页面脚本语法（node --check） | **PASS** |
| `api/runs` | 43 个 run，根目录正确 |
| `api/run?name=CHAIN-v1.0` | 3/6 阶段，验收 PENDING |
| `asset` | 77,831 字节 PNG，base64 回传正常 |
| 冻结交付包 | **PASS**（102 项校验和一致，未被本次改动影响） |
| 测试 | 101 项通过 |

**网站可用；设计层的立面几何仍不合格**（见上一节，窗高与层线分配需要重做）。
徽章上的 PASS 只代表流程与校验，不代表立面合格。
