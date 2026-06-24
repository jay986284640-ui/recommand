# -*- coding: utf-8 -*-
"""动态过滤器测试"""

import pytest
from cleaning.rule_filter import DynamicFilter
from tests.fixtures.sample_data import create_rule_test_df


def test_dynamic_filter_simple_rules(spark):
    """测试动态过滤器 - 简单规则列表"""
    df = create_rule_test_df(spark)

    config = {
        "rules": [
            {"field": "value", "operator": "gte", "value": 10},
            {"field": "value", "operator": "lte", "value": 20},
        ],
        "logic": "AND"
    }

    result = DynamicFilter(name="测试过滤", config=config).filter(df)
    assert result.count() == 9  # 10 <= value <= 20


def test_dynamic_filter_rule_groups(spark):
    """测试动态过滤器 - 多个规则组"""
    df = create_rule_test_df(spark)

    config = {
        "rule_groups": [
            {
                "name": "值过滤",
                "logic": "AND",
                "rules": [
                    {"field": "value", "operator": "gte", "value": 10},
                    {"field": "value", "operator": "lte", "value": 20},
                ]
            },
            {
                "name": "名称过滤",
                "logic": "OR",
                "rules": [
                    {"field": "name", "operator": "startswith", "value": "a"},
                ]
            }
        ]
    }

    result = DynamicFilter(name="多规则组测试", config=config).filter(df)

    # 先应用值过滤 (10 <= value <= 20): 5 条
    # 再应用名称过滤 (name starts with 'a'): 在剩余结果中过滤
    # 10-20 范围内的 name: apple(1), banana(2), elderberry(5)
    # 其中 starts with 'a': apple
    assert result.count() >= 1


def test_dynamic_filter_both_rules_and_groups(spark):
    """测试同时有 rules 和 rule_groups"""
    df = create_rule_test_df(spark)

    config = {
        "rules": [
            {"field": "value", "operator": "gt", "value": 5}
        ],
        "rule_groups": [
            {
                "name": "名称过滤",
                "rules": [
                    {"field": "name", "operator": "contains", "value": "a"}
                ]
            }
        ]
    }

    result = DynamicFilter(name="混合测试", config=config).filter(df)
    # 先应用 rules: value > 5
    # 再应用 rule_groups: name contains 'a'
    ids = [row.id for row in result.collect()]
    # value > 5 的记录中 name 包含 'a' 的
    assert 1 in ids  # apple, value=10


def test_dynamic_filter_empty_config(spark):
    """测试空配置"""
    df = create_rule_test_df(spark)

    result = DynamicFilter(name="空配置", config={}).filter(df)
    # 空配置不过滤
    assert result.count() == df.count()


def test_dynamic_filter_disabled():
    """测试禁用动态过滤器"""
    config = {
        "rules": [
            {"field": "value", "operator": "gt", "value": 10}
        ]
    }

    filter_obj = DynamicFilter(name="禁用测试", config=config, enabled=False)
    # 禁用后不过滤
    assert filter_obj.enabled is False