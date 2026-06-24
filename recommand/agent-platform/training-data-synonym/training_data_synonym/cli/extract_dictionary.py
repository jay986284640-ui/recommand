"""extract_dictionary — Stage 0 dictionary candidate extraction from Hive.

Independent CLI; not part of the main pipeline. Produces candidate files
under <output-dir>/ that a human reviews before promoting into the
authoritative configs/{dim_dictionary,brand_dictionary}.yaml.

Outputs:
  brands_raw.csv           raw Brnd_Nm + frequency + sources (raw aggregation)
  brands_normalized.csv    clustered by Levenshtein distance + frequency filter
  brands_diff.yaml         vs current brand_dictionary.yaml (added/existing/removed)
  categories_raw.csv       raw Cat_Nm + frequency + sources
  categories_normalized.csv
  categories_diff.yaml     vs current dim_dictionary.category

Per the dictionary governance workflow (see /speckit-clarify session 2026-06-23).
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import click
import yaml

from ..common.logging import configure_logging, get_logger
from ..data_model import HiveReadSpec, Role, TableMeta
from ..hive_reader.base import HiveReader
from ..sql_parser.parser import parse_sql

logger = get_logger(__name__)


# --- Brand / category text normalization --------------------------------


_PAREN_RE = re.compile(r"\([^)]*\)")
_CPAREN_RE = re.compile(r"[（].*?[）]")
_SUFFIX_RE = re.compile(r"(有限公司|集团|股份|Co\.?|Ltd\.?|Inc\.?|LLC|GmbH)$", re.IGNORECASE)


def clean_brand(s: str) -> str:
    """Strip branch markers, legal suffixes, and parens.

    Examples:
      "星巴克(上海)"  -> "星巴克"
      "STARBUCKS RESERVE" -> "STARBUCKS RESERVE" (unchanged — meaningful)
      "星巴克咖啡有限公司" -> "星巴克咖啡"
    """
    if not s:
        return ""
    s = s.strip()
    s = _PAREN_RE.sub("", s)
    s = _CPAREN_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    return s.strip()


def clean_category(s: str) -> str:
    """Light cleanup for category names (preserve Chinese semantics)."""
    if not s:
        return ""
    s = s.strip()
    s = _PAREN_RE.sub("", s)
    s = _CPAREN_RE.sub("", s)
    return s.strip()


def levenshtein(a: str, b: str, max_dist: int | None = None) -> int:
    """Standard DP edit distance with optional early-exit cap."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Ensure a is shorter to keep prev row cheap
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
            if cur[-1] < row_min:
                row_min = cur[-1]
        if max_dist is not None and row_min > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


def jaccard_chars(a: str, b: str, n: int = 2) -> float:
    """Character n-gram Jaccard similarity (better for Chinese than Levenshtein)."""
    if not a or not b:
        return 0.0
    a_grams = {a[i:i + n] for i in range(len(a) - n + 1)}
    b_grams = {b[i:i + n] for i in range(len(b) - n + 1)}
    if not a_grams or not b_grams:
        return 0.0
    inter = len(a_grams & b_grams)
    union = len(a_grams | b_grams)
    return inter / union if union else 0.0


# --- Raw frequency aggregation ------------------------------------------


@dataclass
class RawRow:
    name: str
    frequency: int = 0
    sources: set[str] = field(default_factory=set)


def aggregate_raw(rows: Iterable[tuple[str, str]]) -> dict[str, RawRow]:
    """Aggregate (name, source) tuples into a name -> RawRow map."""
    agg: dict[str, RawRow] = defaultdict(lambda: RawRow(name=""))
    for name, source in rows:
        if not name:
            continue
        if name in agg:
            agg[name].frequency += 1
            agg[name].sources.add(source)
        else:
            agg[name] = RawRow(name=name, frequency=1, sources={source})
    return dict(agg)


def query_brands_from_hive(
    reader: HiveReader, sql_tables: list[TableMeta], spec: HiveReadSpec
) -> list[tuple[str, str]]:
    """Yield (raw_brand_name, item_type_str) tuples from core 3 tables."""
    out: list[tuple[str, str]] = []
    for tm in sql_tables:
        if tm.table_name not in {
            "o2o_new_gut_shop_base_third",
            "o2o_new_gut_shop_base",
            "o2o_new_gut_coupon_template",
        }:
            continue
        for rec in reader.read(tm, spec):
            # Pull brand from various possible columns
            raw_brand = (
                rec.raw.get("Brnd_Nm")
                or rec.raw.get("Str_Nm")
                or rec.raw.get("shopName")
                or rec.raw.get("couponName")
            )
            if raw_brand:
                out.append((raw_brand, rec.item_type.value))
    return out


def query_categories_from_hive(
    reader: HiveReader, sql_tables: list[TableMeta], spec: HiveReadSpec
) -> list[tuple[str, str]]:
    """Yield (raw_category_name, source_str) from category tables."""
    out: list[tuple[str, str]] = []
    for tm in sql_tables:
        if tm.table_name not in {
            "o2o_new_gut_shop_category",
            "o2o_new_gut_shop_category_meituan",
            "o2o_new_gut_shop_category_mapping",
        }:
            continue
        for rec in reader.read(tm, spec):
            cat = rec.raw.get("Cat_Nm")
            if cat:
                out.append((cat, rec.item_type.value or tm.table_name))
    return out


# --- Normalization (clustering) -----------------------------------------


def _select_canonical(candidates: list[str], by_frequency: dict[str, int]) -> str:
    """Pick the canonical name from a cluster: prefer the most frequent raw."""
    return max(candidates, key=lambda n: (by_frequency.get(n, 0), -len(n)))


def normalize_brands(
    raw_rows: list[RawRow],
    *,
    levenshtein_threshold: int = 3,
    jaccard_threshold: float = 0.6,
    jaccard_ngram: int = 2,
) -> dict[str, dict]:
    """Cluster raw brand names into canonical entries.

    Two-row merge rule (greedy, by descending frequency):
      merge iff levenshtein(a, b) ≤ threshold AND jaccard(a, b) ≥ jaccard_threshold

    Returns:
      {canonical_name: {"aliases": [...], "frequency": int, "n_variants": int,
                         "sample_aliases": [str]}}
    """
    # Sort by frequency descending so high-frequency forms become canonical
    sorted_rows = sorted(raw_rows, key=lambda r: -r.frequency)
    by_freq = {r.name: r.frequency for r in raw_rows}

    # clusters: list[set[str]] of merged names; parallel canonical name
    clusters: list[set[str]] = []
    canonicals: list[str] = []

    for row in sorted_rows:
        cleaned = clean_brand(row.name)
        if not cleaned:
            continue
        placed = False
        for i, cluster in enumerate(clusters):
            canon = canonicals[i]
            if levenshtein(cleaned.lower(), canon.lower(), max_dist=levenshtein_threshold) <= levenshtein_threshold:
                # also require character n-gram similarity to avoid false positives
                if jaccard_chars(cleaned, canon, n=jaccard_ngram) >= jaccard_threshold:
                    cluster.add(cleaned)
                    placed = True
                    break
        if not placed:
            clusters.append({cleaned})
            canonicals.append(_select_canonical([cleaned], by_freq))

    out: dict[str, dict] = {}
    for canon, cluster in zip(canonicals, clusters):
        total_freq = sum(by_freq.get(n, 0) for n in cluster)
        out[canon] = {
            "aliases": sorted(cluster),
            "frequency": total_freq,
            "n_variants": len(cluster),
            "sample_aliases": sorted(cluster)[:5],
        }
    # Sort by frequency desc
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["frequency"]))


def normalize_categories(
    raw_rows: list[RawRow],
    *,
    jaccard_threshold: float = 0.6,
) -> dict[str, dict]:
    """Cluster category names (no Levenshtein — categories are short).

    Uses only character n-gram Jaccard for clustering.
    """
    sorted_rows = sorted(raw_rows, key=lambda r: -r.frequency)
    by_freq = {r.name: r.frequency for r in raw_rows}

    clusters: list[set[str]] = []
    canonicals: list[str] = []

    for row in sorted_rows:
        cleaned = clean_category(row.name)
        if not cleaned:
            continue
        placed = False
        for i, canon in enumerate(canonicals):
            if jaccard_chars(cleaned, canon, n=2) >= jaccard_threshold:
                clusters[i].add(cleaned)
                placed = True
                break
        if not placed:
            clusters.append({cleaned})
            canonicals.append(_select_canonical([cleaned], by_freq))

    out: dict[str, dict] = {}
    for canon, cluster in zip(canonicals, clusters):
        total_freq = sum(by_freq.get(n, 0) for n in cluster)
        out[canon] = {
            "aliases": sorted(cluster),
            "frequency": total_freq,
            "n_variants": len(cluster),
        }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["frequency"]))


# --- Diff vs authoritative yaml ----------------------------------------


def diff_brands(current_yaml: dict, normalized: dict[str, dict]) -> dict:
    """Compute added / existing / removed against current brand_dictionary.yaml.

    `normalized` keys are candidate canonical names.
    `current_yaml` is the loaded YAML; uses `values:` as the brand list.
    """
    existing_set = set(current_yaml.get("values", []) or [])
    candidate_set = set(normalized.keys())

    added_sorted = sorted(candidate_set - existing_set, key=lambda n: -normalized[n]["frequency"])
    existing_sorted = sorted(candidate_set & existing_set, key=lambda n: -normalized[n]["frequency"])
    removed_sorted = sorted(existing_set - candidate_set)

    return {
        "_meta": {
            "candidate_count": len(candidate_set),
            "existing_count": len(existing_set),
            "added_count": len(added_sorted),
            "removed_count": len(removed_sorted),
        },
        "added": [
            {
                "name": n,
                "frequency": normalized[n]["frequency"],
                "n_variants": normalized[n]["n_variants"],
                "sample_aliases": normalized[n]["sample_aliases"],
            }
            for n in added_sorted
        ],
        "existing": [
            {"name": n, "frequency": normalized[n]["frequency"]}
            for n in existing_sorted
        ],
        "removed": [{"name": n} for n in removed_sorted],
    }


def diff_categories(current_yaml: dict, normalized: dict[str, dict]) -> dict:
    """Same shape as diff_brands but for dim_dictionary.category.values."""
    existing_set = set((current_yaml.get("category") or {}).get("values", []) or [])
    candidate_set = set(normalized.keys())

    added_sorted = sorted(candidate_set - existing_set, key=lambda n: -normalized[n]["frequency"])
    existing_sorted = sorted(candidate_set & existing_set, key=lambda n: -normalized[n]["frequency"])
    removed_sorted = sorted(existing_set - candidate_set)

    return {
        "_meta": {
            "candidate_count": len(candidate_set),
            "existing_count": len(existing_set),
            "added_count": len(added_sorted),
            "removed_count": len(removed_sorted),
        },
        "added": [
            {
                "name": n,
                "frequency": normalized[n]["frequency"],
                "n_variants": normalized[n]["n_variants"],
            }
            for n in added_sorted
        ],
        "existing": [{"name": n, "frequency": normalized[n]["frequency"]} for n in existing_sorted],
        "removed": [{"name": n} for n in removed_sorted],
    }


# --- File writers ------------------------------------------------------


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# --- Main pipeline -----------------------------------------------------


def extract(
    *,
    source: str = "mock",
    fixture_dir: str = "tests/fixtures/hive",
    sql_path: str = "/opt/recommand/recommand/tabale_structer.sql",
    output_dir: str = "dict_candidates",
    configs_dir: str = "configs",
    frequency_min: int = 10,
    levenshtein_threshold: int = 3,
    jaccard_threshold: float = 0.6,
    sample_n_per_type: int | None = None,
) -> dict:
    """Run Stage 0 → 3 and write candidate files under output_dir.

    Returns a stats dict for the CLI to print.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    configs = Path(configs_dir)

    # Stage 0: SQL 抽取
    if source == "mock":
        from ..hive_reader.mock_reader import MockHiveReader
        reader: HiveReader = MockHiveReader(fixture_dir=fixture_dir)
    elif source == "hive":
        from ..hive_reader.spark_reader import SparkHiveReader
        reader = SparkHiveReader()  # env-wired in production
    else:
        raise ValueError(f"unknown source: {source}")

    sql_tables = parse_sql(sql_path)
    spec = HiveReadSpec(source=source, sample_n_per_type=sample_n_per_type)

    # Brands
    brand_tuples = query_brands_from_hive(reader, sql_tables, spec)
    brand_raw = aggregate_raw(brand_tuples)
    _write_csv(
        out / "brands_raw.csv",
        rows=[
            {
                "name": r.name,
                "frequency": r.frequency,
                "sources": "|".join(sorted(r.sources)),
            }
            for r in sorted(brand_raw.values(), key=lambda x: -x.frequency)
        ],
        fieldnames=["name", "frequency", "sources"],
    )

    brand_norm = normalize_brands(
        list(brand_raw.values()),
        levenshtein_threshold=levenshtein_threshold,
        jaccard_threshold=jaccard_threshold,
    )
    brand_norm_filtered = {k: v for k, v in brand_norm.items() if v["frequency"] >= frequency_min}
    _write_csv(
        out / "brands_normalized.csv",
        rows=[
            {
                "canonical": k,
                "frequency": v["frequency"],
                "n_variants": v["n_variants"],
                "aliases": "|".join(v["aliases"]),
            }
            for k, v in brand_norm_filtered.items()
        ],
        fieldnames=["canonical", "frequency", "n_variants", "aliases"],
    )

    # Diff vs current brand_dictionary.yaml
    current_brand = yaml.safe_load((configs / "brand_dictionary.yaml").read_text()) if (configs / "brand_dictionary.yaml").exists() else {"values": []}
    brand_diff = diff_brands(current_brand, brand_norm_filtered)
    brand_diff["_meta"]["frequency_min"] = frequency_min
    brand_diff["_meta"]["levenshtein_threshold"] = levenshtein_threshold
    brand_diff["_meta"]["jaccard_threshold"] = jaccard_threshold
    brand_diff["_meta"]["raw_count"] = len(brand_raw)
    brand_diff["_meta"]["normalized_count"] = len(brand_norm)
    brand_diff["_meta"]["filtered_count"] = len(brand_norm_filtered)
    _write_yaml(out / "brands_diff.yaml", brand_diff)

    # Categories
    cat_tuples = query_categories_from_hive(reader, sql_tables, spec)
    cat_raw = aggregate_raw(cat_tuples)
    _write_csv(
        out / "categories_raw.csv",
        rows=[
            {"name": r.name, "frequency": r.frequency, "sources": "|".join(sorted(r.sources))}
            for r in sorted(cat_raw.values(), key=lambda x: -x.frequency)
        ],
        fieldnames=["name", "frequency", "sources"],
    )

    cat_norm = normalize_categories(list(cat_raw.values()), jaccard_threshold=jaccard_threshold)
    cat_norm_filtered = {k: v for k, v in cat_norm.items() if v["frequency"] >= frequency_min}
    _write_csv(
        out / "categories_normalized.csv",
        rows=[
            {
                "canonical": k,
                "frequency": v["frequency"],
                "n_variants": v["n_variants"],
                "aliases": "|".join(v["aliases"]),
            }
            for k, v in cat_norm_filtered.items()
        ],
        fieldnames=["canonical", "frequency", "n_variants", "aliases"],
    )

    current_dim = yaml.safe_load((configs / "dim_dictionary.yaml").read_text()) if (configs / "dim_dictionary.yaml").exists() else {}
    cat_diff = diff_categories(current_dim, cat_norm_filtered)
    cat_diff["_meta"]["frequency_min"] = frequency_min
    cat_diff["_meta"]["raw_count"] = len(cat_raw)
    cat_diff["_meta"]["normalized_count"] = len(cat_norm)
    cat_diff["_meta"]["filtered_count"] = len(cat_norm_filtered)
    _write_yaml(out / "categories_diff.yaml", cat_diff)

    return {
        "raw_brands": len(brand_raw),
        "normalized_brands": len(brand_norm),
        "filtered_brands": len(brand_norm_filtered),
        "added_brands": brand_diff["_meta"]["added_count"],
        "removed_brands": brand_diff["_meta"]["removed_count"],
        "raw_categories": len(cat_raw),
        "normalized_categories": len(cat_norm),
        "filtered_categories": len(cat_norm_filtered),
        "added_categories": cat_diff["_meta"]["added_count"],
        "output_dir": str(out),
    }


# --- Click CLI ---------------------------------------------------------


@click.command()
@click.option("--source", default="mock", help="hive | mock")
@click.option("--fixture-dir", default="tests/fixtures/hive", help="mock fixture dir")
@click.option("--sql", default="/opt/recommand/recommand/tabale_structer.sql")
@click.option("--output-dir", default="dict_candidates")
@click.option("--configs-dir", default="configs")
@click.option("--frequency-min", default=10, type=int, help="min occurrences to include")
@click.option("--levenshtein-threshold", default=3, type=int)
@click.option("--jaccard-threshold", default=0.6, type=float)
@click.option("--n-items-per-type", type=int, default=None)
@click.option("--log-level", default="INFO")
def main(
    source, fixture_dir, sql, output_dir, configs_dir,
    frequency_min, levenshtein_threshold, jaccard_threshold,
    n_items_per_type, log_level,
):
    """Stage 0 dictionary candidate extraction (offline CLI)."""
    configure_logging(log_level)
    stats = extract(
        source=source,
        fixture_dir=fixture_dir,
        sql_path=sql,
        output_dir=output_dir,
        configs_dir=configs_dir,
        frequency_min=frequency_min,
        levenshtein_threshold=levenshtein_threshold,
        jaccard_threshold=jaccard_threshold,
        sample_n_per_type=n_items_per_type,
    )
    click.echo("Stage 0 extract-dictionary complete:")
    for k, v in stats.items():
        click.echo(f"  {k}: {v}")
    click.echo(f"\nReview {output_dir}/brands_diff.yaml for candidates to promote.")


if __name__ == "__main__":
    main()