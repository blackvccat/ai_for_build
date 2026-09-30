# 混合检索实施与边界

已建立178件生产候选索引：43个源窗＋45族×3个派生配方。没有向量化697298个尚未完成建筑语义解释的局部上下文。

## 实现

- SQLite保存原catalog完整证据（包括准确状态、裁切、锚点、来源和翻译记录），向量不能覆盖这些字段。
- 官方`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，固定revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`，官方arm64 int8 ONNX，mean pooling＋L2归一化，真实384维多语言语义向量。模型118MB，本地CPU运行；不需要API密钥。
- 模型卡：<https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2>。固定版本模型卡已保存于`knowledge/retrieval/model/README.md`，许可证Apache-2.0。模型与catalog SHA256见manifest。
- family、最大宽度/深度、游戏验证状态为硬过滤。尺寸比较作为可选几何重排。可传参考图，以颜色直方图和8×8前景占据率做可选视觉统计重排。
- 评分为语义×1、可选几何×0.25、可选视觉统计×0.15的加权平均；分项分数单独输出。
- NPZ精确余弦遍历适合178件规模，避免引入不必要的近似向量服务。SQLite＋向量文件共同构成本地混合数据库，接口不依赖设计模型身份。

## 使用

在paris-builder目录运行：

```sh
.venv/bin/pip install -r knowledge/retrieval/requirements.txt
PYTHONPATH=src .venv/bin/python tools/build_retrieval_index.py --download-model
PYTHONPATH=src .venv/bin/python tools/query_components.py '侧街克制的薄窗套' --family window_assembly --max-width 3 --max-depth 4
PYTHONPATH=src .venv/bin/python tools/query_components.py '入口门廊' --dimensions 5 7 3 --full
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_retrieval.py -v
```

Python接口：`ComponentIndex(directory).query(text, limit=5, family=None, max_width=None, max_depth=None, game_status=None, dimensions=None, reference_image=None)`。返回候选ID、分项分数、原始证据和必须试装的状态；不能直接视为生产准入。

## 实测

5项测试通过：178件证据无损、向量维度与归一化、中文语义召回、硬条件过滤与未知游戏状态、复现性、几何和视觉信号分离。示例保存在`knowledge/retrieval/demo_queries.json`。无family过滤时，“屋顶排放烟气的烟囱”首位为chimney-v1，“入口门廊”首位为portal-v1。

## 不可越过的边界

1. 视觉统计不是CLIP类视觉语义模型，也不具有三维理解能力；卡片背景和文字会影响它，只能低权重辅助。真正的多视图判断交给运行工作流的多模态模型，并保存证据。
2. 尚无独立人工标注的大规模检索基准；少量冒烟测试不能证明所有建筑意图均可正确召回。
3. 候选源窗中包含模组状态；原始状态与转译分别保留，检索不保证原版等价。
4. 178件都是候选，游戏验证仍NOT_RUN。当前family级派生配方语义较短，无法从文字补出不存在的深入构法解释。
5. 文本最多128 token；只编码优先建筑解释与材料类别，完整状态始终保存数据库，不依靠文本截断结果保存证据。
6. 索引需随catalog更新重建。返回尺寸是当前实物裁件的包围盒；不能把配方支持的尺寸范围误当作当前裁件尺寸。
