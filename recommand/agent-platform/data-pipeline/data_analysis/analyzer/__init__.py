#!/usr/bin/env python3
"""
分析器模块 - 包含所有分析器实现
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

__all__ = ['BaseAnalyzer', 'AnalyzerFactory']

from . import first_vs_subsequent
from . import helpful_vote
from . import length_by_rating
from . import monthly_rating_distribution
from . import null_statistics
from . import popularity_comparison
from . import product_rating_stats
from . import product_review_count
from . import product_review_tail
from . import rating_by_time
from . import rating_distribution
from . import rating_polarization
from . import review_length_stats
from . import title_length_stats
from . import user_rating_trend
# 导入所有分析器以触发注册
from . import user_review_count
from . import verified_purchase
from . import weekday_rating
from .base import BaseAnalyzer
from .factory import AnalyzerFactory
