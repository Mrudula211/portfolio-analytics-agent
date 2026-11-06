"""Deterministic portfolio-name resolution.

Maps user phrasing ("international equity", "portfolio 7", "balanced fund") to a single
portfolio, or reports ambiguity instead of guessing. Pure Python, fully unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

GENERIC = {"fund", "funds", "portfolio", "portfolios", "index", "the", "a", "an", "of", "for", "in", "my", "our"}
ALIASES = {
    "em": "emerging markets fund",
    "emerging": "emerging markets fund",
    "esg": "esg sustainable fund",
    "sustainable": "esg sustainable fund",
    "tech": "tech innovation fund",
    "reit": "real estate fund",
}
RESOLVE_MIN, RESOLVE_MARGIN, CANDIDATE_MIN = 0.99, 0.25, 0.5


@dataclass
class Resolution:
    status: str                      # resolved | ambiguous | not_found
    portfolio_id: int | None = None
    portfolio_name: str | None = None
    score: float = 0.0
    candidates: list[tuple[int, str, float]] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("&", " and ")).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in _norm(text).split() if t not in GENERIC]


def _token_hit(token: str, words: list[str]) -> bool:
    return any(w == token or (len(token) > 3 and SequenceMatcher(None, w, token).ratio() >= 0.85) for w in words)


class PortfolioResolver:
    def __init__(self, portfolios: list[tuple]):
        self.portfolios = [(int(p[0]), str(p[1])) for p in portfolios]

    def resolve(self, text: str) -> Resolution:
        if not text or not text.strip():
            return Resolution("not_found")
        norm = _norm(text)
        by_id = {pid: name for pid, name in self.portfolios}

        # 1. explicit id: "portfolio 7", "portfolio id 7", "#7"
        m = re.search(r"\b(?:portfolio|fund|id)\s*(?:id\s*)?#?\s*(\d+)\b", norm) or re.fullmatch(r"\s*#?(\d+)\s*", norm)
        if m and int(m.group(1)) in by_id:
            pid = int(m.group(1))
            return Resolution("resolved", pid, by_id[pid], 1.0, [(pid, by_id[pid], 1.0)])

        # 2. exact full-name containment (longest wins: "Total Stock Market Index Fund")
        exact = [(pid, name) for pid, name in self.portfolios if _norm(name) in norm]
        if exact:
            pid, name = max(exact, key=lambda x: len(x[1]))
            return Resolution("resolved", pid, name, 1.0, [(pid, name, 1.0)])

        # 3. aliases expand the query text
        words = norm.split()
        expanded = " ".join([norm] + [ALIASES[w] for w in words if w in ALIASES])
        words = [w for w in expanded.split() if w not in GENERIC]
        if not words:
            return Resolution("not_found")

        # 4. distinctive-token score: share of the name's distinctive tokens present in the query
        scored = []
        for pid, name in self.portfolios:
            toks = _tokens(name)
            if toks:
                score = sum(_token_hit(t, words) for t in toks) / len(toks)
                scored.append((pid, name, round(score, 3)))
        scored.sort(key=lambda x: (-x[2], x[0]))
        top = [c for c in scored if c[2] >= CANDIDATE_MIN][:5]
        if not top:
            return Resolution("not_found", candidates=scored[:3])
        best = top[0]
        runner_up = top[1][2] if len(top) > 1 else 0.0
        if best[2] >= RESOLVE_MIN and best[2] - runner_up >= RESOLVE_MARGIN:
            return Resolution("resolved", best[0], best[1], best[2], top)
        return Resolution("ambiguous", score=best[2], candidates=top)
