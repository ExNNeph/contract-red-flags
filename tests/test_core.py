import pytest

from contract_flags import review as rv
from contract_flags.contract import detect_lang, split_clauses
from contract_flags.knowledge import load_risks, retrieve, tokens

CONTRACT = """Service Agreement

1. Liability
The Contractor shall be liable without limitation for all damages, including lost profits.

2. Payment
Invoices are payable within 14 days.
3. Term
This agreement renews automatically unless cancelled six months before the end of the term."""


def test_split_keeps_headings_with_their_clause_and_splits_numbered_lines():
    clauses = split_clauses(CONTRACT)
    assert len(clauses) == 3
    assert clauses[0].startswith("Service Agreement 1. Liability The Contractor")
    assert clauses[1] == "2. Payment Invoices are payable within 14 days."
    assert clauses[2].startswith("3. Term This agreement renews")


def test_split_german_paragraph_signs():
    clauses = split_clauses("§ 1 Haftung\nDer Auftragnehmer haftet unbeschränkt.\n\n§ 2 Zahlung\nZahlbar in 14 Tagen.")
    assert clauses == ["§ 1 Haftung Der Auftragnehmer haftet unbeschränkt.", "§ 2 Zahlung Zahlbar in 14 Tagen."]


def test_detect_lang():
    assert detect_lang(CONTRACT) == "en"
    assert detect_lang("Der Auftragnehmer haftet für die Schäden und wird die Leistung erbringen.") == "de"


def test_tokens_share_stems_and_drop_stop_words():
    assert tokens("The liability of the Contractor", "en") == tokens("liability", "en") + ["contractor"]
    assert tokens("liabilities", "en") == tokens("liability", "en")
    assert tokens("Haftung", "de")[0] == tokens("haften", "de")[0]


def test_knowledge_base_is_complete_in_both_languages():
    risks = load_risks()
    assert len(risks) == 18
    for risk in risks.values():
        assert risk.severity in {"high", "medium", "low"}
        for lang in ("en", "de"):
            t = risk.text(lang)
            assert t.title and t.description and t.question.endswith("?") and t.keywords


@pytest.mark.parametrize("clause,lang,expected", [
    ("The Contractor shall be liable without limitation for all damages, including lost profits.", "en",
     "unlimited_liability"),
    ("This agreement renews automatically unless cancelled six months before the end.", "en", "auto_renewal"),
    ("Der Auftragnehmer haftet unbeschränkt für sämtliche Schäden.", "de", "unlimited_liability"),
    ("Für jeden Tag des Verzugs ist eine Vertragsstrafe von 500 Euro fällig.", "de", "contract_penalty"),
])
def test_retrieve_ranks_the_matching_risk_first(clause, lang, expected):
    assert retrieve(clause, lang)[0][0] == expected


CLAUSES = split_clauses(CONTRACT)
CANDS = [retrieve(c, "en", rv.K) for c in CLAUSES]


def flag(**kw):
    return rv.Flag(**{"clause": 0, "risk_id": "unlimited_liability", "quote": "liable without limitation",
                      "explanation": "x", **kw})


def test_guardrail():
    assert rv.grounded(flag(), CLAUSES, CANDS) is None
    assert "does not exist" in rv.grounded(flag(clause=9), CLAUSES, CANDS)
    assert "not retrieved" in rv.grounded(flag(risk_id="portfolio_ban"), CLAUSES, CANDS)
    assert "quote" in rv.grounded(flag(quote="liable for everything forever"), CLAUSES, CANDS)


def test_review_with_llm_keeps_grounded_flags_only(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(rv, "_llm_flags", lambda *a: [
        {"clause": 1, "risk_id": "unlimited_liability", "quote": "liable without limitation", "explanation": "ok"},
        {"clause": 1, "risk_id": "unlimited_liability", "quote": "liable without limitation", "explanation": "dup"},
        {"clause": 3, "risk_id": "auto_renewal", "quote": "renews forever", "explanation": "invented quote"},
        {"clause": 2, "risk_id": "portfolio_ban", "quote": "payable within 14 days", "explanation": "not retrieved"},
    ])
    result = rv.review(CONTRACT)
    assert result.source == "llm"
    assert [(f.clause, f.risk_id) for f in result.flags] == [(0, "unlimited_liability")]  # numbering from 1 -> 0
    assert [why for _, why in result.dropped] == ["quote not found in the clause",
                                                   "risk 'portfolio_ban' was not retrieved for this clause"]


def test_api_error_falls_back_to_retrieval_with_reason(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def boom(*a):
        raise RuntimeError("overloaded")

    monkeypatch.setattr(rv, "_llm_flags", boom)
    result = rv.review(CONTRACT)
    assert (result.source, result.error) == ("retrieval only (API error)", "RuntimeError: overloaded")
    assert {f.risk_id for f in result.flags} >= {"unlimited_liability", "auto_renewal"}


def test_without_key_baseline_flags_by_score(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = rv.review(CONTRACT)
    assert result.source == "retrieval only" and result.lang == "en"
    assert len(result.candidates) == len(result.clauses) == 3
