"""Matches spoken utterances against the fixed confirm/cancel vocabulary used
to resolve approvals during hands-free voice sessions.

Design note: this is deliberately conservative. A misheard "yes" approving a
`restart_service` or `execute_command` call is a much worse failure mode than
making the user repeat themselves, so we do NOT do loose keyword-contains
matching against natural language ("yeah I guess that's fine" does not
count). We only accept an utterance that IS - once trimmed of filler words -
one of the configured confirm/cancel words. This also means a stray mention
of the word "confirm" in an unrelated sentence ("can you confirm what OS
we're running") won't be misread as an approval, because the rest of the
sentence doesn't reduce down to just the confirm word.
"""

import re
import string
from typing import Literal, Optional

# Filler words we strip before comparing, so "yeah confirm" or "okay cancel
# that" still match cleanly without opening the door to arbitrary sentences.
_FILLER_WORDS = {
    "yes", "yeah", "yep", "sure", "ok", "okay", "please", "go", "ahead",
    "do", "it", "that", "molly", "um", "uh",
}

_MAX_UTTERANCE_TOKENS = 6


def _normalize(text: str) -> list[str]:
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return [t for t in text.split() if t]


def parse_voice_choice(transcript: str, options: list[str]) -> Optional[list[str]]:
    """Match a spoken answer to one or more of a question's option labels.

    Unlike parse_voice_decision's fixed two-word vocabulary, option labels
    are arbitrary strings, so this compares normalized tokens: an utterance
    resolves to an option if, after stripping filler words, what's left is a
    superset of that option's own tokens and isn't ambiguous with another
    option's tokens. "and"/"," lets a multi-select answer name more than
    one option in a single utterance (e.g. "coffee and tea").
    """
    said = _normalize(transcript)
    said_meaningful = [t for t in said if t not in _FILLER_WORDS and t not in ("and",)]
    if not said_meaningful:
        return None

    matches = []
    for option in options:
        opt_tokens = set(_normalize(option))
        if opt_tokens and opt_tokens.issubset(set(said_meaningful)):
            matches.append(option)

    return matches or None


def parse_voice_decision(
    transcript: str,
    confirm_words: list[str],
    cancel_words: list[str],
) -> Optional[Literal["approve", "reject"]]:
    """Return "approve", "reject", or None if the utterance doesn't cleanly
    resolve to one of the configured confirm/cancel words.

    `transcript` should be a single finalized user utterance (one turn of
    input transcription), not a running buffer of the whole conversation.
    """
    tokens = _normalize(transcript)
    if not tokens or len(tokens) > _MAX_UTTERANCE_TOKENS:
        return None

    meaningful = [t for t in tokens if t not in _FILLER_WORDS]
    if len(meaningful) != 1:
        # Either nothing left after stripping filler, or more than one
        # substantive word - too ambiguous to treat as a bare confirmation.
        return None

    word = meaningful[0]
    if word in confirm_words:
        return "approve"
    if word in cancel_words:
        return "reject"
    return None
