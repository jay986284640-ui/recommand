"""
Load fixture JSONL → Hive tables via PySpark.
Handles column count mismatch: reads table schema, pads missing cols with NULL.

Usage: python scripts/spark_load_fixtures.py
"""
from pathlib import Path
from pyspark.sql import SparkSession, functions as F

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "hive"
METASTORE_URI = "thrift://localhost:9083"
WAREHOUSE = "/opt/bigdata/hive/warehouse"

TABLES = [
    ("recommand_workspace.o2o_new_gut_shop_base_third",
     FIXTURE_DIR / "o2o_new_gut_shop_base_third.jsonl"),
    ("recommand_workspace.o2o_new_gut_shop_base",
     FIXTURE_DIR / "o2o_new_gut_shop_base.jsonl"),
    ("recommand_workspace.o2o_new_gut_coupon_template",
     FIXTURE_DIR / "o2o_new_gut_coupon_template.jsonl"),
]

spark = (
    SparkSession.builder
    .appName("load-fixtures")
    .config("hive.metastore.uris", METASTORE_URI)
    .config("spark.sql.warehouse.dir", WAREHOUSE)
    .enableHiveSupport()
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")
spark.sql("SET hive.exec.dynamic.partition.mode=nonstrict")

for full_name, path in TABLES:
    if not path.exists():
        print(f"SKIP {path.name}: not found")
        continue
    print(f"Loading {path.name} → {full_name}")

    df_src = spark.read.json(str(path), multiLine=False)

    # Read table schema from Hive
    table_schema = spark.table(full_name).schema
    table_cols = [f.name for f in table_schema.fields]
    col_type = {f.name.lower(): f.dataType for f in table_schema.fields}

    # Build SELECT list: if src has the column (by lower-case match), cast to target type; else NULL
    selects = []
    for tc in table_cols:
        tc_lower = tc.lower()
        match = None
        for sc in df_src.columns:
            if sc.lower() == tc_lower:
                match = sc
                break
        if match:
            selects.append(F.col(match).cast(col_type[tc_lower]).alias(tc))
        else:
            selects.append(F.lit(None).cast(col_type[tc_lower]).alias(tc))

    df_aligned = df_src.select(selects)

    # Write — match by position now that column count & order are identical
    df_aligned.write.mode("overwrite").insertInto(full_name, overwrite=True)

    cnt = spark.table(full_name).count()
    print(f"  OK: {cnt} rows")

spark.stop()
print("Done")