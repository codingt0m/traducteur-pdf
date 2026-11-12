"""Traitements communs à tous les moteurs, avant et après la traduction."""

from __future__ import annotations

import re

from .encoding import PH_RE, TAG_RE, Encoded

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
FR_WORDS = {
    "le",
    "la",
    "les",
    "des",
    "du",
    "de",
    "et",
    "est",
    "une",
    "un",
    "pour",
    "dans",
    "sur",
    "avec",
    "par",
    "que",
    "qui",
    "pas",
    "au",
    "aux",
    "ce",
    "cette",
    "sont",
    "ou",
    "en",
    "nous",
    "vous",
    "il",
    "elle",
    "mais",
}
EN_WORDS = {
    "the",
    "and",
    "is",
    "of",
    "to",
    "in",
    "for",
    "with",
    "on",
    "that",
    "are",
    "by",
    "this",
    "be",
    "as",
    "an",
    "or",
    "not",
    "from",
    "it",
    "can",
    "we",
    "if",
    "at",
    "which",
    "each",
    "all",
    "has",
    "have",
}


def plain(text: str) -> str:
    return PH_RE.sub(" ", TAG_RE.sub("", text))


def looks_like(text: str, target: str) -> bool:
    """Le segment est-il déjà dans la langue cible ? (heuristique pour fr/en ;
    pour les autres langues on laisse le traducteur en décider)."""
    if target == "fr":
        return looks_french(text)
    if target == "en":
        words = [w.lower() for w in _WORD.findall(plain(text))]
        en = sum(w in EN_WORDS for w in words)
        fr = sum(w in FR_WORDS for w in words) + sum(1 for w in words if re.search(r"[éèêàùâîôûç]", w))
        return en >= 2 and en > 2 * fr
    return False


def looks_french(text: str) -> bool:
    """Heuristique légère : le segment est-il déjà en français ?"""
    words = [w.lower() for w in _WORD.findall(plain(text))]
    if not words:
        return False
    fr = sum(w in FR_WORDS for w in words) + sum(1 for w in words if re.search(r"[éèêàùâîôûç]", w))
    en = sum(w in EN_WORDS for w in words)
    return (fr >= 2 and fr > 2 * en) or (
        fr >= 1 and en == 0 and len(words) <= 3 and re.search(r"[éèêàùç]", text) is not None
    )


def fix_punctuation(source: str, translated: str) -> str:
    """Retire le point final ajouté par le traducteur quand la source n'en avait pas."""
    if translated is None:
        return translated
    if not re.search(r"[.!?:;…]\s*(</b\d+>)?\s*$", plain(source).rstrip() or " ") and re.search(
        r"(?<!\.)\.\s*$", translated
    ):
        translated = re.sub(r"\.\s*$", "", translated)
    return translated


def missing_tags(enc: Encoded, translated: str) -> list[int]:
    found = {int(m.group(2)) for m in TAG_RE.finditer(translated) if m.group(1) == ""}
    return sorted(set(enc.tag_styles) - found)


def tag_inner(enc: Encoded, n: int) -> str | None:
    m = re.search(rf"<b{n}>(.*?)</b{n}>", enc.text)
    return m.group(1).strip() if m else None


def insert_tag(translated: str, n: int, candidates: list[str]) -> tuple[str, bool]:
    """Ré-applique le style n sur le premier candidat retrouvé dans la traduction."""
    cleaned = re.sub(rf"<\s*/?\s*b\s*{n}\s*>", "", translated, flags=re.I)
    low = cleaned.lower().replace("’", "'")
    for cand in candidates:
        c = (cand or "").strip().rstrip(".").lower().replace("’", "'")
        if len(c) < 2:
            continue
        i = low.find(c)
        if i >= 0:
            j = i + len(c)
            return cleaned[:i] + f"<b{n}>" + cleaned[i:j] + f"</b{n}>" + cleaned[j:], True
    return cleaned, False
