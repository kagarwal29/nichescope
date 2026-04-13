"""Title performance predictor service (stub)."""
from dataclasses import dataclass

EMOTIONAL_WORDS = frozenset(['amazing', 'insane', 'secret', 'hack', 'incredible', 'mindblown', 'shocking'])

@dataclass
class TitleFeatures:
    has_number: bool = False
    has_question: bool = False
    has_how_to: bool = False
    has_listicle: bool = False
    has_emotional_word: bool = False
    has_brackets: bool = False
    has_vs: bool = False
    word_count: int = 0

@dataclass
class TitleScore:
    title: str
    score: int = 50
    strengths: list = None
    weaknesses: list = None
    suggestions: list = None
    
    def __post_init__(self):
        if self.strengths is None:
            self.strengths = []
        if self.weaknesses is None:
            self.weaknesses = []
        if self.suggestions is None:
            self.suggestions = []

def extract_title_features(title: str) -> TitleFeatures:
    """Extract features from title."""
    return TitleFeatures(
        has_number=any(c.isdigit() for c in title),
        has_question='?' in title,
        has_how_to='how' in title.lower(),
        has_listicle=any(x in title.lower() for x in ['best', 'top', 'worst']),
        has_emotional_word=any(w in title.lower() for w in EMOTIONAL_WORDS),
        has_brackets='[' in title or ']' in title,
        has_vs=' vs ' in title.lower(),
        word_count=len(title.split())
    )

async def compare_titles(session, niche_id, titles: list[str]):
    """Score and compare titles."""
    return [TitleScore(title=t) for t in titles]
