"""Local web demo, started with `contract-flags demo`."""
import os

import pandas as pd
import streamlit as st

from contract_flags.knowledge import load_risks
from contract_flags.review import MODEL, review

SAMPLES = {
    "English sample (freelance development)": """Freelance Development Agreement

1. Fees and Payment
The Client pays a fixed fee of EUR 12,000. Invoices are payable within 90 days of receipt.

2. Revisions
The Contractor shall make all changes requested by the Client until the Client is fully satisfied, without additional charge.

3. Intellectual Property
All rights in the work product, including any pre-existing tools, libraries and templates used by the Contractor, are assigned to the Client. The rights transfer upon creation, regardless of payment.

4. Liability
The Contractor's liability is limited to the total fee paid under this agreement, except in cases of intent or gross negligence.

5. Termination
The Client may terminate this agreement at any time without notice. Work performed until termination will not be compensated.""",
    "Deutsches Beispiel (Influencer-Kooperation)": """Kooperationsvereinbarung

1. Vergütung
Die Vergütung von 3.000 Euro ist 90 Tage nach Veröffentlichung fällig.

2. Nutzung
Die Marke darf die Inhalte sowie Name und Bildnis der Creatorin zeitlich unbegrenzt, weltweit und in allen Medien nutzen, auch für Werbeanzeigen, ohne zusätzliche Vergütung.

3. Exklusivität
Die Creatorin arbeitet während der Laufzeit im Bereich Getränke nur mit der Marke zusammen. Diese Exklusivität wird mit 500 Euro gesondert vergütet.

4. Kündigung
Die Marke kann den Vertrag jederzeit fristlos ohne Angabe von Gründen kündigen. Bereits erbrachte Leistungen werden nicht vergütet.""",
}
BADGE = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟡 Low"}
ORDER = {"high": 0, "medium": 1, "low": 2}

st.set_page_config(page_title="Contract Red Flags demo", page_icon="🚩", layout="wide")
st.title("🚩 Contract Red Flags")
st.caption("Paste or upload a contract (English or German) and see which clauses are worth asking about "
           "before you sign. **Not legal advice**: a checklist of questions, not a judgement on the contract.")

with st.sidebar:
    api_key = st.text_input("Anthropic API key (optional)", type="password",
                            help="Used only for your requests in this local session, never stored.")
    if api_key or os.getenv("ANTHROPIC_API_KEY"):
        where = "sidebar" if api_key else "ANTHROPIC_API_KEY environment variable"
        st.success(f"🔑 Key set ({where}): Claude ({MODEL}) decides which clauses are really risky.")
    else:
        st.info("No key: retrieval only. Every clause that resembles a risk is flagged, fair ones too. "
                "Paste a key and press Enter to let Claude judge.")
    st.markdown(f"**How it works:** each clause is matched against {len(load_risks())} known risks "
                "(BM25 search). Claude checks the top 3 candidates per clause. A flag must quote the clause "
                "and name a retrieved risk; anything else is dropped.")

source = st.radio("Contract", [*SAMPLES, "Upload a file", "Paste my own"], horizontal=True)
if source == "Upload a file":
    upload = st.file_uploader("Contract as .txt or .md", type=["txt", "md"])
    text = upload.getvalue().decode("utf-8", errors="replace") if upload else ""
elif source == "Paste my own":
    text = st.text_area("Contract text", height=300, placeholder="1. Payment\nInvoices are payable within ...")
else:
    text = st.text_area("Contract text", SAMPLES[source], height=300)


@st.cache_data(show_spinner="Checking the clauses…")
def cached_review(contract: str, key: str):
    # cached so reruns (clicking, scrolling) never call or pay for the API twice
    return review(contract, key or None)


if st.button("Check contract", type="primary", disabled=not text.strip()):
    st.session_state.result = cached_review(text, api_key)
    st.session_state.result_for = (text, api_key)

result = st.session_state.get("result")
if result is None:
    st.info("👆 Pick a sample, upload a file or paste a contract, then click **Check contract**.")
    st.stop()
if st.session_state.get("result_for") != (text, api_key):
    st.warning("The contract or key changed since this result. Click **Check contract** again to update it.")

risks = load_risks()
counts = {s: sum(risks[f.risk_id].severity == s for f in result.flags) for s in ORDER}
if result.source == "llm":
    st.success(f"Checked by Claude ({MODEL}). Every flag quotes the contract and names a risk from the knowledge base.")
elif result.source == "retrieval only (API error)":
    st.error(f"The Claude call failed, so retrieval-only flags are shown.\n\n`{result.error}`")
else:
    st.info("Retrieval only: clauses that resemble a known risk, including fair ones. Add an API key to let Claude judge.")

cols = st.columns(4)
cols[0].metric("Clauses", len(result.clauses))
for col, s in zip(cols[1:], ORDER):
    col.metric(BADGE[s], counts[s])

st.subheader("Worth asking about")
if not result.flags:
    st.write("No clause matches a known risk. That does not mean the contract is fine, only that none of the "
             f"{len(risks)} risks in the knowledge base were found.")
for f in sorted(result.flags, key=lambda f: (ORDER[risks[f.risk_id].severity], f.clause)):
    risk = risks[f.risk_id]
    t = risk.text(result.lang)
    with st.container(border=True):
        st.markdown(f"**{BADGE[risk.severity]} · {t.title}** · clause {f.clause + 1}")
        st.markdown(f"> {f.quote}")
        st.write(f.explanation)
        st.markdown(f"**Ask:** {t.question}")

if result.dropped:
    with st.expander(f"Dropped by the guardrail ({len(result.dropped)})"):
        for f, why in result.dropped:
            st.warning(f"Clause {f.clause + 1} as `{f.risk_id}`: {why}")

with st.expander("All clauses and their retrieved candidates (BM25)"):
    st.dataframe(pd.DataFrame([{
        "clause": i + 1, "text": c[:120] + ("…" if len(c) > 120 else ""),
        "candidates": ", ".join(f"{risks[rid].text(result.lang).title} ({score:.1f})" for rid, score in cands) or "—",
        "flagged": ", ".join(risks[f.risk_id].text(result.lang).title for f in result.flags if f.clause == i) or "—",
    } for i, (c, cands) in enumerate(zip(result.clauses, result.candidates))]), hide_index=True, width="stretch")
