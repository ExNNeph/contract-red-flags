import argparse
import subprocess
import sys
from pathlib import Path

from .knowledge import load_risks
from .review import review

DEMO_APP = Path(__file__).with_name("demo_app.py")
ICON = {"high": "[HIGH]  ", "medium": "[MEDIUM]", "low": "[LOW]   "}


def demo() -> None:
    """Start the local web demo on http://localhost:8501 and open the browser."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise SystemExit('The demo needs Streamlit: pip install -e ".[demo]"')
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(DEMO_APP), "--server.address", "localhost",
                    "--server.port", "8501", "--browser.gatherUsageStats", "false",
                    "--client.toolbarMode", "minimal",  # hides Streamlit's "Deploy" button
                    "--server.fileWatcherType", "none"])  # no code reloading needed, and no "install Watchdog" hint


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["demo"]:
        return demo()
    p = argparse.ArgumentParser(prog="contract-flags", description="Flag contract clauses worth asking about "
                                "before you sign (not legal advice). Run `contract-flags demo` for the web demo.")
    p.add_argument("contract", type=Path, help="contract as a .txt or .md file, English or German")
    args = p.parse_args(argv)

    result = review(args.contract.read_text(encoding="utf-8"))
    risks = load_risks()
    print(f"{len(result.clauses)} clauses ({result.lang}), {len(result.flags)} flag(s) ({result.source})"
          + (f": {result.error}" if result.error else ""))
    order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(result.flags, key=lambda f: (order[risks[f.risk_id].severity], f.clause)):
        risk = risks[f.risk_id]
        t = risk.text(result.lang)
        print(f"\n{ICON[risk.severity]} clause {f.clause + 1}: {t.title}\n  \"{f.quote}\"\n  {f.explanation}\n"
              f"  Ask: {t.question}")
    for f, why in result.dropped:
        print(f"\n  dropped by guardrail: clause {f.clause + 1} as {f.risk_id} ({why})")
    print("\nNot legal advice: a checklist of questions to raise before signing.")
