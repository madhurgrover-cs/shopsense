"""Spelling correction for search queries ("sirt" -> "shirt", "laptp" -> "laptop").

How it works:
1. A VOCABULARY of words the shop knows: every word in active product names and
   category names, plus a hand-written list of common product words (COMMON_WORDS).
   Each word also has a count (how many names contain it), used to break ties.
2. Each query word that is NOT already known is compared with every vocabulary word
   using rapidfuzz's fuzz.ratio: a 0-100 similarity based on how many letters must be
   inserted or deleted to turn one word into the other (a changed letter counts as a
   deletion plus an insertion).
       sirt  -> shirt     88.9   (1 letter missing)
       hodie -> hoodie    90.9
       laptp -> laptop    90.9
       keybord -> keyboard 93.3
3. The best match replaces the word only if its score reaches a threshold that depends
   on the word's length (min_score). Short words need a STRICTER threshold, because one
   wrong letter is a bigger share of a short word: "warm" vs "farm" already scores 75,
   and correcting it would change what the user meant.

Words are never corrected when they are:
- known: in the vocabulary, OR anywhere in a product description (`known_words`). A
  description word like "fleece" is a real word the search can use as it is.
- 3 letters or shorter ("pen", "mat", "red"): too little to tell a typo from a word.
- containing digits ("128gb", "x200"): model numbers and sizes, not spellings.
- the plural of a known word ("watches", "dogs").
And a correction must keep the FIRST letter: people rarely mistype the first letter,
and without this rule "chair" (which the shop doesn't sell) would become "hair".
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz, process

# Words shoppers type that may not appear in any product NAME. They are valid
# correction targets ("hoodies" -> fine; "hodies" -> "hoodies") and are never changed.
COMMON_WORDS = """
    shirt shirts tshirt tshirts hoodie hoodies jacket jackets sweater sweatshirt trousers
    pants jeans shorts dress dresses kurta kurtas saree sarees shoes shoe sneakers sandals
    slippers socks boots laptop laptops computer keyboard keyboards mouse monitor headphones
    earphones earbuds headset charger cable phone phones mobile smartphone watch
    speaker camera bottle bottles kitchen cookware cooker mixer grinder pan pans lamp
    bedsheet pillow towel book books novel notebook cricket football badminton racket yoga
    gym fitness dumbbell dumbbells shampoo conditioner soap sunscreen moisturiser cream
    perfume trimmer gift gifts warm winter summer cotton leather wireless gaming gamer
    running office travel kids men women girls boys cheap budget premium black white blue
""".split()

WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Vocabulary:
    words: Counter          # correction targets -> how many names contain the word
    known_words: frozenset  # never corrected (vocabulary + description words)


@dataclass(frozen=True)
class Correction:
    original: str
    corrected: str          # equal to original when nothing was changed
    changes: tuple          # ((typed word, corrected word), ...)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def words_in(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def build_vocabulary(names: Iterable[str], descriptions: Iterable[str] = ()) -> Vocabulary:
    """names: product + category names (targets). descriptions: only protect words."""
    counts = Counter()
    for name in names:
        counts.update(set(w for w in words_in(name) if w.isalpha() and len(w) >= 3))
    for word in COMMON_WORDS:
        counts[word] += 1
    known = set(counts)
    for description in descriptions:
        known.update(words_in(description))
    return Vocabulary(counts, frozenset(known))


def min_score(word: str) -> float | None:
    """Similarity needed to correct a word of this length (None = never correct).

    With fuzz.ratio, ONE missing/extra letter scores 88.9 for a 4-letter word, 90.9
    for 5, 92.3 for 6; ONE changed letter scores 75 / 80 / 83.3. So:
    - 4-6 letters: 85 -> a missing or extra letter is fixed ("sirt", "hodie"), but a
      changed letter is not ("warm" stays "warm", "gamer" doesn't become "games").
    - 7+ letters: 80 -> long words also allow one changed letter ("keybord").
    """
    if len(word) <= 3:
        return None
    return 85 if len(word) <= 6 else 80


def correct_word(word: str, vocabulary: Vocabulary) -> str:
    """The corrected spelling of one lower-case word (or the word itself)."""
    threshold = min_score(word)
    if (threshold is None or word in vocabulary.known_words or not word.isalpha()
            or _is_plural_of_known(word, vocabulary)):
        return word
    same_first_letter = [w for w in vocabulary.words if w[0] == word[0]]
    matches = process.extract(word, same_first_letter, scorer=fuzz.ratio,
                              score_cutoff=threshold, limit=5)
    if not matches:
        return word
    # Highest score wins; on a tie, the word used in more product names.
    best, _score, _index = max(matches, key=lambda m: (m[1], vocabulary.words[m[0]]))
    return best


def _is_plural_of_known(word: str, vocabulary: Vocabulary) -> bool:
    return any(word.endswith(suffix) and word[:-len(suffix)] in vocabulary.known_words
               for suffix in ("s", "es"))


def correct_query(query: str, vocabulary: Vocabulary) -> Correction:
    """Correct each word of the query; everything else (spaces, order) is kept."""
    changes = []

    def fix(match: re.Match) -> str:
        word = match.group(0)
        corrected = correct_word(word, vocabulary)
        if corrected != word:
            changes.append((word, corrected))
        return corrected

    corrected = WORD_RE.sub(fix, query.lower().strip())
    if not changes:
        return Correction(query, query, ())
    return Correction(query, corrected, tuple(changes))
