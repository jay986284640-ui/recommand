"""Mock LLM 客户端(本地启发式,无网络)

训练数据生成 + 同义词抽取 复用,沿用 001 spec 描述的"mock-llm-server"模式,
但本地实现,不依赖外部 HTTP 服务。

实现:
  - 输入: ai_tags (dict) + dialogue_template (str) + negative_type (str|None)
  - 输出: dict,含 messages / intent / params / order_by 4 字段(对齐 spec 002 schema)
  - 失败注入: 默认 5% 概率返回非法 JSON,模拟 LLM 不稳定

特点:
  - 100% 本地,无外部依赖(只用标准库)
  - 可被 002 训练数据生成 / 003 同义词抽取 复用
  - 支持负样本(拒绝/转移/不满足)
  - 支持多轮对话(1~4 轮)
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── 5 类 intent(沿用 spec 002) ──────────────────────────────────
INTENT_TYPES = ["search_item", "use_coupon", "pay", "view_order", "browse"]

# ── 5~8 套首句骨架(沿用 spec 002 §FR-005,均 ≥ 8 字过清洗) ─────────
DIALOGUE_TEMPLATES = [
    "我想{verb}{category}一下",
    "想要{verb}{category},推荐一下",
    "想看看{category}有什么好的",
    "附近有{category}的店吗",
    "想找一家{category}门店",
    "想{verb}{category},有什么好推荐",
    "想试试{category},求推荐",
    "想{category}一下,有什么选择",
]

# ── verb 词表(按 category 适配) ─────────────────────────────────
VERBS_BY_CATEGORY = {
    "咖啡":     ["喝", "来杯", "点一杯", "买", "点"],
    "奶茶":     ["喝", "来杯", "点一杯", "买", "点"],
    "快餐":     ["吃", "来份", "点一份", "买"],
    "烘焙":     ["买", "买点", "来份", "尝尝"],
    "便利店":   ["去", "逛", "买点东西"],
    "中餐":     ["吃", "来份", "点"],
    "西餐":     ["吃", "来份", "点"],
    "日料":     ["吃", "点", "来份"],
    "火锅":     ["吃", "涮"],
    "烧烤":     ["吃", "撸"],
    "甜品":     ["吃", "来份", "尝尝"],
    "水果":     ["买", "来点"],
    "default":  ["来", "点", "买", "吃"],
}

# ── order_by 候选(沿用 spec 002) ────────────────────────────────
ORDER_BYS = ["distance", "price", "rating", "time", None]

# ── 3 类负样本 prompt 指令(沿用 spec 002 §FR-006) ────────────────
NEGATIVE_PROMPTS = {
    "reject":         "用户表达'不要'某条件,如'不要辣的' / '不要太甜的'。",
    "pivot":          "用户转移意图,如'算了不看咖啡了,看奶茶'。",
    "unsatisfiable":  "无门店满足 query,如'附近没这种店'。",
}


@dataclass
class MockLLMConfig:
    failure_rate: float = 0.05       # 5% 失败注入
    max_turns: int = 3               # 默认 3 轮
    turn_distribution: List[float] = field(
        default_factory=lambda: [0.10, 0.30, 0.40, 0.20]   # 1/2/3/4 轮
    )
    template_repeat_threshold: float = 0.3   # 30% 触发降频


class MockLLMClient:
    """本地启发式 mock-llm 客户端"""

    def __init__(self, config: Optional[MockLLMConfig] = None):
        self.config = config or MockLLMConfig()
        self._rng = random.Random()
        self._template_counter: Dict[str, int] = {}  # 高频模板降频

    # ── 公共 API ──────────────────────────────────────────────
    def generate_training_sample(
        self,
        ai_tags: Dict[str, Any],
        dialogue_template: str,
        negative_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成 1 条训练样本(对齐 spec 002 §6.1 训练数据 jsonl schema)

        Args:
            ai_tags:           商品属性(从 o2o 门店表抽)
            dialogue_template: 首句骨架("我想喝咖啡" / "推荐个咖啡" ...)
            negative_type:     None / "reject" / "pivot" / "unsatisfiable"

        Returns:
            {item_id, intent, messages, params, order_by, negative}
        """
        # 1. 失败注入
        if self._rng.random() < self.config.failure_rate:
            # 模拟 JSON 解析失败:返回字符串而非 dict
            return {"_mock_error": "JSONDecodeError: invalid token at line 1"}

        # 2. 决定对话轮次
        n_turns = self._pick_turn_count()

        # 3. 构造 messages
        messages = self._build_messages(
            ai_tags=ai_tags,
            template=dialogue_template,
            n_turns=n_turns,
            negative_type=negative_type,
        )

        # 4. 决定 intent
        intent = self._pick_intent(ai_tags, negative_type)

        # 5. 构造 params(7 维商业属性,op / values 形式)
        params = self._build_params(ai_tags, negative_type)

        # 6. 决定 order_by
        order_by = self._pick_order_by(ai_tags, negative_type)

        return {
            "item_id": ai_tags.get("item_id", "unknown"),
            "intent": intent,
            "messages": messages,
            "params": params,
            "order_by": order_by,
            "negative": negative_type is not None,
        }

    def extract_synonyms(
        self,
        text: str,
        dictionary: Dict[str, List[str]],
    ) -> List[List[str]]:
        """抽取同义词(供 003 用,启发式:从 text 找字典中含的 token,返回同组)

        Returns: [[token1, token2, ...], ...] 每个内层 list 是一组同义词
        """
        result: List[List[str]] = []
        text_lower = text.lower()
        for canonical, variants in dictionary.items():
            group = [canonical]
            for v in variants:
                if v.lower() in text_lower and v != canonical:
                    group.append(v)
            if len(group) >= 2:
                result.append(group)
        return result

    # ── 内部:对话构造 ──────────────────────────────────────────
    def _build_messages(
        self,
        ai_tags: Dict[str, Any],
        template: str,
        n_turns: int,
        negative_type: Optional[str],
    ) -> List[Dict[str, str]]:
        category = ai_tags.get("category", "咖啡")
        merchant = ai_tags.get("merchant")
        avg_prc = ai_tags.get("avg_prc")
        distance = ai_tags.get("distance")
        occasion = ai_tags.get("occasion")
        taste = ai_tags.get("taste")

        verb = self._pick_verb(category)
        first_user = template.format(verb=verb, category=category)

        # 模板高频降频:首句重复 > 30% → 换说法
        if self._is_template_overused(first_user):
            first_user = self._rewrite_first_user(category, merchant)

        messages: List[Dict[str, str]] = [{"role": "user", "content": first_user}]
        if n_turns == 1:
            return messages

        # 第二轮: assistant 推荐
        assistant_msg = self._build_assistant_msg(merchant, avg_prc, category)
        messages.append({"role": "assistant", "content": assistant_msg})
        if n_turns == 2:
            return messages

        # 第三轮: user 追问(条件)
        follow_up = self._build_follow_up(
            distance=distance, occasion=occasion, taste=taste,
            merchant=merchant, negative_type=negative_type,
        )
        messages.append({"role": "user", "content": follow_up})
        if n_turns == 3:
            return messages

        # 第四轮: assistant 二次回复
        second_assistant = self._build_second_assistant(merchant, follow_up, negative_type)
        messages.append({"role": "assistant", "content": second_assistant})
        return messages

    def _build_assistant_msg(
        self, merchant: Optional[str], avg_prc: Optional[str], category: str
    ) -> str:
        if merchant:
            base = f"为您推荐附近的{merchant}门店"
        else:
            base = f"为您推荐附近的{category}门店"
        if avg_prc:
            base += f",人均{avg_prc}元"
        return base + "。"

    def _build_follow_up(
        self,
        distance: Optional[str],
        occasion: Optional[str],
        taste: Optional[List[str]],
        merchant: Optional[str],
        negative_type: Optional[str],
    ) -> str:
        # 负样本特殊处理
        if negative_type == "reject":
            if taste:
                t = taste[0] if isinstance(taste, list) and taste else "辣"
                return f"有没有不要太{t}的,推荐一下其他选项?"
            return "有没有不要辣的,看看别的?"
        if negative_type == "pivot":
            if merchant:
                return f"算了,不看{merchant}了,推荐一家附近的奶茶店吧"
            return "算了不看咖啡了,有奶茶店推荐吗?"
        if negative_type == "unsatisfiable":
            return "附近没这种店,那还有什么别的选择可以看看?"

        # 正样本
        if distance:
            return f"有没有离我近一点的({distance}米内)?"
        if occasion:
            return f"适合{occasion}的有吗,推荐一下"
        return "有没有别的选择,推荐一下看看"

    def _build_second_assistant(
        self, merchant: Optional[str], follow_up: str, negative_type: Optional[str]
    ) -> str:
        if negative_type == "unsatisfiable":
            return "很抱歉,附近暂时没找到,要不要看看其他分类?"
        if negative_type in ("reject", "pivot"):
            return f"好的,为您筛选其他选项。"
        if "近" in follow_up:
            return "已为您筛选附近 1km 内的门店。"
        return "好的,为您展示更多选择。"

    def _rewrite_first_user(self, category: str, merchant: Optional[str]) -> str:
        """首句高频降频:换 1 种说法(保证 ≥ 8 字,过清洗)"""
        rewrites = [
            f"想{category}一下,有推荐的吗",
            f"想看看附近{category}有什么好的",
            f"附近有{category}的店吗,推荐一下",
            f"想试试{category},有什么推荐",
            f"找个{category}门店,推荐一下",
            f"想找一家好的{category}门店",
        ]
        return self._rng.choice(rewrites)

    def _is_template_overused(self, first_user: str) -> bool:
        self._template_counter[first_user] = self._template_counter.get(first_user, 0) + 1
        total = sum(self._template_counter.values())
        ratio = self._template_counter[first_user] / max(total, 1)
        return ratio > self.config.template_repeat_threshold

    # ── 内部:intent / params / order_by ──────────────────────
    def _pick_intent(self, ai_tags: Dict[str, Any], negative_type: Optional[str]) -> str:
        if negative_type:
            return "search_item"   # 负样本统一 search_item
        return self._rng.choices(
            INTENT_TYPES, weights=[0.6, 0.15, 0.10, 0.10, 0.05]
        )[0]

    def _build_params(
        self, ai_tags: Dict[str, Any], negative_type: Optional[str]
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "category":    None,
            "merchant":    None,
            "avg_prc":     None,
            "distance":    None,
            "occasion":    None,
            "taste":       None,
        }
        # 商品侧 4 维 80% 概率填
        for k in ("category", "merchant", "avg_prc", "distance"):
            if ai_tags.get(k) and self._rng.random() < 0.7:
                v = ai_tags[k]
                if k == "taste" and isinstance(v, list):
                    params[k] = {"op": "contains", "values": v}
                elif k in ("category", "merchant", "avg_prc", "distance", "occasion"):
                    params[k] = {"op": "in", "values": v if isinstance(v, list) else [v]}
                else:
                    params[k] = {"op": "in", "values": [v]}

        # 用户侧 3 维 30% 概率填
        for k in ("occasion", "taste"):
            if ai_tags.get(k) and self._rng.random() < 0.3:
                v = ai_tags[k]
                if k == "taste" and isinstance(v, list):
                    params[k] = {"op": "contains", "values": v}
                else:
                    params[k] = {"op": "in", "values": v if isinstance(v, list) else [v]}

        # 负样本特殊处理:rejected 维度反义
        if negative_type == "reject" and ai_tags.get("taste"):
            taste = ai_tags["taste"]
            if isinstance(taste, list) and taste:
                params["taste"] = {"op": "not contains", "values": [taste[0]]}

        return params

    def _pick_order_by(
        self, ai_tags: Dict[str, Any], negative_type: Optional[str]
    ) -> Optional[str]:
        if negative_type:
            return None
        if ai_tags.get("distance"):
            return self._rng.choices(
                ["distance", "price", "rating", "time", None],
                weights=[0.5, 0.2, 0.15, 0.10, 0.05],
            )[0]
        return self._rng.choices(
            ["price", "rating", "time", None],
            weights=[0.3, 0.4, 0.2, 0.1],
        )[0]

    # ── 内部:小工具 ────────────────────────────────────────────
    def _pick_verb(self, category: str) -> str:
        verbs = VERBS_BY_CATEGORY.get(category, VERBS_BY_CATEGORY["default"])
        return self._rng.choice(verbs)

    def _pick_turn_count(self) -> int:
        choices = [1, 2, 3, 4]
        return self._rng.choices(choices, weights=self.config.turn_distribution)[0]


# ── CLI 自测 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    client = MockLLMClient()
    ai_tags = {
        "item_id": "shop-001",
        "category": "咖啡",
        "merchant": "星巴克",
        "avg_prc": "30-50",
        "distance": "500-1000",
        "occasion": "下午茶",
        "taste": ["甜", "冰"],
    }

    print("=== 正样本 ===")
    for i in range(3):
        for tmpl in DIALOGUE_TEMPLATES[:3]:
            s = client.generate_training_sample(ai_tags, tmpl)
            if "_mock_error" in s:
                print(f"  [ERROR injected] {s['_mock_error']}")
            else:
                print(f"  intent={s['intent']}, order_by={s['order_by']}, "
                      f"messages[0]={s['messages'][0]['content']!r}, "
                      f"non_null_params={[k for k,v in s['params'].items() if v]}")

    print("\n=== 负样本(reject) ===")
    s = client.generate_training_sample(ai_tags, DIALOGUE_TEMPLATES[0], "reject")
    print(f"  negative={s['negative']}, params.taste={s['params']['taste']}")

    print("\n=== 同义词抽取 ===")
    dictionary = {
        "星巴克": ["星巴克", "Starbucks", "STARBUCKS"],
        "咖啡":   ["咖啡", "coffee", "Coffee"],
    }
    syns = client.extract_synonyms("推荐星巴克 coffee 门店", dictionary)
    print(f"  抽到 {len(syns)} 组: {syns}")
