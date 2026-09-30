# 模型无关流程实现

已实现持久化状态机、结构化评审协议、按阶段材料登记、全链文件哈希绑定、图片内容哈希校验、诊断回退与跨模型证据汇总。入口 `PYTHONPATH=src .venv/bin/python tools/run_workflow.py --help`。

离线回归覆盖缺证据、陈旧评审、文件变更、重复推进、回退失效、模型冒充游戏验收、离线结果不计入跨模型成功及目标版本锁定。离线测试证明流程约束可执行，不证明某模型已完成独立建筑设计。

示例：

```sh
PYTHONPATH=src .venv/bin/python tools/run_workflow.py create --task runs/example/workflow.json --json knowledge/workflow/brief.example.json --model provider/model --image-input
PYTHONPATH=src .venv/bin/python tools/run_workflow.py prompt --task runs/example/workflow.json
PYTHONPATH=src .venv/bin/python tools/run_workflow.py register --task runs/example/workflow.json --kind style_model --path knowledge/styles/paris_haussmann_v0.1.json
```

`--image-input` 是能力声明，不是成功实测。现有PAR-002评审不能直接冒充此协议下的新独立模型运行；需要实际证据重新登记。最终游戏状态默认 PENDING。
