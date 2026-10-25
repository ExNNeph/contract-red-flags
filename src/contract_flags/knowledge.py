"""The risk knowledge base and a small BM25 index over it (one index per language)."""
import json
import math
import re
from collections import Counter
from functools import cache
from importlib.resources import files

from pydantic import BaseModel

STOP = {"en": {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "is", "are", "be",
               "this", "that", "any", "all", "as", "at", "it", "its", "you", "your", "shall", "will", "may"},
        "de": {"der", "die", "das", "und", "oder", "ein", "eine", "einer", "eines", "zu", "in", "im", "auf",
               "für", "mit", "von", "vom", "bei", "ist", "sind", "wird", "werden", "sie", "ihr", "ihre", "den",
               "dem", "des", "auch", "nicht", "als", "an", "am", "so", "sich"}}
SUFFIXES = {"en": ("ations", "ation", "ities", "ity", "ing", "ies", "ed", "es", "s"),
            "de": ("ungen", "ung", "ern", "en", "er", "es", "e", "n", "s")}


class RiskText(BaseModel):
    title: str
    description: str
    question: str
    keywords: list[str]


class Risk(BaseModel):
    id: str
    severity: str  # high | medium | low
    en: RiskText
    de: RiskText

    def text(self, lang: str) -> RiskText:
        return self.de if lang == "de" else self.en


@cache
def load_risks() -> dict[str, Risk]:
    raw = json.loads(files("contract_flags").joinpath("risks.json").read_text(encoding="utf-8"))
    return {r["id"]: Risk(**r) for r in raw}


def tokens(text: str, lang: str) -> list[str]:
    """Lowercase words without stop words, with a crude suffix strip so 'liable'/'liability' and
    'haftet'/'haftung' share a stem. ponytail: no real stemmer or compound splitting; recall@k in
    the eval shows when this stops being enough (next step: embeddings)."""
    out = []
    for word in re.findall(r"[a-zäöüß0-9]+", text.lower()):
        if word in STOP[lang]:
            continue
        for suffix in SUFFIXES[lang]:
            if len(word) - len(suffix) >= 4 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        out.append(word)
    return out


class BM25:
    def __init__(self, docs: dict[str, list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = {i: Counter(d) for i, d in docs.items()}, k1, b
        self.avg = sum(map(len, docs.values())) / len(docs)
        self.lens = {i: len(d) for i, d in docs.items()}
        df = Counter(t for d in docs.values() for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> dict[str, float]:
        out = {}
        for i, tf in self.docs.items():
            norm = self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg)
            out[i] = sum(self.idf.get(t, 0) * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in query if t in tf)
        return out


@cache
def index(lang: str) -> BM25:
    docs = {}
    for risk in load_risks().values():
        t = risk.text(lang)
        # keywords twice: they are the phrases contracts actually use
        docs[risk.id] = tokens(" ".join([t.title, t.description, *t.keywords, *t.keywords]), lang)
    return BM25(docs)


def retrieve(clause: str, lang: str, k: int = 3) -> list[tuple[str, float]]:
    """Top-k (risk_id, score) for a clause, best first; risks without any shared term are left out."""
    ranked = sorted(index(lang).scores(tokens(clause, lang)).items(), key=lambda x: -x[1])
    return [(rid, s) for rid, s in ranked[:k] if s > 0]
