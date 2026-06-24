"""通用规则过滤器 - 基于声明式配置的数据过滤"""

import logging
from typing import Any, Dict, List, Optional
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, IntegerType, FloatType, LongType, DoubleType

from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


# 算子定义
class Operators:
    """过滤算子工厂"""

    @staticmethod
    def not_null(df: DataFrame, field: str, params: dict) -> F.Column:
        """非空"""
        return F.col(field).isNotNull()

    @staticmethod
    def is_null(df: DataFrame, field: str, params: dict) -> F.Column:
        """为空"""
        return F.col(field).isNull()

    @staticmethod
    def eq(df: DataFrame, field: str, params: dict) -> F.Column:
        """等于"""
        value = params.get('value')
        return F.col(field) == value

    @staticmethod
    def neq(df: DataFrame, field: str, params: dict) -> F.Column:
        """不等于"""
        value = params.get('value')
        return F.col(field) != value

    @staticmethod
    def gt(df: DataFrame, field: str, params: dict) -> F.Column:
        """大于"""
        value = params.get('value')
        return F.col(field) > value

    @staticmethod
    def gte(df: DataFrame, field: str, params: dict) -> F.Column:
        """大于等于"""
        value = params.get('value')
        return F.col(field) >= value

    @staticmethod
    def lt(df: DataFrame, field: str, params: dict) -> F.Column:
        """小于"""
        value = params.get('value')
        return F.col(field) < value

    @staticmethod
    def lte(df: DataFrame, field: str, params: dict) -> F.Column:
        """小于等于"""
        value = params.get('value')
        return F.col(field) <= value

    @staticmethod
    def range(df: DataFrame, field: str, params: dict) -> F.Column:
        """范围 [min, max]"""
        min_val = params.get('min')
        max_val = params.get('max')
        condition = F.lit(True)
        if min_val is not None:
            condition = condition & (F.col(field) >= min_val)
        if max_val is not None:
            condition = condition & (F.col(field) <= max_val)
        return condition

    @staticmethod
    def length_lt(df: DataFrame, field: str, params: dict) -> F.Column:
        """长度小于"""
        value = params.get('value')
        return F.length(F.col(field)) < value

    @staticmethod
    def length_lte(df: DataFrame, field: str, params: dict) -> F.Column:
        """长度小于等于"""
        value = params.get('value')
        return F.length(F.col(field)) <= value

    @staticmethod
    def length_gt(df: DataFrame, field: str, params: dict) -> F.Column:
        """长度大于"""
        value = params.get('value')
        return F.length(F.col(field)) > value

    @staticmethod
    def length_gte(df: DataFrame, field: str, params: dict) -> F.Column:
        """长度大于等于"""
        value = params.get('value')
        return F.length(F.col(field)) >= value

    @staticmethod
    def length_eq(df: DataFrame, field: str, params: dict) -> F.Column:
        """长度等于"""
        value = params.get('value')
        return F.length(F.col(field)) == value

    @staticmethod
    def length_range(df: DataFrame, field: str, params: dict) -> F.Column:
        """长度范围 [min, max]"""
        min_val = params.get('min')
        max_val = params.get('max')
        length_col = F.length(F.col(field))
        condition = F.lit(True)
        if min_val is not None:
            condition = condition & (length_col >= min_val)
        if max_val is not None:
            condition = condition & (length_col <= max_val)
        return condition

    @staticmethod
    def contains(df: DataFrame, field: str, params: dict) -> F.Column:
        """包含"""
        value = params.get('value')
        return F.col(field).contains(value)

    @staticmethod
    def not_contains(df: DataFrame, field: str, params: dict) -> F.Column:
        """不包含"""
        value = params.get('value')
        return ~F.col(field).contains(value)

    @staticmethod
    def startswith(df: DataFrame, field: str, params: dict) -> F.Column:
        """以...开头"""
        value = params.get('value')
        return F.col(field).startswith(value)

    @staticmethod
    def endswith(df: DataFrame, field: str, params: dict) -> F.Column:
        """以...结尾"""
        value = params.get('value')
        return F.col(field).endswith(value)

    @staticmethod
    def is_in(df: DataFrame, field: str, params: dict) -> F.Column:
        """在列表中"""
        values = params.get('values', [])
        return F.col(field).isin(values)

    @staticmethod
    def not_in(df: DataFrame, field: str, params: dict) -> F.Column:
        """不在列表中"""
        values = params.get('values', [])
        return ~F.col(field).isin(values)

    @staticmethod
    def matches(df: DataFrame, field: str, params: dict) -> F.Column:
        """正则匹配"""
        pattern = params.get('pattern')
        return F.col(field).rlike(pattern)

    @staticmethod
    def not_matches(df: DataFrame, field: str, params: dict) -> F.Column:
        """正则不匹配"""
        pattern = params.get('pattern')
        return ~F.col(field).rlike(pattern)

    @staticmethod
    def is_empty(df: DataFrame, field: str, params: dict) -> F.Column:
        """空字符串"""
        return (F.col(field) == "") | F.col(field).isNull()

    @staticmethod
    def is_not_empty(df: DataFrame, field: str, params: dict) -> F.Column:
        """非空字符串"""
        return (F.col(field) != "") & F.col(field).isNotNull()


# 算子映射
OPERATOR_MAP = {
    'not_null': Operators.not_null,
    'is_null': Operators.is_null,
    'eq': Operators.eq,
    'neq': Operators.neq,
    'gt': Operators.gt,
    'gte': Operators.gte,
    'lt': Operators.lt,
    'lte': Operators.lte,
    'range': Operators.range,
    'length_lt': Operators.length_lt,
    'length_lte': Operators.length_lte,
    'length_gt': Operators.length_gt,
    'length_gte': Operators.length_gte,
    'length_eq': Operators.length_eq,
    'length_range': Operators.length_range,
    'contains': Operators.contains,
    'not_contains': Operators.not_contains,
    'startswith': Operators.startswith,
    'endswith': Operators.endswith,
    'is_in': Operators.is_in,
    'not_in': Operators.not_in,
    'matches': Operators.matches,
    'not_matches': Operators.not_matches,
    'is_empty': Operators.is_empty,
    'is_not_empty': Operators.is_not_empty,
}


class RuleBasedFilter(BaseFilter):
    """
    通用规则过滤器 - 基于声明式配置的数据过滤

    支持的算子：
    - 基础比较: eq, neq, gt, gte, lt, lte, range
    - 字符串长度: length_lt, length_gt, length_eq, length_range
    - 字符串匹配: contains, not_contains, startswith, endswith, matches, not_matches
    - 空值判断: not_null, is_null, is_empty, is_not_empty
    - 列表判断: is_in, not_in
    """

    def __init__(self, rules: List[dict], logic: str = "AND", enabled: bool = True):
        """
        初始化规则过滤器

        Args:
            rules: 规则列表，每条规则格式:
                {
                    "field": "字段名",
                    "operator": "算子名",
                    "value": 值,  # 用于单值算子
                    "values": [值列表],  # 用于列表算子
                    "min": 最小值,  # 用于范围算子
                    "max": 最大值,  # 用于范围算子
                    "pattern": "正则模式"  # 用于正则算子
                }
            logic: 逻辑运算符，"AND" 或 "OR"
            enabled: 是否启用
        """
        super().__init__("规则过滤", enabled)
        self.rules = rules
        self.logic = logic.upper()

    def filter(self, df: DataFrame) -> DataFrame:
        """根据规则过滤数据"""
        if not self.rules:
            return df

        conditions = []

        for rule in self.rules:
            field = rule.get('field')
            operator = rule.get('operator')

            if not field or not operator:
                logger.warning("规则缺少 field 或 operator 字段: %s", rule)
                continue

            # 检查字段是否存在
            if field not in df.columns:
                logger.warning("字段 '%s' 不存在，跳过该规则", field)
                continue

            # 获取算子函数
            if operator not in OPERATOR_MAP:
                logger.warning("未知算子 '%s'，跳过该规则", operator)
                continue

            try:
                op_func = OPERATOR_MAP[operator]
                condition = op_func(df, field, rule)
                conditions.append(condition)
            except Exception as e:
                logger.warning("应用规则失败 %s %s: %s", field, operator, e)
                continue

        if not conditions:
            logger.warning("没有有效的过滤条件")
            return df

        # 组合条件
        if self.logic == "OR":
            combined_condition = F.lit(False)
            for c in conditions:
                combined_condition = combined_condition | c
        else:  # AND
            combined_condition = conditions[0]
            for c in conditions[1:]:
                combined_condition = combined_condition & c

        return df.filter(combined_condition)


class DynamicFilter(BaseFilter):
    """
    动态过滤器 - 从 YAML 配置构建的通用过滤器

    支持在一个过滤器中配置多条规则，适用于不同数据集的不同过滤需求
    """

    def __init__(self, name: str, config: dict, enabled: bool = True):
        """
        初始化动态过滤器

        Args:
            name: 过滤器名称
            config: 配置字典，支持以下格式:
                # 格式1: 简单规则列表
                rules:
                  - field: rating
                    operator: range
                    min: 1
                    max: 5
                  - field: review_text
                    operator: length_gt
                    value: 10

                # 格式2: 多个规则组（每组有自己的逻辑）
                rule_groups:
                  - name: "评分过滤"
                    logic: "AND"
                    rules:
                      - field: rating
                        operator: range
                        min: 1
                        max: 5
                  - name: "文本过滤"
                    logic: "OR"
                    rules:
                      - field: review_text
                        operator: length_gt
                        value: 10
                      - field: review_text
                        operator: is_not_empty
            enabled: 是否启用
        """
        super().__init__(name, enabled)
        self.config = config

    def filter(self, df: DataFrame) -> DataFrame:
        """根据配置过滤数据"""
        result = df

        # 格式1: 简单规则列表
        if 'rules' in self.config:
            rule_filter = RuleBasedFilter(
                rules=self.config['rules'],
                logic=self.config.get('logic', 'AND')
            )
            result = rule_filter.filter(result)

        # 格式2: 多个规则组
        if 'rule_groups' in self.config:
            for group in self.config['rule_groups']:
                group_name = group.get('name', '未命名规则组')
                group_logic = group.get('logic', 'AND')
                group_rules = group.get('rules', [])

                if group_rules:
                    group_filter = RuleBasedFilter(
                        rules=group_rules,
                        logic=group_logic
                    )
                    logger.info("应用规则组: %s (%s)", group_name, group_logic)
                    result = group_filter.filter(result)

        return result