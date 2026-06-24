#!/usr/bin/env python3
"""
分析器工厂 - 统一管理所有分析器
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Dict, Type, Any

from .base import BaseAnalyzer


class AnalyzerFactory:
    """分析器工厂类"""

    _analyzers: Dict[str, Type[BaseAnalyzer]] = {}

    @classmethod
    def register(cls, name: str, analyzer_class: Type[BaseAnalyzer]) -> None:
        """注册分析器"""
        cls._analyzers[name] = analyzer_class

    @classmethod
    def create(cls, name: str, spark, config: Dict[str, Any], output_dir: str) -> BaseAnalyzer:
        """创建分析器实例"""
        if name not in cls._analyzers:
            raise ValueError(f"Unknown analyzer: {name}")
        return cls._analyzers[name](spark, config, output_dir)

    @classmethod
    def get_available_analyzers(cls) -> list:
        """获取所有可用的分析器"""
        return list(cls._analyzers.keys())

    @classmethod
    def get_all_analyzers(cls):
        """获取所有分析器类"""
        return cls._analyzers
