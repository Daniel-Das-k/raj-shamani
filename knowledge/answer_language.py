"""Small language checks for generated video-library replies."""
import re

def question_language(question):
    letters = [c for c in question if c.isalpha()]
    for name, lo, hi in [('Tamil', '\u0b80', '\u0bff'), ('Hindi', '\u0900', '\u097f')]:
        if sum(lo <= c <= hi for c in letters) > .25 * max(1, len(letters)):
            return name
    words = set(re.findall(r"\w+", question.lower()))
    if len(words & {'kya', 'kaise', 'kaunsa', 'kaunsi', 'hai', 'hain', 'mein', 'mujhe', 'mera', 'karein', 'liye'}) >= 2:
        return 'Hinglish'
    return 'English' if all(ord(c) < 128 for c in letters) else 'the question’s language'


def language_matches(text, language):
    letters = [c for c in text if c.isalpha()]
    ranges = {'Tamil': ('\u0b80', '\u0bff'), 'Hindi': ('\u0900', '\u097f')}
    if language in ranges:
        lo, hi = ranges[language]
        return sum(lo <= c <= hi for c in letters) >= .25 * max(1, len(letters))
    if language == 'Hinglish':
        return bool(set(re.findall(r'\w+', text.lower())) &
                    {'hai', 'hain', 'ka', 'ki', 'ke', 'ko', 'mein', 'se', 'aur', 'aap', 'kar', 'karein', 'liye', 'nahi', 'hota'})
    return True
