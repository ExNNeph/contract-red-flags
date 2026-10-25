import builtins

import pytest
from streamlit.testing.v1 import AppTest

from contract_flags import cli


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return AppTest.from_file(str(cli.DEMO_APP), default_timeout=20)  # the file `contract-flags demo` starts


def test_demo_waits_for_click(app):
    at = app.run()
    assert not at.exception and any("Check contract" in i.value for i in at.info)


@pytest.mark.parametrize("sample", [0, 1])
def test_demo_checks_both_samples(app, sample):
    at = app.run()
    at.radio[0].set_value(at.radio[0].options[sample]).run()
    at.button[0].click().run()
    assert not at.exception
    flags = at.session_state["result"].flags
    assert flags and at.session_state["result"].lang == ("en", "de")[sample]
    assert sum(m.value != "0" for m in at.metric) >= 2  # clause count plus at least one severity
    assert len(at.dataframe) == 1  # the retrieval table


def test_quotes_are_shown_verbatim_not_as_markdown(app):
    at = app.run()
    at.button[0].click().run()
    quotes = [m.value for m in at.markdown if m.value.startswith("> ")]
    assert quotes and all(r"\." in q for q in quotes)  # "3. Intellectual Property" stays text, not a list


def test_demo_button_disabled_without_text(app):
    at = app.run()
    at.radio[0].set_value("Paste my own").run()
    assert at.button[0].disabled


def test_cli_prints_flags_with_questions(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    contract = tmp_path / "c.txt"
    contract.write_text("1. Liability\nThe Contractor shall be liable without limitation for all damages.")
    cli.main([str(contract)])
    out = capsys.readouterr().out
    assert "1 clauses (en)" in out and "[HIGH]" in out and "Ask: Can we cap liability" in out
    assert "Not legal advice" in out


def test_demo_without_streamlit_gives_install_hint(monkeypatch):
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "streamlit" else real(n, *a, **k))
    with pytest.raises(SystemExit, match="pip install"):
        cli.demo()
