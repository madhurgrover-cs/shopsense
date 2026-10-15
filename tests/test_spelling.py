"""Unit tests for spelling correction (no database: the vocabulary is built from a
fixed list of names like the seeded catalog's)."""

import pytest

from app.ai import spelling

NAMES = [
    "UrbanWeave Men's Polo T-Shirt", "Basics Co Women's V-Neck T-Shirt",
    "UrbanWeave Unisex Fleece Hoodie", "Trekline Men's Zip-Up Hoodie",
    "Orbitron AirBook 14 (i5/16GB/512GB) Laptop", "UrbanCarry Anti-Theft Backpack Laptop Bag",
    "ClickPro K87 TKL Red Switch Mechanical Keyboard", "Kairo Silent M1 Wireless Mouse",
    "Kairo Gamer X 15 (Ryzen 7/RTX 4060) Laptop", "FlexFit Anti-Slip Yoga Mat",
    "AeroRun Men's Running Shoes", "Botanica Onion Hair Oil",
    # categories
    "Clothing", "Laptops & Computer Accessories", "Sports & Fitness",
]
DESCRIPTIONS = ["A soft fleece hoodie that keeps you warm on cold winter mornings.",
                "Lightweight and breathable for everyday wear."]


@pytest.fixture(scope="module")
def vocabulary():
    return spelling.build_vocabulary(NAMES, DESCRIPTIONS)


@pytest.mark.parametrize("typed, expected", [
    ("sirt", "shirt"),         # missing letter
    ("shrt", "shirt"),
    ("hodie", "hoodie"),
    ("laptp", "laptop"),
    ("keybord", "keyboard"),
    ("SIRT", "shirt"),         # case doesn't matter
    ("blue sirt", "blue shirt"),         # only the typo changes
    ("hodie for running", "hoodie for running"),
])
def test_typos_are_corrected(vocabulary, typed, expected):
    correction = spelling.correct_query(typed, vocabulary)
    assert correction.corrected == expected
    assert correction.changed


@pytest.mark.parametrize("query", [
    "shirt", "hoodie", "laptop", "keyboard", "yoga mat",       # in product names
    "warm winter wear", "cold mornings",                      # in descriptions
    "gift for a gamer", "running shoes", "wireless mouse",
    "shirts", "laptops", "hoodies",                           # plurals of known words
    "coffee", "chair", "warm", "gamer", "pets",               # real words the shop lacks
])
def test_normal_words_are_not_changed(vocabulary, query):
    correction = spelling.correct_query(query, vocabulary)
    assert correction.corrected == query and not correction.changed


@pytest.mark.parametrize("query", ["asdfgh qwerty", "xkcdqz", "zzzz", "blorptang wuzzle"])
def test_gibberish_is_not_corrected(vocabulary, query):
    assert not spelling.correct_query(query, vocabulary).changed


def test_short_words_and_numbers_are_never_corrected(vocabulary):
    # 3 letters or fewer: one wrong letter is too much of the word to guess.
    assert spelling.correct_word("mta", vocabulary) == "mta"
    assert spelling.correct_word("bg", vocabulary) == "bg"
    # Model numbers / sizes contain digits.
    assert spelling.correct_word("k87x", vocabulary) == "k87x"
    assert spelling.correct_word("512gb", vocabulary) == "512gb"


def test_short_words_need_a_stricter_match(vocabulary):
    assert spelling.min_score("mat") is None
    assert spelling.min_score("sirt") > spelling.min_score("keybord")
    # An extra letter is fixed. One CHANGED letter scores 83.3 in a 6-letter word (below
    # its 85 threshold) but 87.5 in an 8-letter word (above its 80 threshold).
    assert spelling.correct_word("hooddie", vocabulary) == "hoodie"
    assert spelling.correct_word("lapkop", vocabulary) == "lapkop"
    assert spelling.correct_word("keyboerd", vocabulary) == "keyboard"  # 8 letters, 1 changed


def test_first_letter_must_match(vocabulary):
    # "chair" is one letter away from "hair", but people rarely mistype the first letter.
    assert spelling.correct_word("chair", vocabulary) == "chair"
    assert spelling.correct_word("hirt", vocabulary) == "hirt"


def test_ties_prefer_the_word_in_more_product_names():
    vocabulary = spelling.build_vocabulary(
        ["Cotton Shirt", "Linen Shirt", "Denim Skirt"])  # "shirt" in 2 names, "skirt" in 1
    assert spelling.correct_word("sirt", vocabulary) == "shirt"


def test_correction_keeps_the_original_query(vocabulary):
    correction = spelling.correct_query("  Hodie ", vocabulary)
    assert correction.original == "  Hodie "
    assert correction.corrected == "hoodie"
    assert correction.changes == (("hodie", "hoodie"),)
    unchanged = spelling.correct_query("Hoodie", vocabulary)
    assert unchanged.corrected == "Hoodie"  # untouched, not even lower-cased


def test_common_product_words_are_targets_without_any_product():
    vocabulary = spelling.build_vocabulary([])
    assert spelling.correct_word("sneekers", vocabulary) == "sneakers"
