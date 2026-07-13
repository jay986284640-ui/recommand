# 业务对齐说明:002/003 Spec ↔ 兴业银行 O2O 真实表结构

**Date**: 2026-06-26 (v2.5.1:field_contract + name_inference + 禁隐式 JOIN)
**Spec 源**: `specs/002-training-data-generator/`, `specs/003-synonym-dictionary/`
**业务源**: `tabale_structer.sql`(737 行,7 张业务表 + 1 张埋点表)— **v2.5 起仅作 schema 参考,运行时通过 `configs/tables.yaml` 声明**

---

## 1. 背景

002 / 003 spec 原假设的业务域是 **"美团券推荐"**(`configs/datasets/meituan_coupon.yaml`,
`Str_Quality_Type` / `CouponType` / `FacePrice` / `CurrentPrice` 等字段)。实际客户表结构
来自 **兴业银行信用卡 O2O 推荐系统**,两套业务模型对不上,需要重写训练数据生成与同义词
生成脚本。

| 维度 | 002/003 原 spec | 兴业 O2O 真实业务 | 影响 |
|------|---------------|------------------|------|
| 商品来源 | 美团券模板 | **门店**(咖啡/餐饮/便利店/烘焙连锁) | 改读 `o2o_new_gut_shop_base_third` |
| 商品画像 | 7 维口味标签(味/场/材/域/人/情/就) | **7 维商业属性**(品类/品牌/价格/距离/年龄/场合/口味) | 改 `param_schema` |
| 用户画像 | 通用 user_features | **银行客户画像**(`CDM_ADM_CUST_INFO_STAT_F`,CIF 客户号 + 性别/年龄/收入/资产/职业) | 训练时 user 端接 `MASTERCARD_CUST_ID` |
| 行为来源 | 交互序列 | **神策埋点**(`c10_ods_events_xysh`,`prd_cd`/`prd_nm`/`eqty_nm`/`kywrd`/`actv_ttl`) | 检索信号来自埋点 |
| 推荐产出 | 券 / 商品 | **门店 + 权益券**(`o2o_new_gut_coupon_template`,`FacePrice` / `CurrentPrice` / `UseScope`) | 输出侧补券信息 |
| 触发端 | 通用 LP Agent | **兴业生活 App**(基于 `c10_ods_events_xysh.app_name` 区分) | 触发位置字段 |

---

## 2. 训练数据 params schema(7 维商业属性)

替代原 spec 的 7 维口味标签(味/场/材/域/人/情/就),对齐 LP Agent 实际提参模型。

```yaml
# configs/dim_dictionary.yaml
dims:
  # ──── 商品侧 4 维 ────
  category:
    desc: 品类(咖啡/快餐/奶茶/烘焙/便利店/中餐/西餐)
    values: [咖啡, 快餐, 奶茶, 烘焙, 便利店, 中餐, 西餐, 日料, 火锅, 烧烤, 甜品, 水果]
    op: in
  merchant:
    desc: 品牌(星巴克/KFC/麦当劳/瑞幸/喜茶...)
    values: < 从 o2o 门店 Brnd_Nm 动态抽取 + 品牌词典补全 >
    op: in
  avg_prc:
    desc: 人均价格区间
    values:
      - "0-30"     # 便利店 / 平价快餐
      - "30-50"    # 奶茶 / 烘焙
      - "50-100"   # 主流餐饮
      - "100-200"  # 中高端
      - "200+"     # 高端
    op: in
  distance:
    desc: 用户到门店距离(米)
    values:
      - "0-500"
      - "500-1000"
      - "1000-3000"
      - "3000+"
    op: in

  # ──── 用户侧 3 维 ────
  age:
    desc: 客户年龄段(从 CDM.SEX_ID + 推断)
    values: [18-25, 25-35, 35-45, 45-55, 55+]
    op: in
  occasion:
    desc: 消费场合
    values: [早餐, 午餐, 下午茶, 晚餐, 夜宵, 聚会, 工作日, 周末, 节日, 自取, 外卖, 堂食]
    op: in
  taste:
    desc: 口味偏好
    values: [甜, 咸, 辣, 麻, 酸, 苦, 鲜, 清淡, 浓郁, 冰, 热, 温]
    op: contains   # 数组语义,允许多值
```

**op 类型**(沿用 spec 002):
- `eq` — `distance` / `avg_prc` 单值匹配
- `in` — 集合包含
- `contains` — 数组语义(用户说"不要太甜的",反向 `not_in: [甜]`)
- `not_in` — 反向(用于负样本)

---

## 3. 同义词词表 3 源(对齐真实门店)

| 源 | 中心 | 数据来源 | 扩量 |
|----|------|----------|------|
| 规则(品牌词典) | **Str_Nm / Brnd_Nm**(连锁品牌) | `brand_dictionary.yaml`(现 33 → 扩 60+) | 运营手动维护 |
| 规则(品类词典) | **Cat_Nm**(品类中文) | `category_dictionary.yaml`(50+ 品类别名,如"咖啡" = "coffee" = "拿铁馆") | 运营手动维护 |
| LLM 抽取 | 商品名 / 通用商品词 | mock-llm 从门店名 + 品类生成同义词 | 启发式模板 |
| 简单聚类 | 商品名词 | 字符 n-gram Jaccard 相似度 ≥ 0.7 聚类(不依赖 sentence-transformers) | 离线 |

**反义词表**(内置 50+ 对,代码中常量,非 yaml):
- 程度:大/小,高/低,长/短,多/少,胖/瘦
- 温度:热/冷,温/凉,冰/烫
- 味道:甜/咸/辣/酸/苦,浓/淡,鲜/涩
- 方向:左/右,上/下,前/后,里/外
- 状态:好/坏,新/旧,干/湿,生/熟
- 数量:有/无,加/减,满/空
- 速度:快/慢,早/晚
- 时间:今/明,日/夜
- 偏好:喜欢/讨厌,接受/拒绝

---

## 4. 数据流(对齐真实业务,v2.5)

```
                  configs/tables.yaml (v2.5 — 取代 SQL 解析)
                  db / name / role / columns / type / sensitive
                              │
            ┌─────────────────┼─────────────────┐
            ↓                 ↓                 ↓
   o2o_new_gut_shop_    CDM_ADM_CUST_     c10_ods_events_
   base_third           INFO_STAT_F        xysh
   (门店 + 品类)        (客户画像)         (埋点)
            │                 │                 │
            └─────────────────┼─────────────────┘
                              ↓
              ┌───────────────────────────────────┐
              │ training_data/           │
              │   common/tables_config.py        │
              │   load_tables_config(yaml)       │
              │   → list[TableMeta]              │
              │   (校验 + sensitive 自动派生)     │
              └───────────────┬───────────────────┘
                              ↓
              ┌───────────────┴───────────────┐
              ↓                               ↓
    ┌──────────────────────┐      ┌──────────────────────┐
    │ cli extract-dict.    │      │ cli enrich           │
    │ (Stage 0,扩量)       │      │ (Stage 1,补全标签)   │
    │ brand/category diff  │      │ item_tags.jsonl      │
    └──────────────────────┘      └──────────┬───────────┘
                                            ↓
                                ┌──────────────────────┐
                                │ cli sft → split →    │
                                │ verify               │
                                │ (Stage 2 + split +   │
                                │  SC verify)          │
                                └──────────────────────┘
```

> **v2.5.1 变更**(2026-06-26):
> - **字段契约(`_meta.field_contract`)**:每种 role 声明 required/optional 字段,
>   loader 加载时校验。修复了"上游 SQL 缺字段代码静默失败"的隐患。
> - **禁隐式 JOIN**:`extract_geo` 不再接受 `address_row` 参数。
>   自拓展门店的 `Lng`/`Lat` 必须由上游 SQL 把 `o2o_new_gut_shop_address` JOIN 进来
>   (或 fixture pre-join);代码不主动做跨表查询。
> - **名称 fallback 推断**(`name_inference.py`):当 `Brnd_Nm` / `Cat_Nm` / `productDesc`
>   为空或为券抢购规则文案(满50减10 / 代金券 / 限时抢购),从商品名称(`Str_Nm` /
>   `shopName` / `couponName`)按字典值做最长子串匹配,推断 brand / category / taste /
>   occasion;规则文案识别命中即整体抑制该 item 推断(避免误判)。
> - **可观测**:新增 `LLMEnricher.inferred_used_count` / `ConsumableMapper.inferred_count`
>   + `logger.info("name_hint_used", ...)` 结构化日志;end-to-end demo 覆盖率
>   coverage_avg 从 3.75 提升到 4.24(品牌/分类维度从空 → 推断补齐)。
>
> **v2.5 变更**(基线):旧版用 `scripts/sql_parser.py` 正则解析 `tabale_structer.sql` 推断 schema,
> 已被 `common/tables_config.load_tables_config(yaml)` 取代。新增可观测性:
> 字典 reject 计数 / 失败盘 / T097 日志;新增真实 LLM 客户端(`OpenAICompatClient`)。

---

## 5. 不在本目录范围(留给运行时)

- **LP Agent envelope 协议**:运行时负责
- **001 增强管线的 `ai_enhance/`**:001 spec 也说"待实现",002/003 脚本不依赖它
- **真实 LLM SDK**:本目录用 mock-llm,真 LLM 接入由后续 US 处理
- **Embedding 模型**:不依赖 `bge-small-zh`,改用字符 n-gram 简单聚类(本地无依赖)

---

## 6. 文件清单(本目录)

| 文件 | 用途 |
|------|------|
| `docs/ALIGNMENT_cib_o2o.md` | 本文档 |
| `configs/tables.yaml` | **v2.5 新** — 表结构声明(取代 sql_parser) |
| `training_data/common/tables_config.py` | **v2.5 新** — YAML 加载器 |
| `training_data/common/llm_client.py` | MockLLMClient + OpenAICompatClient (v2.5) |
| `scripts/sql_parser.py` | 旧版 regex 解析,保留兼容不再被 demo 调用 |
| `scripts/mock_llm_client.py` | 旧版 heuristic mock,保留参考 |
| `configs/dim_dictionary.yaml` | 8 维商业属性字典(merchant 82 / occasion 13 / taste 14) |
| `configs/brand_dictionary.yaml` | 60+ 连锁品牌 canonical + 变体 |
| `configs/consumable_type_map.yaml` | category → 吃/喝 映射 |
| `configs/intent_keywords.yaml` | 5 类 intent 关键词 |
| `configs/sentence_templates.yaml` | 句式骨架 |
| `configs/pipeline.yaml` | 顶层配置(provider / ratios / paths) |
| `scripts/demo.sh` | **v2.5 更新** — 一键 demo(走新 CLI 4 段) |
| `README.md` | 入口文档(v2.5 含 YAML / 真实 LLM / 可观测性说明) |
