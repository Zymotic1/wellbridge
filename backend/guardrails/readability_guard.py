"""
Readability guard — Flesch-Kincaid Grade Level checker.

Pure Python implementation of the FK formula. No external dependencies.
Used by guardrail_node to determine if the response needs a simplification pass.

Formula: FK Grade = 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
Target: grade level <= 6.0 for patient-facing summaries.
"""

import re


def count_syllables(word: str) -> int:
    """
    Heuristic English syllable counter.
    Accurate enough for Flesch-Kincaid scoring; not linguistically perfect.
    """
    word = word.lower().strip(".,!?;:\"'()")
    if not word:
        return 0
    if len(word) <= 3:
        return 1

    # Remove trailing silent 'e'
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]

    # Count vowel groups
    vowel_groups = re.findall(r"[aeiou]+", word)
    syllables = len(vowel_groups)

    # Edge cases
    if word.endswith("le") and len(word) > 2 and word[-3] not in "aeiou":
        syllables += 1
    if word.endswith("ed") and syllables > 1:
        syllables -= 1

    return max(1, syllables)


def check_readability(text: str) -> float:
    """
    Calculate the Flesch-Kincaid Grade Level for the given text.

    Returns a float grade level (e.g., 6.0 = 6th grade).
    Lower is easier to read. Grade 6 is accessible to most adults.

    Returns 0.0 for empty or very short text.
    """
    if not text or not text.strip():
        return 0.0

    # Split into sentences
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    num_sentences = len(sentences)

    if num_sentences == 0:
        return 0.0

    # Split into words (letters and apostrophes only)
    words = re.findall(r"\b[a-zA-Z']+\b", text)
    num_words = len(words)

    if num_words == 0:
        return 0.0

    total_syllables = sum(count_syllables(w) for w in words)

    # FK formula
    asl = num_words / num_sentences          # Average sentence length
    asw = total_syllables / num_words        # Average syllables per word
    grade = 0.39 * asl + 11.8 * asw - 15.59

    return round(max(0.0, grade), 2)
