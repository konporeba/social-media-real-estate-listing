"""Unit tests for the Validation Layer — no DB, no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.validation import (
    ValidationAgent,
    _price_in_text,
    _validate_post,
)
from models import PropertyData

# ── Fixtures ──────────────────────────────────────────────────────────────────

URL = "https://dprealestate.es/dom-sprzedaz/willa-ODS"
PRICE = "235 000 EUR"
CATEGORY = "Dom na sprzedaż"


def _data(
    url: str = URL,
    price: str | None = PRICE,
    category: str = CATEGORY,
) -> PropertyData:
    return PropertyData(url=url, title="Willa testowa", price=price, category=category)


def _fb(text: str) -> str:
    """Pad text to a valid Facebook-length post with URL, price, category, hashtags."""
    base = (
        f"{text} {CATEGORY}. Cena: 235 000 EUR. "
        f"Więcej informacji: {URL} "
        "#nieruchomości #hiszpania #costadelsol"
    )
    # Pad to at least 300 chars
    while len(base) < 300:
        base += " nieruchomość"
    return base


def _ig(text: str) -> str:
    base = (
        f"{text}\n{CATEGORY}\nCena: 235 000 EUR\n{URL}\n"
        "#nieruchomości #hiszpania #costadelsol #dom #sprzedaz "
        "#murcja #inwestycja #property #realestate #spain "
        "#domnadelsol #wakacje"
    )
    while len(base) < 200:
        base += " x"
    return base


def _li(text: str) -> str:
    base = f"{text} {CATEGORY}. Cena: 235 000 EUR. Doskonała inwestycja. {URL} #nieruchomości"
    while len(base) < 400:
        base += " nieruchomość"
    return base


# ── _price_in_text ────────────────────────────────────────────────────────────


def test_price_exact_match():
    assert _price_in_text("235 000 EUR", "Cena 235 000 EUR.") is True


def test_price_different_formatting():
    assert _price_in_text("235 000 EUR", "Kosztuje 235000€") is True


def test_price_missing():
    assert _price_in_text("235 000 EUR", "Świetna okazja.") is False


def test_price_no_digits_always_passes():
    assert _price_in_text("Cena na zapytanie", "Dowolny tekst") is True


def test_price_empty_string():
    assert _price_in_text("", "Dowolny tekst") is True


# ── _validate_post — length ───────────────────────────────────────────────────


def test_facebook_length_too_short():
    errors, _ = _validate_post("za krotki", "facebook", _data())
    assert any("length" in e for e in errors)


def test_facebook_length_pass():
    errors, _ = _validate_post(_fb("Piękna willa."), "facebook", _data())
    assert not any("length" in e for e in errors)


def test_instagram_length_too_short():
    errors, _ = _validate_post("krótki", "instagram", _data())
    assert any("length" in e for e in errors)


def test_linkedin_length_too_short():
    errors, _ = _validate_post("za krotki", "linkedin", _data())
    assert any("length" in e for e in errors)


def test_facebook_length_too_long():
    errors, _ = _validate_post("x" * 1300, "facebook", _data())
    assert any("length" in e for e in errors)


# ── _validate_post — URL ──────────────────────────────────────────────────────


def test_url_present_passes():
    errors, _ = _validate_post(_fb("Test."), "facebook", _data())
    assert not any("URL" in e for e in errors)


def test_url_missing_fails():
    content = "A" * 300 + " Dom na sprzedaż 235 000 EUR #a #b #c"
    errors, _ = _validate_post(content, "facebook", _data())
    assert any("URL" in e for e in errors)


def test_url_check_skipped_when_none():
    data = _data(url="")
    errors, _ = _validate_post(_fb("Test."), "facebook", data)
    assert not any("URL" in e for e in errors)


# ── _validate_post — price ────────────────────────────────────────────────────


def test_price_present_passes():
    errors, _ = _validate_post(_fb("Test."), "facebook", _data())
    assert not any("price" in e for e in errors)


def test_price_missing_fails():
    content = "A" * 300 + f" Dom na sprzedaż {URL} #a #b #c"
    errors, _ = _validate_post(content, "facebook", _data())
    assert any("price" in e for e in errors)


def test_price_check_skipped_when_none():
    data = _data(price=None)
    errors, _ = _validate_post(_fb("Test."), "facebook", data)
    assert not any("price" in e for e in errors)


# ── _validate_post — hashtags ─────────────────────────────────────────────────


def test_facebook_hashtags_pass():
    errors, _ = _validate_post(_fb("Test."), "facebook", _data())
    assert not any("hashtag" in e for e in errors)


def test_facebook_too_few_hashtags():
    content = "A" * 300 + f" Dom na sprzedaż 235 000 EUR {URL} #jeden"
    errors, _ = _validate_post(content, "facebook", _data())
    assert any("hashtag" in e for e in errors)


def test_facebook_too_many_hashtags():
    content = f"Dom na sprzedaż 235 000 EUR {URL} " + " ".join(f"#tag{i}" for i in range(10))
    content = content.ljust(300)
    errors, _ = _validate_post(content, "facebook", _data())
    assert any("hashtag" in e for e in errors)


def test_instagram_hashtags_pass():
    errors, _ = _validate_post(_ig("Test."), "instagram", _data())
    assert not any("hashtag" in e for e in errors)


def test_linkedin_no_hashtags_passes():
    content = f"Dom na sprzedaż 235 000 EUR {URL} " + "x " * 50
    errors, _ = _validate_post(content, "linkedin", _data())
    assert not any("hashtag" in e for e in errors)


def test_linkedin_too_many_hashtags():
    content = f"Dom na sprzedaż 235 000 EUR {URL} " + "x " * 50 + "#a #b #c #d"
    errors, _ = _validate_post(content, "linkedin", _data())
    assert any("hashtag" in e for e in errors)


# ── _validate_post — template leakage ────────────────────────────────────────


def test_template_leakage_square_brackets():
    content = _fb("[WSTAW CENĘ]")
    errors, _ = _validate_post(content, "facebook", _data())
    assert any("template" in e for e in errors)


def test_template_leakage_curly_braces():
    content = _fb("{LINK}")
    errors, _ = _validate_post(content, "facebook", _data())
    assert any("template" in e for e in errors)


def test_no_template_leakage_passes():
    errors, _ = _validate_post(_fb("Test."), "facebook", _data())
    assert not any("template" in e for e in errors)


# ── _validate_post — category label ──────────────────────────────────────────


def test_category_present_passes():
    errors, _ = _validate_post(_fb("Test."), "facebook", _data())
    assert not any("category" in e for e in errors)


def test_category_missing_fails():
    content = "A" * 300 + f" 235 000 EUR {URL} #a #b #c"
    errors, _ = _validate_post(content, "facebook", _data())
    assert any("category" in e for e in errors)


def test_category_case_insensitive():
    content = _fb("dom na sprzedaż")  # lowercase version
    errors, _ = _validate_post(content, "facebook", _data(category="Dom na sprzedaż"))
    assert not any("category" in e for e in errors)


def test_category_check_skipped_when_empty():
    data = _data(category="")
    errors, _ = _validate_post(_fb("Test."), "facebook", data)
    assert not any("category" in e for e in errors)


# ── ValidationAgent ───────────────────────────────────────────────────────────


def _make_agent() -> tuple[ValidationAgent, list[str]]:
    emitted: list[str] = []

    async def fake_emit(run_id, agent, event_type, payload):
        emitted.append(event_type)

    agent = ValidationAgent(
        run_id="test-run-id",
        emit=fake_emit,
        logger=MagicMock(),
    )
    return agent, emitted


async def test_agent_passes_clean_drafts():
    agent, emitted = _make_agent()
    data = _data()
    drafts = {
        "facebook": _fb("Piękna willa na sprzedaż."),
        "instagram": _ig("Nowa oferta!"),
        "linkedin": _li("Doskonała inwestycja."),
    }

    with patch.object(agent, "_save_validation_errors"):
        result = await agent.run(property_data=data, drafts=drafts)

    assert result.passed is True
    assert "validation_passed" in emitted


async def test_agent_fails_with_errors():
    agent, emitted = _make_agent()
    data = _data()
    drafts = {
        "facebook": "za krotki",
        "instagram": _ig("OK."),
        "linkedin": _li("OK."),
    }

    with patch.object(agent, "_save_validation_errors"):
        result = await agent.run(property_data=data, drafts=drafts)

    assert result.passed is False
    assert result.errors["facebook"]
    assert "validation_failed" in emitted


async def test_agent_emits_started_event():
    agent, emitted = _make_agent()
    data = _data()
    drafts = {"facebook": _fb("x"), "instagram": _ig("x"), "linkedin": _li("x")}

    with patch.object(agent, "_save_validation_errors"):
        await agent.run(property_data=data, drafts=drafts)

    assert "validation_started" in emitted


async def test_agent_warnings_not_counted_as_errors():
    """Forbidden-word hits go into warnings, not errors — passed stays True."""
    from agents.validation import FORBIDDEN_WORDS

    agent, _ = _make_agent()
    data = _data()
    drafts = {
        "facebook": _fb("Piękna willa."),
        "instagram": _ig("Nowa oferta."),
        "linkedin": _li("Doskonała inwestycja."),
    }

    original = FORBIDDEN_WORDS[:]
    try:
        FORBIDDEN_WORDS.append("testowy_zakaz")
        drafts["facebook"] = _fb("testowy_zakaz willa.")
        with patch.object(agent, "_save_validation_errors"):
            result = await agent.run(property_data=data, drafts=drafts)
        assert result.warnings.get("facebook")
        # passed depends on whether other rules also fire; just check no error from forbidden
        assert not any("forbidden" in e for e in result.errors.get("facebook", []))
    finally:
        FORBIDDEN_WORDS[:] = original
