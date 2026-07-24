import re

_RAW = [
    '씨발', '시발', '병신', '새끼', '개새끼', '존나', '좆', '보지', '니미',
    'fuck', 'shit', 'bitch', 'asshole', 'bastard', 'damn', 'crap',
]

_PATTERNS = [re.compile(re.escape(w), re.IGNORECASE) for w in _RAW]


def contains_profanity(text: str) -> bool:
    for p in _PATTERNS:
        if p.search(text):
            return True
    return False


def censor(text: str) -> str:
    """Replace profanity with * (same length)."""
    for p in _PATTERNS:
        text = p.sub(lambda m: '*' * len(m.group()), text)
    return text


# Banned product keywords — triggers admin review
_BANNED_PRODUCT_KEYWORDS = [
    '마약', '총기', '폭탄', '음란', '불법복제', '도박',
    'drug', 'gun', 'bomb', 'porn', 'piracy',
]
_BAN_PATTERNS = [re.compile(re.escape(w), re.IGNORECASE) for w in _BANNED_PRODUCT_KEYWORDS]


def has_banned_keyword(text: str) -> bool:
    for p in _BAN_PATTERNS:
        if p.search(text):
            return True
    return False
