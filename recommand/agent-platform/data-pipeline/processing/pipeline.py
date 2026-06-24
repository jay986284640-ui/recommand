"""统一数据处理流程"""

import logging
from typing import Optional, Dict, Any, List
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from .filters import (
    FieldCompletenessFilter,
    TimeFilter,
    KCoreFilter,
    DeduplicateFilter,
    BurstReviewFilter,
    UserItemDeduplicateFilter,
    ProductExistsFilter,
    RuleBasedFilter,
    DynamicFilter,
)
from .normalizers import (
    HtmlNormalizer,
    LowercaseNormalizer,
    SpecialCharNormalizer,
    UnicodeNormalizer,
    WhitespaceNormalizer,
    RegexReplaceNormalizer,
    RegexExtractNormalizer,
)
from .config_loader import Config
from .writers import StandardDataWriter


logger = logging.getLogger(__name__)


class UnifiedPipeline:
    """
    统一数据处理流程

    整合数据清洗、文本标准化、特征提取功能，处理流程：
    1. 加载数据（通过 Adapter）
    2. 交互数据清洗（字段完整性 -> 业务过滤 -> 级联过滤）
    3. 用户/物品基于有效交互ID过滤（级联过滤）
    4. 文本字段标准化
    5. 特征提取与序列构建
    6. 输出多个文件
    """

    def __init__(self, config: Config, items_df=None):
        """
        初始化统一处理流程

        Args:
            config: 配置对象
            items_df: 物品数据 DataFrame（用于商品存在性过滤）
        """
        self.config = config
        self.stats: List[Dict[str, Any]] = []
        self.items_df = items_df  # 保存物品数据用于过滤

    def _build_interaction_filters(self) -> List:
        """构建交互数据过滤器列表"""
        filters = []
        cleaning = self.config.cleaning

        # 1. 字段完整性过滤
        if cleaning.field_completeness:
            filters.append(FieldCompletenessFilter(
                required_fields=cleaning.required_fields
            ))

        # 2. 商品存在性过滤（需要物品数据）
        if cleaning.product_exists and self.items_df is not None:
            filters.append(ProductExistsFilter(items_df=self.items_df))

        # 3. 字段完整性过滤后直接应用通用规则过滤
        # (质量过滤通过 interaction_rules 配置)

        # 4. 时间过滤
        if cleaning.time:
            filters.append(TimeFilter(years=cleaning.years))

        # 5. 通用规则过滤 - 交互数据
        if cleaning.interaction_rules:
            filters.append(RuleBasedFilter(
                rules=cleaning.interaction_rules,
                logic=cleaning.interaction_rules_logic
            ))

        # 6. 去重
        if cleaning.deduplicate:
            filters.append(DeduplicateFilter(key_column=cleaning.dedup_column))

        # 7. 突发评论过滤
        if cleaning.burst_review:
            filters.append(BurstReviewFilter(
                time_window_minutes=cleaning.burst_window_minutes,
                max_reviews=cleaning.burst_max_reviews
            ))

        # 8. 用户-物品连续去重
        if cleaning.user_item_dedup:
            filters.append(UserItemDeduplicateFilter())

        # 9. K-core 过滤（最后执行）
        if cleaning.kcore:
            filters.append(KCoreFilter(
                k=cleaning.kcore_k,
                checkpoint_dir=cleaning.kcore_checkpoint_dir
            ))

        return filters

    def _build_user_filters(self) -> List:
        """构建用户数据过滤器列表"""
        filters = []
        cleaning = self.config.cleaning

        if cleaning.user_rules:
            filters.append(RuleBasedFilter(
                rules=cleaning.user_rules,
                logic=cleaning.user_rules_logic
            ))

        return filters

    def _build_item_filters(self) -> List:
        """构建物品数据过滤器列表"""
        filters = []
        cleaning = self.config.cleaning

        if cleaning.item_rules:
            filters.append(RuleBasedFilter(
                rules=cleaning.item_rules,
                logic=cleaning.item_rules_logic
            ))

        return filters

    def _build_normalizers(self, df_config: list) -> Dict:
        """
        根据 DataFrame 配置构建文本规范化器字典

        Args:
            df_config: 当前 DataFrame 的 normalizer 配置列表

        Returns:
            {normalizer_name: normalizer_instance}
        """
        norm = self.config.normalization
        if not norm.enabled or not df_config:
            return {}

        # normalizer 名称到类的映射
        SIMPLE_NORMALIZERS = {
            'html_normalizer': HtmlNormalizer,
            'unicode_normalizer': UnicodeNormalizer,
            'special_char_normalizer': SpecialCharNormalizer,
            'lowercase': LowercaseNormalizer,
            'whitespace_normalizer': WhitespaceNormalizer,
        }

        normalizers = {}

        # 收集该表需要的 normalizer
        for config_item in df_config:
            normalizer_name = config_item.get('normalizer')
            if not normalizer_name:
                continue

            # 简单 normalizer（无额外参数）
            if normalizer_name in SIMPLE_NORMALIZERS:
                if normalizer_name not in normalizers:
                    normalizers[normalizer_name] = SIMPLE_NORMALIZERS[normalizer_name]()
                continue

            # regex_replace_normalizer - 从 columns 配置中提取 rules
            if normalizer_name == 'regex_replace_normalizer':
                if 'regex_replace_normalizer' not in normalizers:
                    normalizers['regex_replace_normalizer'] = RegexReplaceNormalizer()
                regex_normalizer = normalizers['regex_replace_normalizer']
                self._add_regex_replace_rules(regex_normalizer, config_item.get('columns', []))
                continue

            # regex_extract_normalizer - 从 columns 配置中提取每列规则
            if normalizer_name == 'regex_extract_normalizer':
                if 'regex_extract_normalizer' not in normalizers:
                    normalizers['regex_extract_normalizer'] = RegexExtractNormalizer()
                extract_normalizer = normalizers['regex_extract_normalizer']
                self._add_regex_extract_columns(extract_normalizer, config_item.get('columns', []))

        return normalizers

    def _add_regex_replace_rules(self, regex_normalizer: RegexReplaceNormalizer, columns_config: list):
        """为正则替换规范化器添加规则"""
        for col_config in columns_config:
            if isinstance(col_config, dict) and 'rules' in col_config:
                for rule in col_config['rules']:
                    if 'pattern' in rule and 'replacement' in rule:
                        regex_normalizer.add_rule(rule['pattern'], rule['replacement'])

    def _add_regex_extract_columns(self, extract_normalizer: RegexExtractNormalizer, columns_config: list):
        """为正则提取规范化器添加列规则"""
        for col_config in columns_config:
            if isinstance(col_config, dict) and 'name' in col_config:
                col_name = col_config['name']
                rule = {
                    'pattern': col_config.get('pattern', ''),
                    'group': col_config.get('group', 1),
                    'remove': col_config.get('remove', ''),
                    'default': col_config.get('default', '')
                }
                if rule['pattern']:
                    extract_normalizer.columns[col_name] = rule

    def _run_normalizers_by_config(self, df: DataFrame, df_name: str) -> DataFrame:
        """
        根据配置为指定 DataFrame 应用文本标准化

        Args:
            df: 输入 DataFrame
            df_name: DataFrame 名称 (users/items/interactions)

        Returns:
            处理后的 DataFrame
        """
        norm = self.config.normalization
        if not norm.enabled:
            return df

        # 获取该 DataFrame 的配置
        df_config = norm.df_config.get(df_name, [])

        # 如果没有配置，直接返回结果
        if not df_config:
            return df

        # 根据该表的配置构建 normalizer
        all_normalizers = self._build_normalizers(df_config)
        if not all_normalizers:
            return df

        logger.info("文本标准化 - %s", df_name)

        result = df
        for config_item in df_config:
            normalizer_name = config_item.get('normalizer')
            columns_config = config_item.get('columns', [])

            if normalizer_name not in all_normalizers:
                logger.warning("未找到 normalizer '%s'", normalizer_name)
                continue

            normalizer = all_normalizers[normalizer_name]

            # 处理 columns_config：支持两种格式
            # 1. 简单列名: ["col1", "col2"]
            # 2. 带规则: [{name: "col1", pattern: "...", rules: [...]}, ...]
            for col_config in columns_config:
                if isinstance(col_config, str):
                    col_name = col_config
                elif isinstance(col_config, dict):
                    col_name = col_config.get('name')
                else:
                    logger.warning("跳过无效的列配置: %s", col_config)
                    continue

                if not col_name or col_name not in result.columns:
                    continue

                # 检查列类型是否支持
                if normalizer.is_column_supported(result, col_name):
                    result = normalizer.process(result, col_name)
                    logger.info("应用: %s -> %s", normalizer.name, col_name)
                else:
                    logger.warning("跳过列 '%s': 类型不支持", col_name)

        return result

    def _run_filters(self, df: DataFrame, filters: List, step_name: str) -> DataFrame:
        """运行过滤器列表"""
        logger.info("%s", step_name)

        result = df
        before_count = result.count()
        for i, filter_obj in enumerate(filters, 1):    
            logger.info("步骤 %d: %s (过滤前: %d)", i, filter_obj.name, before_count)

            result = filter_obj.filter(result)

            after_count = result.count()
            removed = before_count - after_count

            logger.info("步骤 %d: %s (过滤后: %d, 移除: %d, %.2f%%)",
                       i, filter_obj.name, after_count, removed,
                       removed/before_count*100 if before_count > 0 else 0)

            self.stats.append({
                "step": step_name,
                "filter": filter_obj.name,
                "before": before_count,
                "after": after_count,
                "removed": removed
            })

            before_count = after_count

        return result

    def _cascade_filter(self, users_df: DataFrame, items_df: DataFrame,
                       interactions_df: DataFrame) -> tuple:
        """
        级联过滤 - 确保用户/物品 ID 在交互记录中出现

        Args:
            users_df: 用户数据
            items_df: 物品数据
            interactions_df: 交互数据

        Returns:
            (过滤后的用户DF, 过滤后的物品DF, 过滤后的交互DF)
        """
        logger.info("级联过滤 - 数据一致性保证")

        # 从交互数据中提取有效的用户和物品 ID
        valid_user_ids = interactions_df.select("user_id").distinct()
        valid_item_ids = interactions_df.select("item_id").distinct()

        valid_user_count = valid_user_ids.count()
        valid_item_count = valid_item_ids.count()

        logger.info("有效用户数: %d, 有效物品数: %d", valid_user_count, valid_item_count)

        # 用户表内连接过滤
        filtered_users = users_df.join(valid_user_ids, "user_id", "inner")

        # 物品表内连接过滤
        filtered_items = items_df.join(valid_item_ids, "item_id", "inner")

        valid_user_count_1 = filtered_users.count()
        valid_item_count_1 = filtered_items.count()

        self.stats.append({
            "step": "级联过滤",
            "filter": "用户ID过滤",
            "before": 1,
            "after": valid_user_count_1,
            "removed": 1
        })

        self.stats.append({
            "step": "级联过滤",
            "filter": "物品ID过滤",
            "before": 1,
            "after": valid_item_count_1,
            "removed": 1
        })

        return filtered_users, filtered_items, interactions_df

    def _build_user_sequences(self, interactions_df: DataFrame) -> DataFrame:
        """
        构建用户行为序列

        Args:
            interactions_df: 交互数据

        Returns:
            用户行为序列 DataFrame
        """
        logger.info("构建用户行为序列")

        # 按用户分组，按时间排序，收集交互记录
        window = Window.partitionBy("user_id").orderBy("timestamp")

        # 构建结构体
        interactions_with_struct = interactions_df.withColumn(
            "interaction_struct",
            F.struct(*[c for c in interactions_df.columns if c != "user_id"])
        )

        # 按用户分组，排序并收集
        user_sequences = interactions_with_struct.groupBy("user_id").agg(
            F.collect_list("interaction_struct").alias("interaction_history")
        )

        # 对历史记录按时间排序
        user_sequences = user_sequences.withColumn(
            "interaction_history",
            F.array_sort(
                "interaction_history",
                lambda x, y: F.when(x.timestamp < y.timestamp, -1)
                              .when(x.timestamp > y.timestamp, 1)
                              .otherwise(0)
            )
        )

        logger.info("序列构建完成: %d 个用户", user_sequences.count())

        return user_sequences

    def process(self, users_df: DataFrame, items_df: DataFrame,
                interactions_df: DataFrame,
                co_occurrence_df: Optional[DataFrame] = None) -> Dict[str, DataFrame | None]:
        """
        执行完整的数据处理流程

        Args:
            users_df: 用户数据
            items_df: 物品数据
            interactions_df: 交互数据
            co_occurrence_df: 共现数据（可选）

        Returns:
            处理后的数据字典
        """
        logger.info("开始数据处理流程")

        # Step 1: 交互数据清洗
        logger.info("Step 1: 交互数据清洗")
        interaction_filters = self._build_interaction_filters()
        cleaned_interactions = self._run_filters(
            interactions_df, interaction_filters, "交互数据清洗"
        )

        # Step 2: 级联过滤 - 保证数据一致性
        logger.info("Step 2: 级联过滤")
        filtered_users, filtered_items, final_interactions = self._cascade_filter(
            users_df, items_df, cleaned_interactions
        )

        # Step 3: 文本标准化 - 根据配置分别为不同 DataFrame 应用不同的 normalizer
        logger.info("Step 3: 文本标准化")
        normalized_users = self._run_normalizers_by_config(filtered_users, "users")
        normalized_items = self._run_normalizers_by_config(filtered_items, "items")
        normalized_interactions = self._run_normalizers_by_config(final_interactions, "interactions")
        
        # Step 4: 构建用户行为序列
        logger.info("Step 4: 构建用户行为序列")
        user_sequences = self._build_user_sequences(normalized_interactions)

        # Step 5: 共现数据过滤（如果有）
        filtered_co_occurrence = None
        if co_occurrence_df is not None:
            logger.info("Step 5: 共现数据过滤")
            valid_item_ids = normalized_interactions.select("item_id").distinct()
            filtered_co_occurrence = co_occurrence_df.join(
                valid_item_ids, "item_id", "inner"
            )
            # 清除无效共现信息
            filtered_co_occurrence = self._filter_related_items(filtered_co_occurrence, valid_item_ids)

            logger.info("共现数据过滤后: %d", filtered_co_occurrence.count())

        # 打印统计信息
        self._print_stats()
        return {
            "users": normalized_users,
            "items": normalized_items,
            "interactions": normalized_interactions,
            "user_sequences": user_sequences,
            "co_occurrence": filtered_co_occurrence
        }

    def _filter_related_items(self, co_occurrence_df: DataFrame, valid_ids: DataFrame) -> DataFrame:
        """
        使用 broadcast join 过滤 related_items 字段

        步骤：
        1. explode 将数组展开为多行
        2. 与 valid_products 进行 inner join 过滤
        3. 使用 collect_list 重新聚合为数组
        """
        field_name = "related_items"

        # 展开数组
        exploded = co_occurrence_df.select("item_id", F.explode(F.col(field_name)).alias("relate_item"))

        # 与有效商品进行 inner join 过滤
        valid_products_renamed = valid_ids.withColumnRenamed("item_id", "relate_item")
        filtered = exploded.join(F.broadcast(valid_products_renamed), "relate_item", "inner")

        # 重新聚合为数组
        filtered_agg = filtered.groupBy("item_id").agg(
            F.collect_list("relate_item").alias(field_name)
        )

        # 与原数据合并
        result = co_occurrence_df.drop(field_name).join(filtered_agg, "item_id", "left")
        return result

    def _print_stats(self):
        """打印处理统计信息"""
        logger.info("处理统计汇总")
        for stat in self.stats:
            logger.info("%s - %s: %d -> %d (移除: %d)",
                        stat['step'], stat['filter'],
                        stat['before'], stat['after'], stat['removed'])

    def save_results(self, results: Dict[str, DataFrame]):
        """
        保存处理结果

        Args:
            results: 处理结果字典
        """
        logger.info("保存处理结果")

        writer = StandardDataWriter(
            output_dir=self.config.output.dir,
            format=self.config.output.format
        )

        writer.write_all(
            users_df=results.get("users"),
            items_df=results.get("items"),
            interactions_df=results.get("interactions"),
            sequences_df=results.get("user_sequences"),
            co_occurrence_df=results.get("co_occurrence")
        )
