"""CleaningPipeline 端到端测试"""

from pyspark.sql.types import StructType, StructField, StringType, LongType, IntegerType

from common.config_loader import Config
from cleaning import CleaningPipeline


def _build(spark):
    users = spark.createDataFrame(
        [("u1", "Alice"), ("u2", "Bob"), ("u3", "Ghost")],
        "user_id STRING, name STRING",
    )
    items = spark.createDataFrame(
        [("i1", "A"), ("i2", "B"), ("i3", "C")],
        "item_id STRING, title STRING",
    )
    interactions = spark.createDataFrame(
        [
            ("u1", "i1", 1700000000, 5),
            ("u1", "i2", 1700000100, 4),
            ("u2", "i1", 1700000200, 3),
            ("u3", "i3", 1700000300, 2),  # u3 不在 users 里(注意:u3 在 users 里)
            (None, "i1", 1700000400, 1),  # 缺 user_id
        ],
        "user_id STRING, item_id STRING, timestamp LONG, rating INT",
    )
    return users, items, interactions


def test_cleaning_pipeline_cascades(spark):
    users, items, inters = _build(spark)
    config = Config()
    # 关闭重过滤项,只留字段完整性 + product_exists + 级联
    config.cleaning.field_completeness = True
    config.cleaning.product_exists = True
    config.cleaning.time = False
    config.cleaning.deduplicate = False
    config.cleaning.burst_review = False
    config.cleaning.user_item_dedup = False
    config.cleaning.kcore = False
    config.cleaning.outlier = False
    config.cleaning.spam = False
    config.cleaning.text_length = False

    out = CleaningPipeline(config).run(users, items, inters)
    # 字段完整性 + product_exists 后,interactions 应只剩 (u1, i1), (u1, i2), (u2, i1)
    assert out["interactions"].count() == 3
    # u3 仍在 users 中,但如果 i3 不出现在清洗后的 interactions 也会被级联掉
    # 这里 i3 在 interactions 里出现了 1 次(u3, i3),所以 u3 仍保留
    user_ids = {r["user_id"] for r in out["users"].collect()}
    assert user_ids == {"u1", "u2", "u3"}
    item_ids = {r["item_id"] for r in out["items"].collect()}
    assert item_ids == {"i1", "i2", "i3"}
