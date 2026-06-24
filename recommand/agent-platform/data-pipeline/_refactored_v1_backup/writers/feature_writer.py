"""通用 DataFrame 写出器(支持 parquet / json / csv)"""

import logging
import os
from pyspark.sql import DataFrame


logger = logging.getLogger(__name__)


def write_dataframe(
    df: DataFrame,
    output_dir: str,
    name: str,
    format: str = "parquet",
    mode: str = "overwrite",
) -> str:
    """写出 DataFrame 到 output_dir/name.format"""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{name}.{format}")
    fmt = format.lower()
    if fmt == "parquet":
        df.write.mode(mode).parquet(path)
    elif fmt == "json":
        df.write.mode(mode).json(path)
    elif fmt == "csv":
        df.write.mode(mode).csv(path, header=True)
    else:
        raise ValueError(f"不支持的输出格式: {format}")
    logger.info("已写出: %s", path)
    return path
