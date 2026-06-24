# CLAUDE.md

本文档为 Claude Code (claude.ai/code) 在本项目中工作时提供指导。

## 项目概述

优惠推荐 Agent (001-promo-recommend-agent):主 Agent + LP 子 Agent 多 Agent 推荐系统,
H5 通过对话接口调用,Agent 编排工具,数据来自离线管线与运行时服务。

## 顶层目录

```
recommand/
├── specs/                    # 设计文档(Spec Kit 工作流产物)
│   └── 001-promo-recommend-agent/
├── agent-platform/           # 运行时 + 离线实现
│   ├── data-pipeline/        # 离线数据处理管线(Spark 批处理)
│   ├── main-agent/           # 主 Agent(对话入口、Session、跨子 Agent 编排)— tasks.md 待实现
│   └── local-promo-agent/    # LP 子 Agent(推荐/下单/券包/排除)— tasks.md 待实现
├── CLAUDE.md                 # 本文件
└── .specify/                 # Spec Kit 工作流脚本
```

## 常用命令

```bash
# 离线数据管线(全部 4 步一键跑)
cd agent-platform/data-pipeline
python run_pipeline.py --config configs/datasets/meituan_coupon.yaml --output-dir ./pipeline_output

# 离线数据管线(分步)
python run_audit.py             --config configs/datasets/meituan_coupon.yaml
python run_cleaning.py          --config configs/datasets/meituan_coupon.yaml --output ./pipeline_output/cleaned
python run_normalization.py     --config configs/datasets/meituan_coupon.yaml --input  ./pipeline_output/cleaned --output ./pipeline_output/normalized
python run_feature_extraction.py --config configs/datasets/meituan_coupon.yaml --input ./pipeline_output/normalized

# 数据管线测试(需安装 pyspark + pytest)
pip install -r agent-platform/data-pipeline/requirements.txt pytest
pytest agent-platform/data-pipeline/tests/ -v
```

## 离线管线 ↔ 运行时 Agent 数据契约

| 离线产出 | 运行时消费者 | 用途 |
|----------|-------------|------|
| `item_features` | LP Agent → ES 索引 | 候选粗排 / 过滤 |
| `user_features` | Preference Store + 画像服务 | 冷启动检测 / 个性化召回 |
| `user_interaction_history` | LP Agent → ES 长序列索引 | 序列召回 / 重排 |
| `co_purchase` | LP Agent → ES I2I 索引 | 联想召回 / I2I 推荐 |
| `impression_log`(stub) | OLAP 离线分析 | AUC / 转化分析(待 LP 主流程落盘 conversation_trace 后开启) |

## Spec Kit 设计产物(从 spec.md 起读)

- **设计文档**:`specs/001-promo-recommend-agent/`
  - `plan.md` — 技术栈、库选择、项目结构
  - `spec.md` — 8 个用户故事(P1~P8)+ 38 个 FR + 9 个 SC
  - `research.md` — 10 个技术决策 + 5 个集成模式
  - `data-model.md` — 14 个实体 + 状态机
  - `contracts/` — Envelope + gRPC + H5 SSE 协议
  - `quickstart.md` — 8 + 8 场景 + 3 性能基线
  - `tasks.md` — 140 个实施任务(按 US 拆分)

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
/opt/recommand/recommand/agent-platform/training-data-synonym/specs/plan.md

Supporting design artifacts:
- Spec: /opt/recommand/recommand/agent-platform/training-data-synonym/specs/spec.md
- Research: /opt/recommand/recommand/agent-platform/training-data-synonym/specs/research.md
- Data Model: /opt/recommand/recommand/agent-platform/training-data-synonym/specs/data-model.md
- Contracts: /opt/recommand/recommand/agent-platform/training-data-synonym/specs/contracts/
- Quickstart: /opt/recommand/recommand/agent-platform/training-data-synonym/specs/quickstart.md
<!-- SPECKIT END -->
