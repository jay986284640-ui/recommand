# CLAUDE.md

本文档为 Claude Code (claude.ai/code) 在本项目中工作时提供指导。

## 项目概述

基于 Apache Spark 的通用推荐数据集治理工具，用于将 Amazon、TikTok、Taobao 等异构数据源处理、清洗为模型可直接消费的标准化格式。

## 常用命令

```bash
# 运行适配器 - 将原始数据转换为中间格式
python run_adapter.py --config config/datasets/amazon.yaml --output ./intermediate

# 或指定参数
python run_adapter.py --adapter amazon --review-input /path/to/reviews.json --meta-input /path/to/meta.json --output ./intermediate

# 运行处理管道 - 清洗、标准化、构建序列
python run_pipeline.py --config config/datasets/amazon.yaml

# 从中间格式处理
python run_pipeline.py --config config/datasets/amazon.yaml --input ./intermediate --output ./output

# 运行数据分析
python -m data_analysis.main --config data_analysis/config.yaml
```

## 架构设计

系统采用**分层插件架构**：

1. **适配器层 (Adapter)** - 将异构原始数据（JSON/CSV/Parquet）转换为统一中间格式，核心键为 `user_id`、`item_id`、`timestamp`、`action`。每个数据源（Amazon、TikTok 等）有各自继承自 `BaseDataSource` 的适配器类。

2. **处理核心 (Pipeline)** - 按顺序应用过滤器：
   - 字段完整性 → 商品存在性 → 时间过滤 → 规则过滤 → 去重 → 突发评论过滤 → 用户-物品连续去重 → K-core 过滤
   - **级联过滤**：用户表/物品表通过内连接只保留出现在有效交互中的 ID，确保数据一致性

3. **标准化层** - 文本处理（HTML 清理、Unicode 规范化、小写转换、正则替换/提取），可按 DataFrame 类型分别配置

4. **序列构建** - 按用户分组、按时间排序、收集为数组

5. **输出** - 写入标准化文件：`users.json`、`items.json`、`interactions.json`、`user_sequences.json`、`co_occurrence.json`

## 关键文件

- [run_adapter.py](run_adapter.py) - 适配器入口
- [run_pipeline.py](run_pipeline.py) - 处理流程入口
- [adapters/factory.py](adapters/factory.py) - 适配器工厂（注册模式）
- [processing/pipeline.py](processing/pipeline.py) - 核心处理逻辑
- [config/datasets/amazon.yaml](config/datasets/amazon.yaml) - 配置示例

## 配置说明

YAML 配置文件定义适配器选择、过滤规则、标准化设置和 Spark 参数。过滤规则支持算子：`eq`、`range`、`length_gt`、`contains`、`matches`（正则）、`is_in` 等。

## 扩展方式

- **新数据源**：在 `adapters/` 下创建继承 `BaseDataSource` 的适配器类，实现 `load_users()`、`load_items()`、`load_interactions()`、`load_co_occurrence()` 方法
- **新过滤器**：在 `processing/filters/` 下创建继承 `BaseFilter` 的类，或在 YAML 配置中使用声明式规则
- **新标准化器**：在 `processing/normalizers/` 下创建继承 `BaseNormalizer` 的类