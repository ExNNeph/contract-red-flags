"""Split a contract into clauses and detect whether it is English or German."""
import re

NUMBERED = re.compile(r"^\s*(?:§\s*\d+|\d+(?:\.\d+)*\.?|\([a-z0-9]\)|(?:section|clause|article|ziffer)\s+\d+)\s",
                      re.IGNORECASE)
GERMAN = {"der", "die", "das", "und", "ist", "nicht", "wird", "werden", "für", "mit", "auf", "des", "dem",
          "den", "eine", "einer", "auftraggeber", "auftragnehmer", "sie", "vertrag", "zu", "von", "bei"}
ENGLISH = {"the", "and", "is", "not", "will", "shall", "for", "with", "on", "of", "a", "an", "to", "be",
           "by", "client", "contractor", "agreement", "you", "any", "this", "that", "in"}


def detect_lang(text: str) -> str:
    words = re.findall(r"[a-zäöüß]+", text.lower())
    return "de" if sum(w in GERMAN for w in words) > sum(w in ENGLISH for w in words) else "en"


def split_clauses(text: str) -> list[str]:
    """One clause per paragraph or numbered line. Short heading-like lines ("5. Liability") are
    joined with the clause that follows, so every clause carries its own heading."""
    blocks = []
    for para in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in para.splitlines() if line.strip()]
        current: list[str] = []
        for line in lines:
            if NUMBERED.match(line) and current and not _is_heading(current):
                blocks.append(" ".join(current))
                current = []
            current.append(line)
        if current:
            blocks.append(" ".join(current))
    clauses, heading = [], ""
    for block in blocks:
        if _is_heading([block]):
            heading = f"{heading} {block}".strip()
            continue
        clauses.append(f"{heading} {block}".strip())
        heading = ""
    return clauses + ([heading] if heading else [])


def _is_heading(lines: list[str]) -> bool:
    """'5. Liability', '§ 4 Haftung': short, few words, no sentence-ending punctuation."""
    text = " ".join(lines).strip()
    return len(text) < 60 and len(text.split()) <= 6 and not text.endswith((".", ";", ":", "!", "?", ","))
