"""声明式规则过滤器(YAML 配置驱动)"""

import logging
from typing import Any, Dict, List
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class Operators:
    """过滤算子工厂(全部静态方法)"""

    @staticmethod
    def not_null(df, field, params):
        return F.col(field).isNotNull()

    @staticmethod
    def is_null(df, field, params):
        return F.col(field).isNull()

    @staticmethod
    def eq(df, field, params):
        return F.col(field) == params.get('value')

    @staticmethod
    def neq(df, field, params):
        return F.col(field) != params.get('value')

    @staticmethod
    def gt(df, field, params):
        return F.col(field) > params.get('value')

    @staticmethod
    def gte(df, field, params):
        return F.col(field) >= params.get('value')

    @staticmethod
    def lt(df, field, params):
        return F.col(field) < params.get('value')

    @staticmethod
    def lte(df, field, params):
        return F.col(field) <= params.get('value')

    @staticmethod
    def range(df, field, params):
        condition = F.lit(True)
        if (mn := params.get('min')) is not None:
            condition = condition & (F.col(field) >= mn)
        if (mx := params.get('max')) is not None:
            condition = condition & (F.col(field) <= mx)
        return condition

    @staticmethod
    def length_lt(df, field, params):
        return F.length(F.col(field)) < params.get('value')

    @staticmethod
    def length_lte(df, field, params):
        return F.length(F.col(field)) <= params.get('value')

    @staticmethod
    def length_gt(df, field, params):
        return F.length(F.col(field)) > params.get('value')

    @staticmethod
    def length_gte(df, field, params):
        return F.length(F.col(field)) >= params.get('value')

    @staticmethod
    def length_eq(df, field, params):
        return F.length(F.col(field)) == params.get('value')

    @staticmethod
    def length_range(df, field, params):
        length_col = F.length(F.col(field))
        condition = F.lit(True)
        if (mn := params.get('min')) is not None:
            condition = condition & (length_col >= mn)
        if (mx := params.get('max')) is not None:
            condition = condition & (length_col <= mx)
        return condition

    @staticmethod
    def contains(df, field, params):
        return F.col(field).contains(params.get('value'))

    @staticmethod
    def not_contains(df, field, params):
        return ~F.col(field).contains(params.get('value'))

    @staticmethod
    def startswith(df, field, params):
        return F.col(field).startswith(params.get('value'))

    @staticmethod
    def endswith(df, field, params):
        return F.col(field).endswith(params.get('value'))

    @staticmethod
    def is_in(df, field, params):
        return F.col(field).isin(params.get('values', []))

    @staticmethod
    def not_in(df, field, params):
        return ~F.col(field).isin(params.get('values', []))

    @staticmethod
    def matches(df, field, params):
        return F.col(field).rlike(params.get('pattern'))

    @staticmethod
    def not_matches(df, field, params):
        return ~F.col(field).rlike(params.get('pattern'))

    @staticmethod
    def is_empty(df, field, params):
        return (F.col(field) == "") | F.col(field).isNull()

    @staticmethod
    def is_not_empty(df, field, params):
        return (F.col(field) != "") & F.col(field).isNotNull()


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
    """基于声明式配置的规则过滤"""

    def __init__(self, rules: List[Dict[str, Any]], logic: str = "AND", enabled: bool = True):
        super().__init__("规则过滤", enabled)
        self.rules = rules
        self.logic = logic.upper()

    def filter(self, df: DataFrame) -> DataFrame:
        if not self.rules:
            return df
        conditions = []
        for rule in self.rules:
            field = rule.get('field')
            operator = rule.get('operator')
            if not field or not operator:
                logger.warning("规则缺少 field 或 operator 字段: %s", rule)
                continue
            if field not in df.columns:
                logger.warning("字段 '%s' 不存在,跳过该规则", field)
                continue
            if operator not in OPERATOR_MAP:
                logger.warning("未知算子 '%s',跳过该规则", operator)
                continue
            try:
                conditions.append(OPERATOR_MAP[operator](df, field, rule))
            except Exception as e:
                logger.warning("应用规则失败 %s %s: %s", field, operator, e)
        if not conditions:
            return df
        if self.logic == "OR":
            combined = F.lit(False)
            for c in conditions:
                combined = combined | c
        else:
            combined = conditions[0]
            for c in conditions[1:]:
                combined = combined & c
        return df.filter(combined)


class DynamicFilter(BaseFilter):
    """从 YAML 配置构建的动态过滤器"""

    def __init__(self, name: str, config: dict, enabled: bool = True):
        super().__init__(name, enabled)
        self.config = config

    def filter(self, df: DataFrame) -> DataFrame:
        result = df
        if 'rules' in self.config:
            result = RuleBasedFilter(
                rules=self.config['rules'],
                logic=self.config.get('logic', 'AND'),
            ).filter(result)
        if 'rule_groups' in self.config:
            for group in self.config['rule_groups']:
                if group.get('rules'):
                    logger.info("应用规则组: %s", group.get('name', '?'))
                    result = RuleBasedFilter(
                        rules=group['rules'],
                        logic=group.get('logic', 'AND'),
                    ).filter(result)
        return result
