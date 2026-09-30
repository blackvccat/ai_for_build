# ai_for_build — 建筑自动设计流水线

用「生成 → 技术校验 → 多模态视觉评审 → 不过就修生成器」的闭环，让 AI **自己设计建筑**并导出
可粘贴的 Minecraft 结构文件。当前验证对象是**巴黎奥斯曼式转角公寓**。

> **本仓库只收录源码与文档。** 运行产物、知识库数据、第三方素材**不在仓库内**，
> 原因见下方[「不在仓库里的东西」](#不在仓库里的东西)。因此**克隆后不能直接跑通**，
> 需要先按[「运行前提」](#运行前提)补齐数据目录。

---

## 这个项目在做什么

输入是一段自然语言需求 + 可选参考图，输出是一栋建筑的 `.schem`（Minecraft 结构文件）。
中间不是"一次性生成"，而是一条**带门禁的流水线**：

```
形制 → 立面 → 细化二级 → 细化三级 → 交付 → 游戏验收
```

每个阶段都跑同一个三步循环：

```
生成候选  →  技术校验（几何级）+ 渲染 23 张视图  →  多模态 AI 逐图评审
                    ↑                                        │
                    └──────── 不过就修生成器 ←───────────────┘
```

三条硬性设计原则：

1. **先形制后细节**——屋顶剖面、体量、开间网格在形制阶段定死；立面和细节不允许掩盖形制错误。
   后阶段发现结构问题会**回滚**到形制阶段重做，而不是在细节层打补丁。
2. **一个阶段只做一个设计**——不做多候选择优，那只会把成本和"选最不差的"风险一起放大。
   达不到门槛就修，不换。
3. **不合格不前进**——`game_acceptance` 只能由用户在游戏内判定，系统与模型一律保持 `PENDING`。

## 目录结构

| 路径 | 内容 |
|---|---|
| `paris-builder/src/paris_builder/` | 核心源码 |
| `paris-builder/tools/` | 命令行入口与诊断探针 |
| `paris-builder/tests/` | 单元与回归测试（170 项） |
| `paris-builder/reports/` | 设计报告、流程文档、交接文档 |
| `paris-builder/web/learning/` | 网页界面（静态前端） |
| `paris-builder/configs/` | 供应商配置（只引用环境变量，不含密钥） |
| `AGENTS.md` | 项目交接说明：工作流规范、已知坑、当前进度 |
| `巴黎建筑生成项目规划_v0.1.md` | 项目规划 |

### 关键模块

| 模块 | 职责 |
|---|---|
| `atelier_workflow.py` | **流水线主控**：阶段状态机、门禁、修复循环、收敛控制 |
| `workflow.py` | 阶段定义、产物契约、评审校验、评分门禁 |
| `generator_repair.py` | 生成器修复：源码诊断 → 补丁 → 校验 → 新版本 |
| `haussmann_reference.py` | 巴黎转角建筑几何（当前活跃的生成路径） |
| `house.py` / `facade.py` / `technique.py` | 三层分离：结构 / 立面构图 / 方块技法 |
| `technique_library.py` | 统一手法库索引（1018 条目）+ 声明与几何的审计 |
| `architecture.py` | `Scene`、状态变换、冻结状态清单 |
| `preview3d.py` | 预览渲染（真实方块模型，23 视角） |
| `learning_web.py` | 网页服务（端口 8765） |

### 两份必读文档

- **`reports/ATELIER_WORKFLOW_LOGIC.md`** — 逻辑流程与开工说明。状态机、数据流、
  门禁口径、收敛规则、不变量、命令速查。**要接手先读这份。**
- **`reports/ATELIER_HANDOVER.md`** — 当前状态快照与已知边界。

`ATELIER_WORKFLOW_LOGIC.md` 里引用的源码行号可用
`python tools/_check_doc_refs.py` 交叉验证，改完代码跑一次就知道文档哪里失效了。

## 运行前提

```powershell
# Windows，Python 3.12
cd paris-builder
pip install -r requirements.lock
npm install            # 仅预览渲染与独立校验需要

$env:PYTHONPATH = 'src'
python -u -m unittest discover -s tests -p "test_*.py"   # 期望 170 通过 / 5 跳过
python -u tools\serve_learning.py --port 8765            # 网页界面
```

模型密钥**不落盘**：走环境变量 `DEEPSEEK_API_KEY`，或由 `local_credentials.py`
用 Windows DPAPI（用户级加密）存到 `%LOCALAPPDATA%\ParisBuilder\deepseek.dpapi`。

## 不在仓库里的东西

| 缺失目录 | 体积 | 为什么不在 | 怎么补 |
|---|---|---|---|
| `paris-builder/knowledge/` | 667 MB | 单文件 `library-v1/exhaustive-contexts/index.jsonl` 达 **387 MB**，`retrieval/model/model_qint8_arm64.onnx` 达 **112.9 MB**，均超 GitHub 单文件 100 MB 硬限 | 由源素材重新抽取（`tools/extract_details.py`、`tools/survey_incoming.py`） |
| `paris-builder/runs/` | 1.8 GB | 运行产物（生成器版本、预览 PNG、评审记录），不是代码 | 重跑流水线产生 |
| `paris-builder/previews/`、`交付/` | 130 MB | 渲染与打包产物 | 重跑产生 |
| `巴黎建筑素材/`、`参考图/`、`窗/` | 35 MB | 第三方素材与真实建筑照片，公开仓库有版权风险 | 需自行准备 |
| `paris-builder/assets/cache/` | 56 MB | Minecraft `client.jar`（Mojang 版权） | 由 `npm` 依赖自行下载 |

`.gitignore` 里对每一条都写了排除理由。

## 当前进度

- ✅ **形制（frameworks）**：已通过门禁
- ⛔ **立面（facades）**：卡住。评分已多次达到门槛（73~83，门槛 80），但门禁要求
  **95 个检查项全部不 fail**，而部分检查项（如窗洞凹进深度、切角背后线脚连续性、
  mansard 坡折剖面）**渲染图判读不了**，于是每轮都有几项因"看不清"被判 fail。
  修法见 `reports/ATELIER_WORKFLOW_LOGIC.md` §6.3：从导出几何实测一份剖面报告作为证据，
  把"看不清"和"做错了"分开。
- ⬜ 细化二级 / 三级 / 交付：未开始
- ⬜ **游戏内验收：`PENDING`**（只能由用户判定）

**本仓库目前不含任何交付物。**

## 自动流水线的操作方式

```powershell
# 启动服务（改过 src 必须重启——长驻进程不热加载）
Start-Process -FilePath "python" -ArgumentList "-u","tools\serve_learning.py","--port","8765" -PassThru

# 续跑（幂等：从 workflow.json 的 stage 继续，保留已积累的生成器版本）
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/workflow/autonomous' -Method Post `
  -Body '{"run":"<RUN-ID>"}' -ContentType 'application/json'
```

诊断探针（`tools/` 下，以 `_` 开头的都是）：

| 脚本 | 用途 |
|---|---|
| `_tier_probe.py` | 逐细化层级的几何差异——判断"这个阶段到底建了什么" |
| `_provider_probe.py` | 模型连通性与余额 |
| `_vision_probe.py` | 用真实评审图跑一次视觉调用，区分"网络问题"与"代码问题" |
| `_check_doc_refs.py` | 校验文档里引用的源码行号是否失效 |
| `_scan_commit.py` | 提交前扫描密钥与超大文件 |

## 已知边界

- 游戏内粘贴**必须关闭方块更新**（WorldEdit/FAWE）。因此所有方块状态在导出时必须显式写全，
  不能指望游戏重算——禁止更新下必须逐格冻结的格数 **53,000+**。
- 门叶必须成对；源素材里大量门被导出成两格都是 `half=lower`，禁止更新下会粘出半扇门。
- 当前活跃生成路径 `haussmann_reference.build_corner` **没有独立立面层**，
  tier 0/1/2/3 硬编码在一个函数里；通用路径 `house → facade → technique` 与之并存，尚未合并。
- 风格维度（巴黎/日式/中式）目前**只验证了巴黎**。
