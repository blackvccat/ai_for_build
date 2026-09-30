# Atelier 建筑设计 Agent

入口：`http://127.0.0.1:8765/#studio`。主流程为对话需求 → 四层知识检索 → DSH 规划 → 用户检查参数 → 三级构建 → 文件与几何验证 → 七视角预览 → 视觉评审 → 修改并生成新版本。

## 运行边界

- 规划使用官方 `deepseek-harness-sdk==0.1.5rc1` 的 `sdk-minimal` profile，每轮独立运行时。`agent/building.patch.yml` 禁用通用 shell 和子进程工具；`agent/building-tools.mjs` 仅暴露建筑形式目录及本轮检索证据。通用文件编辑、网络搜索和任意命令均不向网页 Agent 开放。
- 浏览器显示规划摘要、证据 ID、工具名称、构建任务与验证结果。原始推理、工具参数和原始返回不显示。会话事件保存在 `runs/LEARNING-WORKBENCH-v1/agent-sessions/`，刷新可恢复。
- DSH 输出必须通过来源 ID、建筑形式、立面方案和尺寸范围校验。模型不可用或超时会退回本地规则，并明确标记来源；多轮本地修改保留上一版参数。
- 构建仍调用 `tools/build_house.py`，运行参数先由 `BuildRequest` 校验。每次生成独立 `runs/ATELIER-XXXXXXXX/`，保存需求、参数、来源、三级 `.schem`、七视角、报告与日志。失败写 `build_status.json`，重启后不会误报 PASS。
- 预览后可记录“需要修改”或“仅预览认可”及具体意见，写入该 run 的 `visual_review.json` 并回流会话。此记录仅代表预览判读，不能改变游戏验收状态。当前生成器对屋顶连续性与窗洞尺度仍有可见缺陷，技术 PASS 不可自动升级为视觉 PASS。
- API Key 由 Windows 当前用户的 DPAPI 加密，存于 `%LOCALAPPDATA%/ParisBuilder/deepseek.dpapi`。明文不进入浏览器存储、会话事件或运行报告。首次升级后需重新连接一次。
- 文件与几何 PASS 仅表示技术检查通过。视觉评审与目标 Minecraft 客户端游戏验收始终独立，`game_acceptance` 保持 PENDING，不能由 Agent 代填。

## 验证

`node --check web/learning/app.js`、`node --check agent/building-tools.mjs`、`python -m unittest discover -s tests`。SDK 补丁已用占位密钥完成运行时启动自检；本轮没有在缺少持久化真实密钥的情况下宣称 DSH 实模型规划已验证。网页本地规划、会话恢复、三级真实构建、七视角与下载接口均已实测。
