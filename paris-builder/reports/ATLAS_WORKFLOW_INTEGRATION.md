# Atlas 工作流接续与证据边界（2026-10-02）

本报告说明 `atlas_street1` 接入 Atelier 的实现与验证，专门对应「先评写实骨相，后装源技法」这条链路。技术夹具不授予真实建筑视觉认可，也不授予游戏验收。

## 已实现的阶段行为

- `frameworks` / `facades` 生成四种普通素材质的裸造型，不使用源库 stamp。造型本身要表达基座与勒脚、凸出体、凹进窗洞、阳台挑板、叠涩檐口、曼萨德、坡面老虎窗小屋与转角塔亭；这些体量缺失不能以「后续细节」为由豁免。
- `tier2` / `tier3` 才装配完整源技法件库。目前两个细化阶段都诚实记为 `post_framework_complete_kit`，不声称已经实现逐件递增的技法装配。
- 后续构建重新验证选中框架与立面评审的图像、文件哈希、计划和门禁。`tier3` 还需要实际通过的 `tier2` 评审，交付还需要实际通过的 `tier3` 评审；只有 `selected` 标志不足以继续。
- 后续候选必须保持已评框架 concept 的完整 composition 布局。任务局部修复即使保留同一个 `composition_profile`，若改变布局，也会产生技术 FAIL 并要求回到框架重新评审。

## 源件证据与交付

每个 atlas 候选保存并绑定 `generation_manifest.json`。细化候选另外保存 `assembly.json`，其中 stamp 坐标和包围盒只负责定位；实际观测来自导出 `.schem`。这修复了旧的目录断点：装配在 `atlas-work/` 下落盘，而符合性工具查找的是候选 `.schem` 同目录的 `assembly.json`。

细化技术校验重新检查实际原件与派生件的 stamp 状态、有限覆盖规则、来源回放收据和导出结果。交付复制已评 `.schem` 后再运行一次源件放置审计，并在 ZIP 中包含 `generation_manifest.json`、`assembly.json`、`source_piece_audit.json`、测量报告、图像、建筑与 STATE-LAB。

新任务的转角链使用 `split-v3`：代码判导出符合性，模型判六项建筑品质。源件审计 PASS 只能证明来源与放置，不能替代模型对可见写实程度的判断。最终 `game_acceptance` 保持 PENDING；用户是唯一可关闭游戏门禁的主体。

## 已运行验证

2026-10-02 的定向测试：

- `test_atlas_workflow.py`：13 项通过。
- `test_atelier_workflow.py`：20 项通过。
- `test_split_review.py`：13 项通过。
- `test_generator_repair.py`：12 项通过。
- `test_generator_worker.py`：2 项通过；包括真实新进程 atlas 源码快照验证。

Atlas 夹具完成 `frameworks → facades → tier2 → tier3 → delivery → game`。它使用小型真实 schematic、一个真实来源回放派生窗件、真实文件哈希与 stamp 回读审计、真实工作流门禁和 ZIP 内容检查；整栋构造、渲染和几何检查被明确 mock。离线评审文字全部标注为管线夹具而非建筑认可，测试临时目录在测试结束后移除。夹具还验证了跳过 tier2 会被拒绝、框架后偷偷改 composition 会技术失败、交付后游戏状态仍是 PENDING。

该结果证明持久化、来源证据、阶段门禁和交付目录能闭环，不证明新骨相的视觉品质。新骨相要另行逐视角看图，并接受真实模型/用户的独立品质判断。

## 接续时必须保留的限制

本次未续跑或改写任何历史用户任务，也未重启服务。框架、装配和北/西街面符合性适配器由同一工作会话的其他代理处理，服务重启及浏览器全流程由主控制者统一负责。

已修复自动修复的模块边界：`generator_repair.MODULES` 现在包含 atlas 的装配、布局、profile、裸造型与细化模块；修复上下文说明各模块职责及先骨相后源件的边界。新进程 worker 保留 `composition_profile`，为两次 atlas 构建分配独立 work_dir；atlas 修复的可信回归检查包括 composition 与导出阶段符合性测试。

真实 worker 夹具在只属于测试的快照中把勒脚素材质从 stone 改为 granite，使用非默认 flat_baseline，验证导出确实包含快照更改、composition 未被丢弃、两个 work_dir 都落盘、普通框架无源 stamp，且主源码哈希不变。该测试证明活跃 atlas 源码能进入隔离修复与新进程执行，仍不是实模型建筑修复成功的证据。端到端实模型任务需另行真实生成、看图、评审与修复。

## API 投影与前端脚本烟测

另外运行了隔离的 FastAPI TestClient 只读烟测，使用系统临时目录中的明示离线候选，不启用服务 lifespan/recovery、不接触历史 jobs、不启动模型：页面、app.js、workflow.js、runs 接口返回 200；未获认可的框架仍显示 `frameworks / VISUAL_REVIEW / game=PENDING`，保留 composition profile、六项品质问题、默认 reject 和 PENDING 符合性状态。下载 schematic 字节与落盘一致，过早下载 delivery.zip 返回 409，路径穿越返回 404，外部 Host 返回 403；烟测前后 workflow.json 字节不变，临时目录已清理。

前端 `app.js` 与 `workflow.js` 的 `node --check` 均通过；`workflow-status.test.cjs` 与 `source-state-ui.test.cjs` 合计 4 项通过。该证据覆盖 API 投影与脚本逻辑，不替代已重启服务的真实浏览器路径，也不授予实验几何认可。
