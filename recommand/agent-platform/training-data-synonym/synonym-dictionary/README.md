# 同义词词表生成

**目录**: `agent-platform/training-data-synonym/synonym-dictionary/`
**业务对齐**: 兴业银行信用卡 O2O 推荐系统
**数据源**: `dim_dictionary_snapshot.yaml` (Stage 1 产出)

## 用途

为 ES 检索生成同义词词表 + 分词词典。每个标签词独立送入 LLM 生成同义词，合并去重后产出两种格式。

## 命令行

```bash
cd agent-platform/training-data-synonym
export OPENAI_API_KEY="sk-xxx"

python -m training_data.cli generate-synonyms \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml \
    --provider openai_compat
```

## 产物

| 文件 | 格式 | 用途 |
|------|------|------|
| `ext_synonyms.txt` | `凉茶, herbal tea, 草药茶` | ES `synonym_graph` filter |
| `ext_dict.txt` | 一行一词 | IK 分词词典 (`ext_dict`) |
| `synonyms_meta.json` | JSON | 元信息(版本/时间/统计) |

## 实现原理

1. 读取 `dim_dictionary_snapshot.yaml` → 提取各维度唯一值
2. 每个词独立送入 LLM → 生成中英文同义词
3. 合并重叠组 → 去重 → 写入

Prompt 模板: `configs/prompts/synonym_generation.txt`

## 目录

```
synonym-dictionary/
├── synonym_builder/          # LLM 驱动同义词生成器
│   └── builder.py            # 核心逻辑
├── configs/prompts/          # Prompt 模板
│   └── synonym_generation.txt
├── output/                   # 产出目录
│   ├── ext_synonyms.txt      # 同义词词表
│   ├── ext_dict.txt          # 分词词表
│   └── synonyms_meta.json
└── specs/                    # 设计文档
```

## 不依赖

- ✅ 0 品牌字典/品类字典（不再需要配置文件）
- ✅ 0 embedding 模型
- ✅ 0 Spark

## 相关

- 训练数据生成: `../training_data/`
- Prompt 模板: `configs/prompts/synonym_generation.txt`
