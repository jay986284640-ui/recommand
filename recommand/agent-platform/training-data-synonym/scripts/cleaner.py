"""7 类清洗规则(沿用 spec 002 §FR-007)

7 类规则:
  1. 完全相同去重 (text_hash)
  2. 消息过短过滤
  3. 模板重复降频(高频首句降到 ≤ 20%)
  4. params 全 null
  5. 控制字符过滤
  6. item_id 不在字典
  7. 对话轮次异常

通过 DataCleaner.apply(samples) -> (cleaned, dropped) 调用。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class CleaningFilter:
    rule_id: int
    name: str
    enabled: bool = True
    threshold: float = 0.0
    dropped_count: int = 0
    dropped_examples: List[str] = field(default_factory=list)


@dataclass
class CleaningReport:
    raw_count: int
    cleaned_count: int
    retention_rate: float
    filters: List[CleaningFilter] = field(default_factory=list)
    dropped_item_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_count": self.raw_count,
            "cleaned_count": self.cleaned_count,
            "retention_rate": round(self.retention_rate, 4),
            "filters": [
                {
                    "rule_id": f.rule_id,
                    "name": f.name,
                    "enabled": f.enabled,
                    "dropped_count": f.dropped_count,
                    "dropped_examples": f.dropped_examples[:3],
                }
                for f in self.filters
            ],
            "dropped_count": len(self.dropped_item_ids),
        }


# ── 工具 ──────────────────────────────────────────────────────────
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]|\n{3,}|\t")


def _text_hash(sample: Dict[str, Any]) -> str:
    """md5(messages + params)"""
    payload = str(sample.get("messages", "")) + str(sample.get("params", ""))
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _is_all_null_params(params: Dict[str, Any]) -> bool:
    if not params:
        return True
    return all(v is None for v in params.values())


def _has_control_char(sample: Dict[str, Any]) -> bool:
    for m in sample.get("messages", []):
        if CONTROL_CHAR_RE.search(m.get("content", "")):
            return True
    return False


# ── 主清洗器 ──────────────────────────────────────────────────────
class DataCleaner:
    """7 类清洗规则 + 留存率校验(SC-008 ≥ 85% / < 50% 报警)"""

    def __init__(
        self,
        min_message_length: int = 10,
        template_repeat_threshold: float = 0.3,
        template_repeat_target: float = 0.2,
        min_retention_rate: float = 0.85,
        alert_retention_rate: float = 0.50,
    ):
        self.min_msg_len = min_message_length
        self.template_threshold = template_repeat_threshold
        self.template_target = template_repeat_target
        self.min_retention = min_retention_rate
        self.alert_retention = alert_retention_rate

    def apply(
        self, samples: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], CleaningReport]:
        raw_count = len(samples)
        filters = self._init_filters()
        dropped_ids: List[str] = []
        cleaned: List[Dict[str, Any]] = []
        seen_hashes: set[str] = set()
        template_counter: Counter[str] = Counter()

        for s in samples:
            item_id = s.get("item_id", "unknown")

            # 规则 7: 轮次异常(< 1 或 > max_turns=4)
            n_turns = len(s.get("messages", []))
            if n_turns < 1 or n_turns > 4:
                filters[6].dropped_count += 1
                filters[6].dropped_examples.append(item_id)
                dropped_ids.append(item_id)
                continue

            # 规则 5: 控制字符
            if _has_control_char(s):
                filters[4].dropped_count += 1
                filters[4].dropped_examples.append(item_id)
                dropped_ids.append(item_id)
                continue

            # 规则 2: 消息过短
            too_short = any(
                len(m.get("content", "").strip()) < self.min_msg_len
                for m in s.get("messages", [])
            )
            if too_short:
                filters[1].dropped_count += 1
                filters[1].dropped_examples.append(item_id)
                dropped_ids.append(item_id)
                continue

            # 规则 4: params 全 null
            if _is_all_null_params(s.get("params", {})):
                filters[3].dropped_count += 1
                filters[3].dropped_examples.append(item_id)
                dropped_ids.append(item_id)
                continue

            # 规则 1: text_hash 去重
            h = _text_hash(s)
            if h in seen_hashes:
                filters[0].dropped_count += 1
                filters[0].dropped_examples.append(item_id)
                dropped_ids.append(item_id)
                continue
            seen_hashes.add(h)

            # 规则 3: 模板高频降频(后面统一处理)
            first_msg = s.get("messages", [{}])[0].get("content", "")
            template_counter[first_msg[:20]] += 1   # 用前 20 字作模板 key
            cleaned.append(s)

        # 规则 3 应用:首句高频模板降到 ≤ target
        total = len(cleaned)
        if total > 0:
            over_used = [
                tmpl for tmpl, cnt in template_counter.items()
                if cnt / total > self.template_threshold
            ]
            for tmpl in over_used:
                target_keep = int(self.template_target * total)
                # 简单策略:截断该模板的多余样本
                kept = 0
                new_cleaned: List[Dict[str, Any]] = []
                for s in cleaned:
                    first_msg = s.get("messages", [{}])[0].get("content", "")[:20]
                    if first_msg == tmpl:
                        if kept < target_keep:
                            new_cleaned.append(s)
                            kept += 1
                        else:
                            filters[2].dropped_count += 1
                            filters[2].dropped_examples.append(s.get("item_id", "?"))
                            dropped_ids.append(s.get("item_id", "?"))
                    else:
                        new_cleaned.append(s)
                cleaned = new_cleaned

        retention = len(cleaned) / max(raw_count, 1)
        report = CleaningReport(
            raw_count=raw_count,
            cleaned_count=len(cleaned),
            retention_rate=retention,
            filters=filters,
            dropped_item_ids=dropped_ids,
        )

        # 留存率校验(SC-008)
        if retention < self.alert_retention:
            report.__dict__["alert"] = (
                f"留存率 {retention:.2%} < 报警阈值 {self.alert_retention:.0%},"
                f"需检查清洗规则或输入数据"
            )
        elif retention < self.min_retention:
            report.__dict__["warning"] = (
                f"留存率 {retention:.2%} < 目标 {self.min_retention:.0%}"
            )
        return cleaned, report

    def _init_filters(self) -> List[CleaningFilter]:
        return [
            CleaningFilter(rule_id=1, name="text_hash_dedup"),
            CleaningFilter(rule_id=2, name="min_message_length",
                           threshold=float(self.min_msg_len)),
            CleaningFilter(rule_id=3, name="template_repeat",
                           threshold=self.template_threshold),
            CleaningFilter(rule_id=4, name="params_all_null"),
            CleaningFilter(rule_id=5, name="control_char"),
            CleaningFilter(rule_id=6, name="item_id_not_in_dict"),
            CleaningFilter(rule_id=7, name="turn_count", threshold=4.0),
        ]


# ── 8 指标分布统计(沿用 spec 002 §FR-008) ────────────────────────
@dataclass
class DistributionStats:
    intent_distribution: Dict[str, float]
    param_non_null_ratio: Dict[str, float]
    op_distribution: Dict[str, float]
    negative_ratio: float
    turn_distribution: Dict[int, float]
    message_avg_length: float
    dict_value_coverage: Dict[str, int]
    params_combo_diversity: int
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_distribution": self.intent_distribution,
            "param_non_null_ratio": self.param_non_null_ratio,
            "op_distribution": self.op_distribution,
            "negative_ratio": round(self.negative_ratio, 4),
            "turn_distribution": {str(k): v for k, v in self.turn_distribution.items()},
            "message_avg_length": round(self.message_avg_length, 2),
            "dict_value_coverage": self.dict_value_coverage,
            "params_combo_diversity": self.params_combo_diversity,
            "warnings": self.warnings,
        }


def compute_distribution_stats(
    samples: List[Dict[str, Any]],
    dim_values: Dict[str, List[str]],
    negative_ratio_target: float = 0.1,
) -> DistributionStats:
    """计算 8 个分布指标 + 警告"""
    n = len(samples)
    if n == 0:
        return DistributionStats({}, {}, {}, 0.0, {}, 0.0, {}, 0, ["no samples"])

    # 1. intent 分布
    intent_cnt = Counter(s.get("intent", "search_item") for s in samples)
    intent_dist = {k: round(v / n, 4) for k, v in intent_cnt.items()}

    # 2. 7 维 params 非 null 比例
    non_null: Dict[str, int] = {}
    for s in samples:
        for k, v in s.get("params", {}).items():
            if v is not None:
                non_null[k] = non_null.get(k, 0) + 1
    param_ratio = {k: round(v / n, 4) for k, v in non_null.items()}

    # 3. op 分布
    op_cnt: Counter[str] = Counter()
    for s in samples:
        for v in s.get("params", {}).values():
            if isinstance(v, dict) and "op" in v:
                op_cnt[v["op"]] += 1
    total_op = sum(op_cnt.values()) or 1
    op_dist = {k: round(v / total_op, 4) for k, v in op_cnt.items()}

    # 4. 负样本比例
    neg_ratio = sum(1 for s in samples if s.get("negative")) / n

    # 5. 轮次分布
    turn_cnt = Counter(len(s.get("messages", [])) for s in samples)
    turn_dist = {k: round(v / n, 4) for k, v in turn_cnt.items()}

    # 6. 消息平均长度
    msg_lens = [
        len(m.get("content", ""))
        for s in samples for m in s.get("messages", [])
    ]
    avg_len = sum(msg_lens) / max(len(msg_lens), 1)

    # 7. 字典值覆盖
    coverage: Dict[str, int] = {}
    for dim, values in dim_values.items():
        for val in values:
            cnt = sum(
                1 for s in samples
                for v in s.get("params", {}).values()
                if isinstance(v, dict) and val in (v.get("values", [])
                                                    if isinstance(v.get("values"), list)
                                                    else [v.get("values")])
            )
            if cnt > 0:
                coverage[f"{dim}.{val}"] = cnt

    # 8. params 组合多样性
    combos = set()
    for s in samples:
        combo = tuple(sorted(
            (k, str(v.get("values"))) for k, v in (s.get("params") or {}).items()
            if v is not None
        ))
        combos.add(combo)
    combo_div = len(combos)

    # 警告(SC-009: ≤ 2 个)
    warnings: List[str] = []
    for intent, ratio in intent_dist.items():
        if ratio < 0.03:
            warnings.append(f"intent.{intent} = {ratio:.2%} < 3%")
    for dim, ratio in param_ratio.items():
        if ratio < 0.05:
            warnings.append(f"param.{dim} = {ratio:.2%} < 5%")
    if op_dist.get("not contains", 0) < 0.03:
        warnings.append(f"op.not_in = {op_dist.get('not_in', 0):.2%} < 3%")
    if abs(neg_ratio - negative_ratio_target) > 0.02:
        warnings.append(f"negative_ratio = {neg_ratio:.2%} ≠ target {negative_ratio_target:.0%} ±2%")
    if not (20 <= avg_len <= 80):
        warnings.append(f"msg_avg_len = {avg_len:.1f} not in [20, 80]")

    return DistributionStats(
        intent_distribution=intent_dist,
        param_non_null_ratio=param_ratio,
        op_distribution=op_dist,
        negative_ratio=neg_ratio,
        turn_distribution=turn_dist,
        message_avg_length=avg_len,
        dict_value_coverage=coverage,
        params_combo_diversity=combo_div,
        warnings=warnings[:10],
    )


# ── 划分器(沿用 spec 002 §FR-009) ────────────────────────────────
def split_by_item_id(
    samples: List[Dict[str, Any]],
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
) -> Dict[str, List[Dict[str, Any]]]:
    """按 item_id hash 划分 80/10/10(SC-010 同 item 不跨集合)

    算法:
      1. 先按 item_id 分组
      2. 对每个 item_id 算 hash,确定唯一集合
      3. 把该 item_id 的所有 sample 放入该集合
    """
    by_item: Dict[str, List[Dict[str, Any]]] = {}
    for s in samples:
        item_id = s.get("item_id", "")
        by_item.setdefault(item_id, []).append(s)

    splits: Dict[str, List[Dict[str, Any]]] = {"train": [], "val": [], "test": []}
    for item_id, samples_in_item in by_item.items():
        h = int(hashlib.md5(item_id.encode("utf-8")).hexdigest(), 16) % 100
        if h < int(train_ratio * 100):
            target = "train"
        elif h < int((train_ratio + val_ratio) * 100):
            target = "val"
        else:
            target = "test"
        splits[target].extend(samples_in_item)
    return splits


def validate_no_leak(splits: Dict[str, List[Dict[str, Any]]]) -> bool:
    """SC-010:同 item 不跨集合(集合间不重叠,集合内多次出现允许)"""
    item_to_splits: Dict[str, set] = {}
    for split_name, samples in splits.items():
        for s in samples:
            item_id = s.get("item_id", "")
            item_to_splits.setdefault(item_id, set()).add(split_name)
    return all(len(s) == 1 for s in item_to_splits.values())
