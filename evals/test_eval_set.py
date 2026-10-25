"""Sanity checks on the eval itself: every anchor finds exactly one clause, every labeled risk exists,
the file prefix matches the detected language, and each risk is covered at least once."""
import json
import sys
from pathlib import Path

import pytest

from contract_flags.contract import detect_lang, split_clauses
from contract_flags.knowledge import load_risks

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "gold.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(HERE))
from run_eval import clause_of, errors, gold_pairs  # noqa: E402


@pytest.mark.parametrize("name", GOLD)
def test_labels_point_to_one_clause_and_a_known_risk(name):
    text = (HERE / "contracts" / name).read_text(encoding="utf-8")
    clauses = split_clauses(text)
    assert detect_lang(text) == name[:2]
    assert all(f["risk"] in load_risks() for f in GOLD[name]["flags"])
    flagged = {c for c, _ in gold_pairs(name, clauses)}  # clause_of asserts exactly one match
    fair = {clause_of(a, clauses) for a in GOLD[name]["fair"]}
    assert not flagged & fair, "a clause cannot be both a red flag and a fair trap"


def test_every_risk_is_labeled_at_least_once():
    used = {f["risk"] for case in GOLD.values() for f in case["flags"]}
    assert used == set(load_risks())


def test_error_lines():
    clauses = ["a clause", "another clause"]
    lines = errors({(0, "x"), (1, "y")}, {(1, "y"), (1, "z")}, clauses)
    assert lines == ["extra:  clause 1 as x: 'a clause'", "missed: clause 2 as z: 'another clause'"]
