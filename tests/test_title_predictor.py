"""Tests for Title Performance Predictor service."""

from nichescope.services.title_predictor import (
    extract_title_features,
    EMOTIONAL_WORDS,
    TitleFeatures,
    TitleScore,
)


# --- Feature extraction tests ---


def test_extract_has_number():
    f = extract_title_features("5 Best Kitchen Gadgets")
    assert f.has_number is True

    f2 = extract_title_features("Best Kitchen Gadgets")
    assert f2.has_number is False


def test_extract_has_question():
    f = extract_title_features("Is This Worth It?")
    assert f.has_question is True

    f2 = extract_title_features("This Is Worth It!")
    assert f2.has_question is False


def test_extract_has_how_to():
    f = extract_title_features("How to Make Sourdough Bread")
    assert f.has_how_to is True

    f2 = extract_title_features("Making Sourdough Bread")
    assert f2.has_how_to is False


def test_extract_has_listicle():
    f = extract_title_features("10 Best Pasta Recipes")
    assert f.has_listicle is True

    f2 = extract_title_features("10 Things I Love")
    assert f2.has_listicle is False  # "love" isn't in listicle trigger words

    f3 = extract_title_features("The Best Pasta Recipe Ever")
    assert f3.has_listicle is False  # no number prefix


def test_extract_has_emotional_word():
    f = extract_title_features("This INSANE Trick Changes Everything")
    assert f.has_emotional_word is True

    f2 = extract_title_features("The Honest Truth About Cooking")
    assert f2.has_emotional_word is True

    f3 = extract_title_features("Regular Cooking Techniques")
    assert f3.has_emotional_word is False


def test_extract_has_brackets():
    f = extract_title_features("iPhone Review [HONEST]")
    assert f.has_brackets is True

    f2 = extract_title_features("Budget Cooking (2025 Edition)")
    assert f2.has_brackets is True

    f3 = extract_title_features("Normal Title Here")
    assert f3.has_brackets is False


def test_extract_has_year():
    f = extract_title_features("Best Laptops in 2025")
    assert f.has_year is True

    f2 = extract_title_features("Best Laptops Ever")
    assert f2.has_year is False


def test_extract_has_vs():
    f = extract_title_features("iPhone vs Samsung")
    assert f.has_vs is True

    f2 = extract_title_features("$1 vs. $100 Steak")
    assert f2.has_vs is True

    f3 = extract_title_features("iPhone and Samsung Compared")
    assert f3.has_vs is False


def test_extract_word_count():
    f = extract_title_features("How to Make Sourdough Bread at Home")
    assert f.word_count == 7


def test_extract_char_count():
    title = "Short"
    f = extract_title_features(title)
    assert f.char_count == 5


def test_extract_all_caps_word_count():
    f = extract_title_features("This INSANE HACK Changed EVERYTHING")
    assert f.all_caps_word_count == 3  # INSANE, HACK, EVERYTHING

    f2 = extract_title_features("regular title here")
    assert f2.all_caps_word_count == 0


# --- Emotional words tests ---


def test_emotional_words_is_frozenset():
    assert isinstance(EMOTIONAL_WORDS, frozenset)


def test_emotional_words_contains_expected():
    expected = {"amazing", "insane", "worst", "best", "secret", "hack", "honest"}
    assert expected.issubset(EMOTIONAL_WORDS)


# --- Dataclass tests ---


def test_title_score_dataclass():
    score = TitleScore(
        title="5 Best Recipes",
        score=75.5,
        strengths=["Contains number"],
        weaknesses=[],
        suggestions=["Try adding an emotional hook"],
        niche_avg_score=50.0,
    )
    assert score.score == 75.5
    assert len(score.strengths) == 1
    assert score.niche_avg_score == 50.0


def test_title_features_all_false():
    """Empty-ish title should have all boolean features as False."""
    f = extract_title_features("simple")
    assert f.has_number is False
    assert f.has_question is False
    assert f.has_how_to is False
    assert f.has_listicle is False
    assert f.has_emotional_word is False
    assert f.has_brackets is False
    assert f.has_year is False
    assert f.has_vs is False
    assert f.word_count == 1
