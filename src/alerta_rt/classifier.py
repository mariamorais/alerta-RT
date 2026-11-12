"""Heuristic classifier: is this SAP Note about Brazilian Tax Reform?"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "tax_reform_patterns.yml"


@dataclass
class Classification:
    is_tax_reform: bool
    score: int
    matched: list[str]


@lru_cache(maxsize=1)
def _rules(path: str = str(_DEFAULT_PATH)) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw["_compiled"] = [(re.compile(p, re.IGNORECASE), w) for p, w in raw.get("keywords", [])]
    return raw


def classify(
    title: str,
    long_text: str | None,
    component: str | None,
    category: str | None,
    priority: str | None,
) -> Classification:
    r = _rules()
    text = f"{title}\n{long_text or ''}"
    comp = (component or "").upper()

    component_hit = any(c.upper() in comp for c in r.get("components_br", []))

    score = 0
    matched: list[str] = []
    for rx, weight in r["_compiled"]:
        if rx.search(text):
            score += weight
            matched.append(rx.pattern)

    if category:
        score += int(r.get("categories_boost", {}).get(category, 0))
    if priority:
        score += int(r.get("priorities_boost", {}).get(priority, 0))

    threshold = int(r.get("threshold", 3))
    is_tr = bool(component_hit and score >= threshold)
    return Classification(is_tax_reform=is_tr, score=score, matched=matched)
