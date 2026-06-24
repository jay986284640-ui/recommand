"""特征提取(步骤 4)

5 类产出:
- item_features: 商品特征(画像 + 热度 + 评分分布)
- user_features: 用户特征(画像 + 活跃度 + 偏好品类)
- user_interaction_history: 用户行为序列(按时间排序)
- co_purchase: 共购信息(同用户同时段共购的 item 对)
- impression_log: 曝光日志(stub,待 LP 主流程回流曝光数据)
"""

from .pipeline import FeatureExtractionPipeline
from .item_features import extract_item_features
from .user_features import extract_user_features
from .user_interaction_history import build_user_interaction_history
from .co_purchase import build_co_purchase
from .impression_log import build_impression_log_stub

__all__ = [
    "FeatureExtractionPipeline",
    "extract_item_features",
    "extract_user_features",
    "build_user_interaction_history",
    "build_co_purchase",
    "build_impression_log_stub",
]
