# CLAUDE.md

本文档为 Claude Code (claude.ai/code) 在本项目中工作时提供指导。

## 项目概述

优惠推荐 Agent (001-promo-recommend-agent):主 Agent + LP 子 Agent 多 Agent 推荐系统,
H5 通过对话接口调用,Agent 编排工具,数据来自离线管线与运行时服务。

## 顶层目录

```
recommand/
├── agent-platform/
│   ├── data-pipeline/            # 离线数据处理管线(Spark 批处理)
│   ├── training-data-synonym/    # 训练数据生成管线(标签+SFT语料+同义词)
│   │   ├── training_data/        # Python 包(enricher/sft/cli/common)
│   │   ├── synonym-dictionary/   # 同义词生成模块
│   │   ├── configs/              # tables.yaml / pipeline.yaml / prompts
│   │   └── output/               # 产出目录(stage1/stage2/sft)
│   ├── main-agent/               # 主 Agent(待实现)
│   └── local-promo-agent/        # LP 子 Agent(待实现)
├── knowledge_database/           # 原始 CSV 数据
└── specs/                        # 设计文档
```

## 常用命令

### 训练数据管线

```bash
cd agent-platform/training-data-synonym

# 环境变量(API Key)
export OPENAI_API_KEY="sk-xxx"

# Stage 1: 标签抽取 → dim_dictionary_snapshot.yaml
python -m training_data.cli extract-tags \
    --source csv --output-dir output/stage1 \
    --frequency-min 1 --provider openai_compat

# Stage 2: 字典约束标注 → item_tags.jsonl + item_profile.jsonl
python -m training_data.cli enrich \
    --source csv --output-dir output/stage2 \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml \
    --provider openai_compat

# Stage 3: SFT 语料合成 → train.jsonl + test.jsonl
python -m training_data.cli sft \
    --input output/stage2/item_profile.jsonl \
    --output-dir output/sft \
    --provider openai_compat \
    --count-per-item 8 --max-items 1000

# 同义词生成 → ext_dict.txt + ext_synonyms.txt
python -m training_data.cli generate-synonyms \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml \
    --provider openai_compat

# 测试用(限制条数)
head -10 output/stage2/item_profile.jsonl > /tmp/test.jsonl
python -m training_data.cli sft --input /tmp/test.jsonl --provider openai_compat --max-items 10
```

### 离线数据管线

```bash
cd agent-platform/data-pipeline
python run_pipeline.py --config configs/datasets/meituan_coupon.yaml --output-dir ./pipeline_output
pip install -r requirements.txt pytest
pytest tests/ -v
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
