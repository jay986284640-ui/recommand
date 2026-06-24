"""LLM client abstraction + Mock implementation.

Per research.md D-012 — retry 2x with exponential backoff; fail → record
failure, continue main flow.
"""

from __future__ import annotations

import json
import random
from abc import ABC, abstractmethod
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import ValidationError
from .logging import get_logger

logger = get_logger(__name__)


class LLMTimeoutError(Exception):
    """LLM call exceeded timeout."""


class LLMClient(ABC):
    """Abstract LLM client. All subclasses MUST implement `complete(prompt)`."""

    @abstractmethod
    def complete(self, prompt: str, *, temperature: float = 0.7) -> dict[str, Any]:
        """Return parsed JSON dict. Raise LLMTimeoutError on timeout.

        Implementations should retry transient failures per research.md D-012.
        """
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Deterministic mock for CI / dev. Returns heuristic JSON from prompt.

    Behavior:
      - If prompt contains {"intent": "..."} (Stage 2 ground-truth injection),
        echo a structured 1-3 turn dialogue back with that intent and
        a {param} -> natural language paraphrase using dictionary values.
      - If prompt contains `原始信息:` (Stage 1), echo back 6 dims based on
        the raw record's category / merchant fields if present, else nulls.
      - Always returns valid JSON; never times out.
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        # 1 in 50 chance to inject a JSON-decode failure to exercise retries.
        self._inject_failure_every = 50
        self._call_count = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=0.1, max=1.0),
        retry=retry_if_exception_type((LLMTimeoutError, json.JSONDecodeError)),
        reraise=True,
    )
    def complete(self, prompt: str, *, temperature: float = 0.7) -> dict[str, Any]:
        self._call_count += 1
        if self._call_count % self._inject_failure_every == 0:
            # Inject transient failure once every N calls.
            raise LLMTimeoutError(f"injected failure at call #{self._call_count}")

        if "目标:" in prompt or "intent:" in prompt:
            return self._mock_sft_dialogue(prompt)
        if "原始信息:" in prompt or "你是一个 O2O 推荐系统的标签补全助手" in prompt:
            return self._mock_enrichment(prompt)
        # Fallback for tests: still produce a structured dialogue so
        # downstream validation does not crash.
        return self._mock_sft_dialogue(prompt)

    # ---- heuristics -----------------------------------------------------

    def _mock_enrichment(self, prompt: str) -> dict[str, Any]:
        """Echo 6-dim JSON from raw record snippet."""
        raw = {}
        # crude extraction of "raw_record" or "原始信息:" block
        try:
            if "原始信息:" in prompt:
                block = prompt.split("原始信息:")[1].strip()
                if block.startswith("{"):
                    raw = json.loads(block)
            elif "raw_record" in prompt:
                block = prompt[prompt.index("raw_record"):]
                # find first {...}
                start = block.index("{")
                end = block.index("}", start) + 1
                raw = json.loads(block[start:end])
        except (json.JSONDecodeError, ValueError):
            raw = {}

        cat = raw.get("Cat_Nm") or raw.get("couponName")
        merch = raw.get("Brnd_Nm") or raw.get("Str_Nm")
        avg = raw.get("Avg_Prc")

        return {
            "category": cat if cat else "咖啡",
            "merchant": merch if merch else None,
            "avg_prc": self._bucket_price(avg) if avg else None,
            "age": "25-35" if self._rng.random() > 0.5 else None,
            "occasion": self._rng.choice(["下午茶", "午餐", None]),
            "taste": self._rng.choice([["甜"], ["咸"], None]),
        }

    def _mock_sft_dialogue(self, prompt: str) -> dict[str, Any]:
        """Echo 1-3 turn dialogue + covered_dims."""
        # crude ground-truth parse
        intent_match = "search_item"
        order_by = None
        covered: list[str] = []

        if "intent: search_item" in prompt:
            intent_match = "search_item"
        elif "intent: use_coupon" in prompt:
            intent_match = "use_coupon"
        elif "intent: pay" in prompt:
            intent_match = "pay"

        if "order_by: distance" in prompt:
            order_by = "distance"
            covered.append("distance")
        if "category" in prompt:
            covered.append("category")
        if "consumable_type" in prompt:
            covered.append("consumable_type")

        n_turns = self._rng.choice([2, 3, 3, 3, 4])
        messages = [
            {"role": "user", "content": f"想看附近有什么推荐({intent_match})"},
            {"role": "assistant", "content": "可以告诉我具体想喝 / 想吃 / 价位吗?"},
        ]
        if n_turns >= 3:
            messages.append(
                {"role": "user", "content": f"{order_by or '随便'},想喝点东西"}
            )
            covered.append("consumable_type")
        if n_turns >= 4:
            messages.append(
                {"role": "assistant", "content": "好的,为您筛选以下门店..."}
            )

        return {"messages": messages, "covered_dims": covered}

    @staticmethod
    def _bucket_price(avg_unc: Any) -> str | None:
        try:
            avg = float(avg_unc)
        except (TypeError, ValueError):
            return None
        if avg <= 30:
            return "0-30"
        if avg <= 50:
            return "30-50"
        if avg <= 100:
            return "50-100"
        if avg <= 200:
            return "100-200"
        return "200+"


# --- thin helpers ---------------------------------------------------------


def validate_complete_response(payload: Any) -> dict[str, Any]:
    """Ensure payload is a dict (catches LLM returning a list / scalar)."""
    if not isinstance(payload, dict):
        raise ValidationError(f"LLM response is not a dict: {type(payload).__name__}")
    return payload