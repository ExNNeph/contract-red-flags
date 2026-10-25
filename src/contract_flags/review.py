"""Review a contract: retrieve candidate risks per clause, let Claude decide which really apply, and keep
only flags that quote the clause and point to a retrieved risk."""
import json
import logging
import os
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from .contract import detect_lang, split_clauses
from .knowledge import load_risks, retrieve

log = logging.getLogger(__name__)
usage = {"in": 0, "out": 0}  # running token totals, read by evals/run_eval.py
MODEL = os.getenv("CONTRACT_FLAGS_MODEL", "claude-opus-5-5")
K = 3  # candidate risks per clause
BASELINE_MIN_SCORE = 4.0  # retrieval-only baseline flags the top risk above this BM25 score

SYSTEM = """You review contracts for freelancers and creators and point out clauses worth negotiating.
For each numbered clause you get up to three candidate risks from a knowledge base. Flag a clause only
if its wording actually creates that risk for the freelancer. Many clauses mention the same topic in a
fair way (for example, liability limited to the fee, payment within 14 days, two revision rounds, a
non-compete limited to the project): do NOT flag those. Only use risk ids from that clause's candidates.
For each flag return:
- clause: the clause number
- risk_id: one of that clause's candidate ids
- quote: the exact words from the clause that create the risk, copied verbatim (one sentence or less)
- explanation: one or two sentences on why this wording is a problem here, in the contract's language"""

SCHEMA = {
    "type": "object",
    "properties": {"flags": {"type": "array", "items": {
        "type": "object",
        "properties": {"clause": {"type": "integer"}, "risk_id": {"type": "string"},
                       "quote": {"type": "string"}, "explanation": {"type": "string"}},
        "required": ["clause", "risk_id", "quote", "explanation"],
        "additionalProperties": False,
    }}},
    "required": ["flags"],
    "additionalProperties": False,
}


class Flag(BaseModel):
    clause: int  # index into Review.clauses
    risk_id: str
    quote: str
    explanation: str


@dataclass
class Review:
    lang: str
    clauses: list[str]
    candidates: list[list[tuple[str, float]]]  # per clause: retrieved (risk_id, score)
    flags: list[Flag]
    source: str  # "llm", "retrieval only" or "retrieval only (API error)"
    dropped: list[tuple[Flag, str]] = field(default_factory=list)
    error: str = ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", text.lower()).strip()


def grounded(flag: Flag, clauses: list[str], candidates: list[list[tuple[str, float]]]) -> str | None:
    """Guardrail: why the flag is not backed by the contract and the knowledge base, or None if it is."""
    if not 0 <= flag.clause < len(clauses):
        return f"clause {flag.clause + 1} does not exist"
    if flag.risk_id not in {rid for rid, _ in candidates[flag.clause]}:
        return f"risk '{flag.risk_id}' was not retrieved for this clause"
    if len(_norm(flag.quote)) < 3 or _norm(flag.quote) not in _norm(clauses[flag.clause]):
        return "quote not found in the clause"
    return None


def review(text: str, api_key: str | None = None) -> Review:
    lang, clauses = detect_lang(text), split_clauses(text)
    candidates = [retrieve(c, lang, K) for c in clauses]
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return Review(lang, clauses, candidates, baseline_flags(clauses, candidates, lang), "retrieval only")
    try:
        raw = _llm_flags(clauses, candidates, lang, key)
    except Exception as e:  # API down, bad key, refusal: still show what retrieval found
        log.warning("LLM call failed (%s), using retrieval only", type(e).__name__)
        return Review(lang, clauses, candidates, baseline_flags(clauses, candidates, lang),
                      "retrieval only (API error)", error=f"{type(e).__name__}: {e}"[:300])
    flags, dropped = [], []
    for item in raw:
        try:
            flag = Flag(**{**item, "clause": int(item["clause"]) - 1})  # Claude numbers clauses from 1
        except (ValidationError, KeyError, TypeError, ValueError):
            continue
        if reason := grounded(flag, clauses, candidates):
            dropped.append((flag, reason))
        elif (flag.clause, flag.risk_id) not in {(f.clause, f.risk_id) for f in flags}:
            flags.append(flag)
    return Review(lang, clauses, candidates, flags, "llm", dropped)


def baseline_flags(clauses: list[str], candidates: list[list[tuple[str, float]]], lang: str) -> list[Flag]:
    """Retrieval without judgment: flag each clause's best match if it scores high enough."""
    risks = load_risks()
    return [Flag(clause=i, risk_id=cands[0][0], quote=clauses[i], explanation=risks[cands[0][0]].text(lang).description)
            for i, cands in enumerate(candidates) if cands and cands[0][1] >= BASELINE_MIN_SCORE]


def _llm_flags(clauses: list[str], candidates: list[list[tuple[str, float]]], lang: str, api_key: str) -> list[dict]:
    import anthropic

    risks = load_risks()
    parts = []
    for i, (clause, cands) in enumerate(zip(clauses, candidates), 1):
        listed = "\n".join(f"  - {rid}: {risks[rid].text(lang).title}. {risks[rid].text(lang).description}"
                           for rid, _ in cands) or "  (no candidates)"
        parts.append(f"Clause {i}: {clause}\nCandidates:\n{listed}")
    resp = anthropic.Anthropic(api_key=api_key).beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if a safety classifier declines, the API retries on a fallback model
        system=SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": f"Contract language: {lang}\n\n" + "\n\n".join(parts)}],
    )
    usage["in"] += resp.usage.input_tokens
    usage["out"] += resp.usage.output_tokens
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined the request")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))["flags"]
