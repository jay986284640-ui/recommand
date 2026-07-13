"""training_data: 兴业 O2O 三品类 SFT 语料生成流水线。

Stage 1 (enrich): Hive 行级原始单据 → 8 维商业属性标签 + tag_source 三族枚举。
Stage 2 (sft):    Stage 1 输出 → 最多 5 轮多轮对话训练样本。
Postprocess:      7 类清洗 + 8 项分布 + 80/10/10 hash 划分。

Public entry: `python -m training_data.cli`
"""

__version__ = "2.0.0"
__format_versions__ = {
    "item_tags": "item_tags_v2",
    "sft_corpus": "sft_corpus_v2",
    "table_meta": "table_meta_v1",
    "train_split": "train_split_v1",
    "distribution_report": "distribution_report_v1",
}