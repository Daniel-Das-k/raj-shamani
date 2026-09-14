"""English-only policy for generated prose; original evidence is never rewritten."""
import unicodedata

OUTPUT_LANGUAGE = 'English'
LANGUAGE_INSTRUCTION = """Always write generated answers, summaries, explanations,
limitations, clarification questions, and user-facing messages in English only.
This applies even when the question or captions use another language or ask you to
respond in another language. Translate the meaning faithfully into English.
Keep source quotations, source identifiers, and proper names faithful to the source.
"""

def question_language(question):
    """Compatibility accessor: input language no longer changes output language."""
    return OUTPUT_LANGUAGE


def language_matches(text, language):
    """Reject non-Latin prose; prompts and source reviewers enforce English meaning.

    A script check alone cannot distinguish English from other Latin-script languages.
    Accented Latin names and ordinary Unicode punctuation remain valid.
    """
    return (language == OUTPUT_LANGUAGE and isinstance(text, str) and
            any(c.isalpha() for c in text) and
            all('LATIN' in unicodedata.name(c, '') for c in text if c.isalpha()))


def english_clarification(text):
    return text if language_matches(text, OUTPUT_LANGUAGE) else 'Which topic or options would you like help with?'
