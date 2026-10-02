# 豪斯曼现实依据与框架对照（2026-10-02）

> 起因（用户原话）："这些你确定参考了巴黎19世纪豪斯曼建筑吗？你不能随便乱来造啊。"
> 本文是造型层的现实依据落地：规则库 `knowledge/styles/paris_haussmann_v0.2.json`（GROUNDED_RULES，取代 v0.1 的 PROVISIONAL），及对当前框架 `runs/ATLAS-FRAME-PROBE-v3` 的逐条对照结果。

## 1. 现实建筑证据要点（外部来源）

- **高度法规（1859）**：檐口高按街宽分档 12/15/18/20m；屋顶体量受 "comble en arc de cercle"（半径=街宽一半）限制；总高 12–20m、≤6 层。（[HAL 法规论文](https://hal.science/hal-01903202v1/file/MC_BRAUP_0519_88_TXT1_001_BD.pdf)、[Un Jour de Plus à Paris](https://www.unjourdeplusaparis.com/en/paris-reportage/reconnaitre-immeuble-haussmannien)）
- **竖向制度**：地面层（商铺）+夹层 → 贵族层（窗最高+连续阳台）→ 标准层 → 第五层连续阳台 → 檐口 → 曼萨德屋顶（锌皮、老虎窗、烟囱）。（[Paris ZigZag](https://www.pariszigzag.fr/insolite/histoire-insolite-paris/reconnaitre-immeuble-parisien/)、[defifeu.fr](https://www.defifeu.fr/securiser-mon-habitation/en-immeuble-hausmannien)、[Home Select](https://homeselect.paris/en/blog/style-haussmannien-post-haussmannien/)）
- **转角**：pan coupé（切角）或 rotonde（圆角）位于街角，柔化街景、增加路口可见性——两者都是合法默认。（[Atulam](https://www.atulam.fr/magazine/les-fenetres-haussmanniennes-codes-et-proportions-dun-embleme-parisien/)）
- **立面**：pierre de taille + 粗石基座；相邻立面共享檐口线构成街墙。（[Ville de Paris 类型学](https://cdn.paris.fr/paris/2020/02/26/426d5f879d02acc6f87f400eb818f792.pdf)、[APUR](https://50ans.apur.org/data/b4s3_home/fiche/82/03_immeuble_espace_urbain_tome3_apapu100-2_7cb38.pdf)）

## 2. 尺度翻译

MC 源对现实约 2:1 压缩（现实 20–26m ≈ 源 44–61 格）。规则约束**关系与比例**，不做米到格字面换算（v0.1 translation_policy 沿用）。

## 3. 对当前框架（ATLAS-FRAME-PROBE-v3）的逐条对照

| 规则 | 目标 | 实测（frame.json） | 判定 |
|---|---|---|---|
| 檐口比 | 0.72–0.80 | 35/46 = **0.761** | PASS |
| 屋顶占比 | 0.25–0.38 | 17/46 = **0.370** | PASS（贴上限） |
| 基座占比 | 0.12–0.20 | 6/46 = **0.130** | PASS |
| 阳台带 | 恰好两条：贵族层窗台 + 最上居住层 | lower y12（noble_base）/ upper y27（cornice_base） | PASS |
| 竖向层序 | 基座→贵族（最高窗）→标准→顶层→檐口→曼萨德 | base0-6/std6-11/noble12-24 双档/upper25-28/cornice27-35/roof29-46 | PASS |
| 转角族 | 默认切角/圆角；破格须声明 | **turret（projection=1）** | **PARTIAL：圆角体合法，但缺 justification 声明字段** |
| 凸出体/主次 | 存在 projection>0 分组段 | 翼段 projection ∈ {0,1} | PASS |
| 共墙 | 盲面且逐面声明 | 四面 glazing_allowed=false 已声明 | PASS |

**结论**：框架体量与现实豪斯曼制度相容——因为它本就锚定街区1 源层序，而该源是忠实豪斯曼。当前差距不在比例制度，在构图表现力（凸出体分级、色彩焦点、转角主角感）与装配毛边。

## 4. 由此产生的待办

1. `corner.family` 非 chamfer/rounded 时 manifest 必须带 `justification`（写进 atlas_conformance 检查）。
2. 公寓尺度**切角族件库空白**：回源补裁街区3 西端切角段（转角族默认项缺件）。
3. 组合版装配端头悬空已实证（v0.2 front.png 东端漂浮钩子），修复中（v0.3）。
4. 游戏内验收（冻结状态 + 造型审美）仍 NOT_RUN，只能用户判定。
