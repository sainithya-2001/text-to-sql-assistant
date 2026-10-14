"""Streamlit UI smoke tests (no API key: exercises rendering and the clarification flow only)."""

from __future__ import annotations

import pytest

from text_to_sql.config import PROJECT_ROOT

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(PROJECT_ROOT / "app" / "streamlit_app.py")


@pytest.fixture
def app(tpch_path, monkeypatch):
    monkeypatch.setenv("T2S_DUCKDB_PATH", str(tpch_path))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def test_renders_without_api_key(app):
    assert not app.exception
    assert app.title[0].value == "Text-to-SQL Assistant"
    assert any("ANTHROPIC_API_KEY" in w.value for w in app.warning)


def test_ambiguous_question_offers_choices(app):
    app.text_input[0].set_value("Who are our biggest customers?")
    app.button[-1].click()  # the form's Ask button is rendered last among buttons in the main area
    app.run()
    assert not app.exception
    assert any("Clarification needed" in i.value for i in app.info)
    assert "by revenue" in app.radio(key="pick-biggest customers").options
