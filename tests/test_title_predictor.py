"""Tests for Title Performance Predictor service."""
from nichescope.services.title_predictor import extract_title_features, EMOTIONAL_WORDS

def test_has_number(): assert extract_title_features("5 Best Kitchen Gadgets").has_number
def test_has_question(): assert extract_title_features("Is This Worth It?").has_question
def test_has_how_to(): assert extract_title_features("How to Make Sourdough").has_how_to
def test_has_emotional(): assert extract_title_features("This INSANE Trick Changes Everything").has_emotional_word
def test_has_brackets(): assert extract_title_features("iPhone Review [HONEST]").has_brackets
def test_has_vs(): assert extract_title_features("iPhone vs Samsung").has_vs
def test_word_count(): assert extract_title_features("How to Make Bread at Home").word_count == 6
def test_emotional_frozenset(): assert isinstance(EMOTIONAL_WORDS, frozenset)
def test_emotional_contains(): assert {"amazing", "insane", "secret", "hack"}.issubset(EMOTIONAL_WORDS)
def test_all_false():
    f = extract_title_features("simple")
    assert not any([f.has_number, f.has_question, f.has_how_to, f.has_listicle, f.has_vs])
