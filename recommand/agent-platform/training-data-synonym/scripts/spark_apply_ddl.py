"""Apply tabale_structer.sql DDL to user's docker-compose Hive metastore.

Connects to thrift://localhost:9083 (mapped to hive-metastore container's 9083),
parses tabale_structer.sql statement-by-statement, and runs each via Spark SQL.

Usage (from project root, host):
    python scripts/spark_apply_ddl.py

Assumes:
  - hive-metastore container is running (port 9083 mapped to host)
  - tabale_structer.sql is at /opt/recommand/recommand/tabale_structer.sql
"""
from __future__ import annotations

import re
from pathlib import Path

from pyspark.sql import SparkSession

SQL_PATH = Path("/opt/recommand/recommand/tabale_structer.sql")
METASTORE_URI = "thrift://localhost:9083"
WAREHOUSE_DIR = "/warehouse"  # mounted in spark container; write tables here


def split_statements(sql_text: str) -> list[str]:
    """Split SQL text into individual statements on semicolons (Hive DDL
    doesn't use semicolons inside strings, so a naive split works)."""
    # Strip line comments
    sql_text = re.sub(r"--[^\n]*", "", sql_text)
    statements = []
    current: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.rstrip()
        if stripped.endswith(";"):
            current.append(stripped[:-1])
            stmt = "\n".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(stripped)
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def main() -> None:
    spark = (
        SparkSession.builder
        .appName("training-data-ddl")
        .config("hive.metastore.uris", METASTORE_URI)
        .config("spark.sql.warehouse.dir", "/opt/bigdata/hive/warehouse")
        .config("spark.hadoop.javax.jdo.option.ConnectionURL",
                "jdbc:postgresql://hive-postgres:5432/metastore")
        .enableHiveSupport()
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    sql = SQL_PATH.read_text(encoding="utf-8")
    stmts = split_statements(sql)
    print(f"=== Applying {len(stmts)} DDL statements from {SQL_PATH} ===")

    for i, stmt in enumerate(stmts, 1):
        # First line preview
        first = stmt.splitlines()[0][:80] if stmt else "(empty)"
        try:
            spark.sql(stmt)
            print(f"  [{i:>3}/{len(stmts)}] OK    {first}")
        except Exception as e:  # noqa: BLE001
            print(f"  [{i:>3}/{len(stmts)}] FAIL  {first}\n      {e}")

    print("\n=== Databases ===")
    spark.sql("SHOW DATABASES").show(truncate=False)
    print("=== Tables in recommand_workspace ===")
    spark.sql("USE recommand_workspace")
    spark.sql("SHOW TABLES").show(truncate=False)
    spark.stop()


if __name__ == "__main__":
    main()