# Windows 接手与跨平台修复记录

本文件记录把 `paris-builder` 从原作者的 macOS 环境接手到本机 Windows 后所做的修复、复核证据与仍未验证的边界。
**本文件不修改已交付包内任何文件**，因此 `runs/PAR-002-v0.4/delivery/checksums.json` 的 102 项仍然有效。

## 1. 环境事实（本机实测）

| 项目 | 结果 |
|---|---|
| Python | 3.12.6（系统 `python`；仓库内 `.venv` 是 macOS 3.9.6 虚拟环境，Windows 不可用） |
| 依赖 | `nbtlib==1.12.1`、`numpy 1.26.3`、`Pillow 9.5.0`、`onnxruntime 1.30.0`、`tokenizers 0.21.4` 已安装并可导入 |
| Node | v24.11.0（`tools/validate_schematic.cjs` 独立注册表校验可用） |
| 语义检索 | `knowledge/retrieval/model/model_qint8_arm64.onnx` 在本机 x64 上可正常推理，5 项检索测试全部通过 |

## 2. 修复的真实缺陷

1. **UTF-8 与系统区域设置冲突（阻断级）**
   `Path.read_text()`/`write_text()` 未指定编码时，Windows 使用 ANSI 代码页（本机为 GBK），无法解码仓库中大量的中文/法文证据，
   `production.build` 直接抛 `UnicodeDecodeError`。macOS/Linux 默认 UTF-8，所以原作者不会遇到。
   修：`src/paris_builder`、`tools`、`tests` 共 **68 处**文本调用显式加 `encoding="utf-8"`；
   新增 `tools/check_utf8_encoding.py` 做静态复查（当前 0 处缺失）。
2. **打包脚本硬编码 macOS 字体路径**
   `tools/package_delivery.py` 使用 `/System/Library/Fonts/Supplemental/Arial.ttf`，Windows 下直接 `OSError`。
3. **TrueType 渲染在本机会硬崩溃（0xC0000005）**
   本机 Pillow 9.5 的 FreeType 后端在渲染第二个字号时会以访问冲突结束进程（`try/except` 无法捕获，`arial.ttf` 同样崩溃），
   中文系统字体（`msyh.ttc`/`simhei.ttf`/`simsun.ttc`/`Deng.ttf`）亦然。
   修：新增 `src/paris_builder/fonts.py`，**在子进程里做一次真实渲染探针**，通过才用 TrueType，否则回退 Pillow 内置点阵字体；
   渲染与打包工具的标签一律只用拉丁字符（中文说明保留在 UTF-8 的 Markdown 交付件中）。
4. **Node 解析是 POSIX 专用**
   `shutil.which('node') or sorted(~/.nvm/...)[-1]` 在 Windows 无 node 时会抛 `IndexError`。
   修：统一走 `paris_builder.fonts.node_binary()`，缺失时给出明确错误。
5. **macOS Keychain 专用凭据**
   `security find-generic-password` 在 Windows 会 `FileNotFoundError`。
   修：凭据解析顺序改为「环境变量 → macOS Keychain（仅 darwin）→ 配置里的 `credential_file`」，并给出可操作的错误信息。
6. **manifest 记录绝对路径**
   `manifest.json` 的 `previews` 曾写入 `/Users/xuhaoyang/...`（原作者家目录），换机后无法解析。
   修：新构建写入相对仓库根的路径。（已交付包未改动，其在 `delivery_verification.json` 中作为未列出/历史事实记录。）
7. **子进程输出编码**
   `subprocess.run(..., text=True)` 在 Windows 用区域编码解码，Node/中文报错会乱码或抛 `UnicodeDecodeError`。
   修：相关调用补 `encoding='utf-8', errors='replace'`。

## 3. 复核证据（本机实跑，可重复）

- `python -m unittest discover -s tests` → **72 项通过**（原 46 项 + 新增 26 项阶段链/门槛/解析回归）。
- `python tools/verify_delivery.py --zip "交付/PAR-002-v0.4-游戏验收.zip"` → **PASS**，明细见 `paris-builder/runs/PAR-002-v0.4/delivery_verification.json`：
  - `checksums`：102 项与磁盘逐字节一致；
  - `par002_python_roundtrip` / `state_lab_python_roundtrip`：PASS；
  - `par002_independent_registry` / `state_lab_independent_registry`：PASS（prismarine-schematic 1.3.0 独立读取）；
  - `par002_geometry`：PASS；
  - `rebuild_from_recorded_seeds`：**PASS**——按 `concept.json` + `design_seeds.json` 记录的种子在本机重新生成，
    体素状态与交付 `PAR-002.schem` 完全相同，且 **字节级一致**（`5ca7e4c3…`）；
  - `state_lab_centres`：150 个实验格中心状态与 `state_lab_tests.json` 记录一致；
  - `preview_provenance`：交付预览的 `render_metadata.json` 记录 `source_sha256` 与交付 `PAR-002.schem` 一致，
    23 个视角齐全——交付的图确实是交付那栋楼的渲染；
  - `acceptance_zip`：`交付/PAR-002-v0.4-游戏验收.zip` 的 103 个条目与已复核的 `delivery/` 目录**逐字节一致**，
    因此不需要重新打包，用户手上的验收包就是本次复核覆盖的同一份证据。
- 渲染链路在本机可用（`preview3d.render_previews` 七视角 + 16 环视全部出图）。
- **完整构建链路复现**：在临时 run（`--run _PORTCHECK`，使用只读源素材与已记录的评审文件，不触碰交付目录）执行
  `python tools/build_par002.py deliver --seed 6521 --scheme 1 --skip-render`，得到
  `PAR-002.schem` sha256 `5ca7e4c3…`、`STATE-LAB.schem` sha256 `b94984ee…`，与交付文件**逐字节相同**，
  状态实验格 150 个。即 Windows 上的确定性构建（生成 + Python 回读 + Node 独立注册表 + 几何 + 冻结状态）全程可用。

## 4. 新增工具

| 文件 | 用途 |
|---|---|
| `src/paris_builder/fonts.py` | 跨平台字体（含子进程探针）与 Node 解析 |
| `src/paris_builder/replay.py` | 离线重放模型客户端：无网络驱动完整阶段链，仅作测试夹具 |
| `tools/verify_delivery.py` | 交付包独立复核（校验和、双 schem 三验、按种子复现、状态格中心） |
| `tools/check_utf8_encoding.py` | 静态检查文本 I/O 是否显式 UTF-8 |
| `tools/setup_windows.ps1` | Windows 一键准备与自检（纯 ASCII，兼容只有 Windows PowerShell 5.1 的机器） |
| `tests/test_stage_chain.py` | 阶段链、动作解析、循环终止、视角映射、重放夹具回归 |

一键自检在本机实跑通过（`powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_windows.ps1 -SkipInstall`）：
UTF-8 检查 0 缺失、Node 解析到 `C:\Program Files\nodejs\node.EXE`、
字体探针判定本机 TrueType 不可用并回退点阵字体、交付包 10 项检查全 PASS（`acceptance_zip` 含 ZIP 逐字节比对）。

## 5. 执行器阶段链（MODEL-DESIGN）

`tools/model_design_run.py --action all` 现在一次跑通
`research → retrieval → frameworks(5) → facades(3) → tier2 → tier3 → delivery`，并且：

- 每个视觉阶段仍然**必须**登记逐视角观察、参考图比较、失败模式与回退层级；
- 只有门槛校验真的通过才 `advance`，否则停在原阶段并记录 `gate_blocked`；
- 交付阶段额外生成并登记 `STATE-LAB.schem`、`manifest.json` 与 `instructions.json`；
- `--provider configs/providers/replay.json` 为**离线测试夹具**，其产物一律标注 `offline_replay`，不得当作实模型证据。

本机实跑记录（2026 交接）：

- `runs/MODEL-DESIGN-REPLAY-v0.2`（诚实路径）：fr1/种子 6317 被脚本评审 reject，选中的正是被否候选 → 停在 frameworks，未继续产出。
- `runs/MODEL-DESIGN-REPLAY-FULL-v0.1`（force-pass 夹具）：一路通过到 delivery，生成 148 个状态实验格，最后停在用户专属的 `game` 门槛。
- 这两次实跑抓出并修复 8 个真实缺陷（单候选登记命名空间、漏登记 assembly_plan、交付缺 manifest/instructions、
  `ensure_prefix` 重复提交、前缀推进被误判为阶段推进、管道无限重跑、门槛允许"选中被否候选"、夹具候选 id 解析），
  详见 `reports/MODEL_DESIGN_RUNS.md`。
- **实模型（DeepSeek）实跑**：密钥只经环境变量传入，未落盘。`runs/MODEL-DESIGN-LIVE-v0.3` 真实完成
  5 候选两轮设计与评审（25 次调用 / 170k tokens），评审成功落盘且 5 个候选**全部 reject**（评分 14–16，
  多项低于门槛）——门槛真实生效。实跑又抓出 7 个缺陷（回复围栏解析、回退层级归一化、拒绝无法落盘、
  漏视角作废、frameworks 误用 stage 0、恢复重复付费、长跑成本），已全部修复。

## 6. 仍然是 NOT_RUN / 只能由用户判定

- 游戏内正常更新 / 禁止更新 A/B、相邻变化、区块重载（`delivery/game_acceptance.json` 全为 PENDING）。
- 全方向、近景、转角、院内与屋顶的审美验收。
- 14 源宏观语义穷尽仍为 NOT_PROVEN；原创性审计为有限网格抽样。
- 实模型（DeepSeek）跑完整阶段链：需要 `DEEPSEEK_API_KEY` 与调用预算，尚未执行。
