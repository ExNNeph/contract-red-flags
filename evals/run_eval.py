"""Score retrieval and flags against the labeled contracts. Usage: python evals/run_eval.py [repeats]

Gold flags name their clause by an anchor (a unique piece of its text) and a risk id. Reported:
retrieval recall@k (is the labeled risk among the clause's candidates?), flag precision/recall, and
how many "fair" trap clauses got flagged. Claude rows need ANTHROPIC_API_KEY.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

from contract_flags import review as rv
from contract_flags.contract import detect_lang, split_clauses
from contract_flags.knowledge import retrieve

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "gold.json").read_text(encoding="utf-8"))


def clause_of(anchor: str, clauses: list[str]) -> int:
    hits = [i for i, c in enumerate(clauses) if anchor in c]
    assert len(hits) == 1, f"anchor {anchor!r} matches {len(hits)} clauses"
    return hits[0]


def gold_pairs(name: str, clauses: list[str]) -> set[tuple[int, str]]:
    return {(clause_of(f["anchor"], clauses), f["risk"]) for f in GOLD[name]["flags"]}


def score(pred: set[tuple[int, str]], gold: set[tuple[int, str]], fair: set[int]) -> Counter:
    return Counter(pred=len(pred), gold=len(gold), tp=len(pred & gold),
                   fair_flagged=len({c for c, _ in pred} & fair), fair=len(fair))


def errors(pred, gold, clauses) -> list[str]:
    out = [f"extra:  clause {c + 1} as {r}: {clauses[c][:70]!r}" for c, r in sorted(pred - gold)]
    return out + [f"missed: clause {c + 1} as {r}: {clauses[c][:70]!r}" for c, r in sorted(gold - pred)]


def retrieval_recall(k: int) -> float:
    hit = total = 0
    for name, case in GOLD.items():
        text = (HERE / "contracts" / name).read_text(encoding="utf-8")
        clauses, lang = split_clauses(text), detect_lang(text)
        for c, risk in gold_pairs(name, clauses):
            total += 1
            hit += risk in {rid for rid, _ in retrieve(clauses[c], lang, k)}
    return hit / total


def evaluate(run, repeats: int, show_errors: bool = False) -> tuple[Counter, int]:
    total, dropped = Counter(), 0
    for name, case in GOLD.items():
        text = (HERE / "contracts" / name).read_text(encoding="utf-8")
        clauses = split_clauses(text)
        gold, fair = gold_pairs(name, clauses), {clause_of(a, clauses) for a in case["fair"]}
        for i in range(repeats):
            print(f"  {name} run {i + 1}/{repeats} …", file=sys.stderr, flush=True)
            result = run(text)
            pred = {(f.clause, f.risk_id) for f in result.flags}
            total += score(pred, gold, fair)
            dropped += len(result.dropped)
            for line in errors(pred, gold, clauses) if show_errors else []:
                print(f"      {line}", file=sys.stderr)
    return total, dropped


def llm(text):
    result = rv.review(text)
    if result.source != "llm":
        raise SystemExit(f"LLM call failed: {result.error}")
    return result


def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print("Retrieval recall (labeled risk among the clause's top-k candidates): "
          + ", ".join(f"@{k} {retrieval_recall(k):.0%}" for k in (1, 3, 5)) + "\n")

    def baseline(text):
        clauses, lang = split_clauses(text), detect_lang(text)
        candidates = [retrieve(c, lang, rv.K) for c in clauses]
        return rv.Review(lang, clauses, candidates, rv.baseline_flags(clauses, candidates, lang), "retrieval only")

    rows = [("retrieval only (top match)", *evaluate(baseline, 1))]
    if os.getenv("ANTHROPIC_API_KEY"):
        rows.append((f"retrieval + Claude ({rv.MODEL}) + guardrail", *evaluate(llm, repeats, show_errors=True)))
    else:
        print("No ANTHROPIC_API_KEY set: Claude row skipped.\n")

    print("| method | flags | precision | recall | F1 | fair clauses flagged | guardrail drops |")
    print("|---|---|---|---|---|---|---|")
    for name, c, dropped in rows:
        p = c["tp"] / c["pred"] if c["pred"] else 0
        r = c["tp"] / c["gold"]
        f1 = 2 * p * r / (p + r) if p + r else 0
        print(f"| {name} | {c['pred']} | {p:.0%} | {r:.0%} | {f1:.0%} | {c['fair_flagged']}/{c['fair']} | {dropped} |")
    if rv.usage["in"]:
        calls = len(GOLD) * repeats
        print(f"\nLLM tokens: {rv.usage['in']} in / {rv.usage['out']} out "
              f"({rv.usage['in'] // calls} / {rv.usage['out'] // calls} per contract)")


if __name__ == "__main__":
    main()
