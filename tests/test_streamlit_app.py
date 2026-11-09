"""Runs the Streamlit app headlessly, with no API key, so no model is ever called."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from portfolio_agent.config import ROOT

APP = str(ROOT / "streamlit_app.py")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    st.cache_resource.clear()
    st.cache_data.clear()


def run(app: AppTest) -> AppTest:
    app.run(timeout=60)
    assert not app.exception, app.exception
    return app


def example(app: AppTest, text: str):
    return next(b for b in app.sidebar.button if b.label == text)


def test_page_lists_examples_dataset_and_evaluation():
    app = run(AppTest.from_file(APP))
    labels = [b.label for b in app.sidebar.button]
    assert "Sector breakdown for the Balanced Portfolio" in labels and len(labels) == 6
    sidebar_text = " ".join(m.value for m in app.sidebar.markdown)
    assert "13 portfolios" in sidebar_text and "Gemini not configured" in sidebar_text
    assert [t.label for t in app.tabs] == ["Query", "Evaluation"]
    assert any(m.label == "Strict accuracy" for m in app.metric)


def test_model_indicator_reports_configuration_not_connectivity(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    app = run(AppTest.from_file(APP))

    sidebar_text = " ".join(m.value for m in app.sidebar.markdown)
    assert "Gemini configured" in sidebar_text
    assert "Gemini connected" not in sidebar_text


def test_example_answers_from_stored_plan():
    app = run(AppTest.from_file(APP))
    example(app, "Which portfolio has the largest AUM?").click()
    run(app)
    assert any("Cached" in c.value for c in app.caption)
    assert app.dataframe and "Total Stock Market Index Fund" in app.dataframe[0].value.to_string()


def test_typed_exposure_question_uses_calculator():
    app = run(AppTest.from_file(APP))
    app.text_input(key="question_box").set_value("Sector breakdown for Tech Innovation Fund")
    next(b for b in app.button if b.label == "Run").click()
    run(app)
    assert any("Calculator" in c.value for c in app.caption)
    assert any("Tech Innovation Fund" in m.value for m in app.markdown)


def test_question_needing_the_model_reports_missing_key():
    app = run(AppTest.from_file(APP))
    app.text_input(key="question_box").set_value("How many bonds are there?")
    next(b for b in app.button if b.label == "Run").click()
    run(app)
    assert app.error and "Gemini is not configured" in app.error[0].value


def test_public_page_opens_without_login_even_with_legacy_password_env(monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "ignored-legacy-setting")
    app = run(AppTest.from_file(APP))
    assert len(app.sidebar.button) == 6
    assert [item.label for item in app.text_input] == ["Question"]
    assert all(item.label != "Password" for item in app.text_input)
