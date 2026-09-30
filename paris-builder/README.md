# Paris Builder

2026-09-26：已拆解两组参考源为8个立面分段与17个手法样本，接入知识库及[参考建筑拆解页面](http://127.0.0.1:8765/reference-decomposition/)。旧源统计中的空气编号错误已修复，84件历史裁件暂停推荐。详见 [拆解与清洗记录](reports/REFERENCE_DECOMPOSITION.md)。

这是“Minecraft 巴黎建筑生成项目”的可复现工作目录。包含素材分析、风格模型、构件库、参数化建筑生成、Sponge v2 导出、独立文件验证与真实方块模型预览。

> **本工作机是 Windows**（原作者使用 macOS）。首次接手先跑
> `pwsh -File tools\setup_windows.ps1`，并阅读 `reports/WINDOWS_PORT.md`。
> 仓库内 `.venv/` 是 macOS 3.9 虚拟环境，Windows 用系统 `python` + `PYTHONPATH=src`。

## 运行

```powershell
# Windows（推荐，一次装依赖并自检）
# 本机只有 Windows PowerShell 5.1：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_windows.ps1
# PowerShell 7+ 可用：pwsh -File tools/setup_windows.ps1
```

```bash
# macOS / Linux（原作者方式）
cd paris-builder
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
npm ci --ignore-scripts --no-audit --no-fund
PYTHONPATH=src .venv/bin/python tools/build_baseline.py \
  --source ../巴黎建筑素材 \
  --output .
```

## 当前产物（新流程，PAR-002）

- `runs/ATELIER-54E0BBBA/`：网页对话驱动的**转角豪斯曼建筑**，已走到 `stage = game`
  （等待用户游戏内验收）。交付件在 `revision-4/delivery/`：`candidate.schem`（43×53×43，97 997 方块）、
  `STATE-LAB.schem`（29 个状态实验区块）、instructions/manifest/technical_validation。
  独立 JS 复核 PASS、同种子重建逐格一致。全链记录见 `reports/ATELIER_54E0BBBA_DELIVERY.md`，
  生成器变更见 `reports/ATELIER_CORNER_FORM.md`（新增转角形式）与
  `reports/ATELIER_SHOP_BASE.md`（底层店面专属语汇，用户指出后修复）。

- `WORKFLOW_STYLE_LEARNING.md`：现实风格研究 → 构件拆解 → 多面框架 → 细节装配的强制流程。
- `knowledge/styles/paris_haussmann_v0.1.json`：与任何单栋实例分离的巴黎奥斯曼风格模型。
- `knowledge/library-v1/`：43 个窗标注、14 个源作品的状态清点与 14093 个去重上下文裁件、45 族 × 3 变体构件 recipe、catalog；178 个生产构件文件独立注册表检查 PASS。上下文是检索索引，不是全语义穷尽证明；游戏验证仍为 NOT_RUN。
- `runs/STYLE-LEARNING-PILOT-v0.1/`：流程可行性试验（供追溯）。
- `runs/PAR-002-v0.4/`：当前游戏验收候选。五框架、三立面、三级细化与评审记录；选择种子 6521 / 方案 1。`delivery/` 内含 PAR-002 与 STATE-LAB 双包、23个全栋视图、近景卡、验证报告、来源表及粘贴说明。最终用户验收 PENDING。
- `manifests/source_manifest.json`、`reports/baseline_report.*`：14 组源文件的清单、哈希与初检。
- `previews/<building_id>/`：源建筑六向正交图及单栋总览。
- `reports/PAR-002_execution.md`：PAR-002 锁定要求与真实进度。
- `reports/WINDOWS_PORT.md`：Windows 接手修复与复核证据（不改动已交付包）。
- `reports/MODEL_DESIGN_RUNS.md`：模型驱动设计执行器的实跑与离线重放记录。
- `runs/PAR-002-v0.4/delivery_verification.json`：交付包独立复核报告（本机 PASS）。
- `tools/model_design_run.py`：`--action all` 驱动 research→retrieval→frameworks(5)→facades(3)→tier2→tier3→delivery 的完整阶段链。

## 构建 PAR-002

```powershell
cd paris-builder; $env:PYTHONPATH = 'src'

python tools\build_par002.py frameworks --run PAR-002-vX.YY
python tools\build_par002.py facades --seed 6521 --run PAR-002-vX.YY
python tools\build_par002.py tier --seed 6521 --scheme 1 --stage 2 --run PAR-002-vX.YY
python tools\build_par002.py tier --seed 6521 --scheme 1 --stage 3 --run PAR-002-vX.YY
python tools\build_par002.py deliver --seed 6521 --scheme 1 --run PAR-002-vX.YY

# 交付后独立复核（不改动交付文件）：校验和、双 schem 三验、按种子字节复现、状态格中心
python tools\verify_delivery.py --out runs\PAR-002-vX.YY\delivery_verification.json
```

首次渲染会从 Mojang 官方清单下载 Minecraft 1.21.11 客户端资源到 `assets/cache/`，并校验 SHA-1。后续复用缓存。

预览读取同一输出 `.schem`，使用游戏方块模型和纹理。光照、玻璃混合、UV 锁定等与客户端可能不同，不能视为游戏内粘贴测试。查看 `previews/render_metadata.json` 获取具体限制。

只需要文件和检查、不需要渲染时加 `--skip-render`。独立验证可运行：

```powershell
node tools\validate_schematic.cjs runs\PAR-002-v0.4\delivery\PAR-002.schem
python -m unittest discover -s tests

## 归档（旧线，已弃用）

`archive/PAR-001/`：PAR-001 v0.1–v0.41 的 run、规格、旧报表与旧生成器（`design.py`、`build_design.py`）、旧 grammar/annotations/prompts。只作追溯，不再迭代。索引见 `archive/README.md`。

## 交给其他 AI

以工作区根目录 `AGENTS.md` 为交接说明，结合 `WORKFLOW_STYLE_LEARNING.md`、`reports/PAR-002_execution.md`、`knowledge/` 与当前 run 目录。更改设计后保存新 run_id，记录改动原因，保留旧版对照。

正式冻结技能包前还需完成目标客户端导入、独立视觉验收与用户认可；文件解析通过只证明文件/方块状态检查范围内的正确性。
