# 同义词词表生成

**目录**: `agent-platform/synonym-dictionary/`
**业务对齐**: 兴业银行信用卡 O2O 推荐系统(门店 + 权益券)
**数据源**: 品牌词典 + 品类词典(mock-llm 抽取触发用 o2o 门店名)

## 用途

为 ES 检索生成同义词词表。`synonyms_solr.txt` 可被 ES `synonym_graph` filter 直接消费,提升"用户搜任一词召回所有同义商品"的准确率。

## 4 源混合(沿用 spec 003 D-007 合并去重)

1. **品牌词典**(`configs/brand_dictionary.yaml`,60+ 品牌)
2. **品类词典**(`configs/category_dictionary.yaml`,30+ 品类)
3. **mock-llm 抽取**(从门店名启发式扩展同义变体)
4. **字符 n-gram 聚类**(替代 embedding,无 bge-small-zh 依赖)

合并后:
- 长度限制(单词 ≤ 20 字,每组 2~10 词)
- 反义词过滤(内置 50+ 对,SC-004)
- 去重(多源标记,source 字段)

## 目录

```
synonym-dictionary/
├── README.md                            # 本文档
├── specs/                               # 003 原始 spec 文档
│   ├── spec.md
│   ├── plan.md
│   ├── tasks.md
│   ├── data-model.md
│   └── contracts/
│       └── solr_synonyms_format.md
├── configs/
│   ├── brand_dictionary.yaml            # 60+ 品牌
│   └── category_dictionary.yaml         # 30+ 品类
├── scripts/
│   ├── sql_parser.py                    # SQL 表结构解析(占位)
│   ├── mock_llm_client.py               # 本地启发式 mock-llm
│   ├── generate_synonyms.py             # 主入口
│   ├── verify.py                        # SC 验证
│   └── demo.sh                          # 一键 demo
```

## 一键 Demo

```bash
bash scripts/demo.sh
# ~ 5s 跑通
```

## 单脚本使用

```bash
python scripts/generate_synonyms.py \
    --brand-dict configs/brand_dictionary.yaml \
    --category-dict configs/category_dictionary.yaml \
    --output-dir /tmp/synonym_output \
    --n-items 50
```

## 产物

| 文件 | 用途 |
|------|------|
| `synonyms_solr.txt` | ES Solr 多向格式(主输出) |
| `synonyms_meta.json` | 元信息(版本/时间/4 源贡献) |
| `synonyms_stats.json` | 统计(组数/覆盖/反义词拒收数) |
| `synonym_rejections.jsonl` | 反义词拒收日志 |

## Solr 输出示例

```text
# 同义词词表 (synonyms_v1)
# Generated at: 2026-06-22T04:03:17Z
# Source distribution: ngram=40%; rule_brand=32%; rule_category=15%; llm=14%
# Total groups: 222
# Embedding model: char_ngram(threshold=0.7)
星巴克咖啡, 星巴克专星送, 星巴克, 星吧克, Starbucks, starbucks, STARBUCKS
luckin coffee, 瑞幸咖啡, Luckin Coffee, luckin, 瑞幸, 瑞幸小蓝杯, Luckin
Costa, costa coffee, COSTA, 哥斯达, 科斯塔
喜茶HEYTEA, Heytea, 喜茶喜, HEYTEA, heytea, 喜茶店, 喜茶
奈雪的茶, NAYUKI, 奈雪茶, 奈雪の茶, nayuki, Nayuki, 奈雪
咖啡, coffee, Coffee, 咖啡店, coffee shop, 咖啡馆, café, Cafe
奶茶, milk tea, Milk Tea, milktea, 茶饮, 奶茶店
...
```

## ES 集成(参考 spec 003)

```json
{
  "settings": {
    "analysis": {
      "filter": {
        "synonym_graph_filter": {
          "type": "synonym_graph",
          "synonyms_path": "synonyms_solr.txt",
          "updateable": true
        }
      }
    }
  }
}
```

## 验证结果

| 项 | 状态 |
|----|------|
| 无空行 | ✅ |
| 注释行无逗号 | ✅ |
| 1 行 1 组 | ✅ (204 组) |
| 单词 ≤ 20 字符 | ✅ |
| 总组数 ≤ 10000 (SC-005) | ✅ |
| 反义词不合并 (SC-004) | ✅ |
| meta._format_version = "synonyms_v1" | ✅ |

## 内置反义词(50+ 对,代码常量)

| 类别 | 例子 |
|------|------|
| 程度 | 大/小, 高/低, 长/短, 多/少 |
| 温度 | 热/冷, 温/凉, 冰/烫 |
| 味道 | 甜/咸/辣/酸/苦, 浓/淡 |
| 方向 | 左/右, 上/下, 前/后, 里/外 |
| 状态 | 好/坏, 新/旧, 干/湿, 生/熟 |
| 数量 | 有/无, 加/减, 满/空 |
| 时间 | 快/慢, 早/晚, 今/明, 日/夜 |

## 不依赖

- ✅ 0 网络
- ✅ 0 LLM API
- ✅ 0 embedding 模型(字符 n-gram 替代)
- ✅ 0 Spark

## 相关

- 训练数据生成:`../training-data/`
- 离线数据管线:`../data-pipeline/`
- 003 spec(参考):`../data-pipeline/specs/003-synonym-dictionary/`
