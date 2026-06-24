"""标准化步骤 Pipeline

按配置分别为 users / items / interactions 三个 DataFrame 应用 normalizer。
"""

import logging
from typing import Dict, Any
from pyspark.sql import DataFrame

from .base_normalizer import BaseTextNormalizer
from .html_normalizer import HtmlNormalizer
from .lowercase_normalizer import LowercaseNormalizer
from .special_char_normalizer import SpecialCharNormalizer
from .unicode_normalizer import UnicodeNormalizer
from .whitespace_normalizer import WhitespaceNormalizer
from .regex_replace_normalizer import RegexReplaceNormalizer
from .regex_extract_normalizer import RegexExtractNormalizer


logger = logging.getLogger(__name__)


SIMPLE_NORMALIZERS = {
    'html_normalizer': HtmlNormalizer,
    'unicode_normalizer': UnicodeNormalizer,
    'special_char_normalizer': SpecialCharNormalizer,
    'lowercase': LowercaseNormalizer,
    'whitespace_normalizer': WhitespaceNormalizer,
}


class NormalizationPipeline:
    """文本标准化 Pipeline"""

    def __init__(self, config):
        self.config = config

    def _build_normalizers(self, df_config: list) -> Dict[str, BaseTextNormalizer]:
        if not self.config.normalization.enabled or not df_config:
            return {}
        normalizers: Dict[str, BaseTextNormalizer] = {}
        for cfg in df_config:
            name = cfg.get('normalizer')
            if not name:
                continue
            if name in SIMPLE_NORMALIZERS:
                if name not in normalizers:
                    normalizers[name] = SIMPLE_NORMALIZERS[name]()
            elif name == 'regex_replace_normalizer':
                if name not in normalizers:
                    normalizers[name] = RegexReplaceNormalizer()
                for col_cfg in cfg.get('columns', []):
                    if isinstance(col_cfg, dict) and 'rules' in col_cfg:
                        for rule in col_cfg['rules']:
                            if 'pattern' in rule and 'replacement' in rule:
                                normalizers[name].add_rule(rule['pattern'], rule['replacement'])
            elif name == 'regex_extract_normalizer':
                if name not in normalizers:
                    normalizers[name] = RegexExtractNormalizer()
                for col_cfg in cfg.get('columns', []):
                    if isinstance(col_cfg, dict) and 'name' in col_cfg:
                        normalizers[name].add_column_rule(
                            col_cfg['name'],
                            col_cfg.get('pattern', ''),
                            col_cfg.get('group', 1),
                            col_cfg.get('remove', ''),
                            col_cfg.get('default', ''),
                        )
        return normalizers

    def _apply(self, df: DataFrame, df_name: str) -> DataFrame:
        df_config = self.config.normalization.df_config.get(df_name, [])
        if not df_config:
            return df
        normalizers = self._build_normalizers(df_config)
        if not normalizers:
            return df
        logger.info("标准化 - %s (应用 %d 个 normalizer)", df_name, len(normalizers))
        result = df
        for cfg in df_config:
            name = cfg.get('normalizer')
            if name not in normalizers:
                continue
            normalizer = normalizers[name]
            for col_cfg in cfg.get('columns', []):
                col_name = col_cfg if isinstance(col_cfg, str) else col_cfg.get('name')
                if not col_name or col_name not in result.columns:
                    continue
                if normalizer.is_column_supported(result, col_name):
                    result = normalizer.process(result, col_name)
                    logger.info("  %s -> %s", normalizer.name, col_name)
        return result

    def run(self, users_df: DataFrame, items_df: DataFrame, interactions_df: DataFrame) -> Dict[str, DataFrame]:
        logger.info("====== 开始标准化步骤 ======")
        return {
            "users": self._apply(users_df, "users"),
            "items": self._apply(items_df, "items"),
            "interactions": self._apply(interactions_df, "interactions"),
        }
