"""Encodage d'un paragraphe en texte à traduire, et décodage de la traduction.

- Les mots dont le style diffère du style principal (gras, couleur...) sont
  entourés de balises <bN>...</bN> que le traducteur conserve et replace.
- Les éléments à ne pas traduire (formules, symboles, URL, e-mails, code) sont
  remplacés par des marqueurs ⟦N⟧ et seront recopiés glyphe par glyphe, avec
  leur police et leur position relative d'origine.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .model import Char, Frame, Paragraph, Style

PROTECTED_FONTS = (
    "math",
    "symbol",
    "wingding",
    "dingbat",
    "mono",
    "courier",
    "consola",
    "menlo",
    "code",
    "cmsy",
    "cmmi",
    "cmex",
)
PROTECTED_PATTERNS = re.compile(
    r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|[<>⟦⟧]+",
    re.UNICODE,
)
LETTERS = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
TAG_RE = re.compile(r"<\s*(/?)\s*b\s*(\d+)\s*>", re.IGNORECASE)
PH_RE = re.compile(r"⟦\s*(\d+)\s*⟧")


def _is_math_char(c: str) -> bool:
    cp = ord(c)
    return (
        0x1D400 <= cp <= 0x1D7FF  # lettres mathématiques
        or 0x2190 <= cp <= 0x21FF  # flèches
        or 0x2200 <= cp <= 0x22FF  # opérateurs
        or 0x27C0 <= cp <= 0x27FF
        or 0x2980 <= cp <= 0x2AFF
        or 0xE000 <= cp <= 0xF8FF  # zone privée (polices symboles)
    )


def is_protected_style(style: Style) -> bool:
    n = style.font.lower()
    return any(k in n for k in PROTECTED_FONTS)


@dataclass
class Placeholder:
    chars: list[Char]
    line_idx: int
    rise: float  # décalage perpendiculaire du 1er glyphe / ligne de base
    offsets: list[tuple[float, float]]  # (along, perp) de chaque glyphe / 1er glyphe
    width: float


@dataclass
class Encoded:
    para: Paragraph
    text: str
    base: Style
    tag_styles: dict[int, Style] = field(default_factory=dict)
    placeholders: list[Placeholder] = field(default_factory=list)

    @property
    def translatable(self) -> bool:
        plain = PH_RE.sub(" ", TAG_RE.sub("", self.text))
        return bool(LETTERS.search(plain))


@dataclass
class _Run:
    kind: str  # "text" | "prot"
    style: Style
    chars: list[Char]

    @property
    def s(self) -> str:
        return "".join(c.c for c in self.chars)


def _runs_for_line(chars: list[Char]) -> list[_Run]:
    runs: list[_Run] = []
    for ch in chars:
        if ch.is_space and runs:
            runs[-1].chars.append(ch)
            continue
        kind = "prot" if is_protected_style(ch.style) or _is_math_char(ch.c) else "text"
        if runs and runs[-1].kind == kind and runs[-1].style == ch.style:
            runs[-1].chars.append(ch)
        else:
            runs.append(_Run(kind, ch.style, [ch]))
    # Motifs protégés (URL, e-mail, chevrons) à l'intérieur des runs de texte
    out: list[_Run] = []
    for r in runs:
        if r.kind != "text":
            out.append(r)
            continue
        s, pos = r.s, 0
        for m in PROTECTED_PATTERNS.finditer(s):
            if m.start() > pos:
                out.append(_Run("text", r.style, r.chars[pos : m.start()]))
            out.append(_Run("prot", r.style, r.chars[m.start() : m.end()]))
            pos = m.end()
        if pos < len(s):
            out.append(_Run("text", r.style, r.chars[pos:]))
    return out


def _baseline(frame: Frame, chars: list[Char]) -> float:
    vals = Counter(round(frame.perp(c.origin) * 2) / 2 for c in chars if not c.is_space and not _is_math_char(c.c))
    return vals.most_common(1)[0][0] if vals else 0.0


def _make_placeholder(chars: list[Char], line_idx: int, frame: Frame, baseline: float) -> Placeholder:
    glyphs = [c for c in chars if not c.is_space]
    first = glyphs[0]
    f0 = Frame(first.origin, frame.d)
    offsets = [(f0.along(c.origin), f0.perp(c.origin)) for c in glyphs]
    width = max(f0.rect_intervals(c.bbox)[1] for c in glyphs)
    rise = frame.perp(first.origin) - baseline
    return Placeholder(glyphs, line_idx, rise, offsets, max(width, 0.0))


def _same_look(a: Style, b: Style) -> bool:
    return a.visual_key() == b.visual_key() and (a.flags & 18) == (b.flags & 18)


def encode(para: Paragraph) -> Encoded:
    all_runs: list[list[_Run]] = []
    for line in para.lines:
        body = list(line.body)
        while body and body[-1].is_space:
            body.pop()
        all_runs.append(_runs_for_line(body))

    counts: Counter[Style] = Counter()
    for runs in all_runs:
        for r in runs:
            if r.kind == "text":
                counts[r.style] += sum(1 for c in r.chars if not c.is_space)
    base = counts.most_common(1)[0][0] if counts else para.lines[0].dominant_style()
    enc = Encoded(para, "", base)

    line_strs: list[str] = []
    tag_no = 0
    for li, (line, runs) in enumerate(zip(para.lines, all_runs)):
        frame = Frame(line.origin, line.dir)
        baseline = _baseline(frame, [c for r in runs for c in r.chars])
        # Indices / exposants (ligne de base décalée) : recopiés à l'identique
        for r in runs:
            glyph = next((c for c in r.chars if not c.is_space), None)
            if glyph is not None and abs(frame.perp(glyph.origin) - baseline) > 0.12 * glyph.style.size:
                r.kind = "prot"
        parts: list[str] = []
        i = 0
        while i < len(runs):
            r = runs[i]
            if r.kind == "prot" or (not _same_look(r.style, base) and not LETTERS.search(r.s) and r.s.strip()):
                # Groupe de runs protégés consécutifs (espaces intercalaires compris)
                group = list(r.chars)
                j = i + 1
                while j < len(runs):
                    rj = runs[j]
                    if rj.kind == "prot" or not rj.s.strip() and j + 1 < len(runs) and runs[j + 1].kind == "prot":
                        group += rj.chars
                        j += 1
                    else:
                        break
                trailing = group[-1].is_space if group else False
                leading_space = r.chars[0].is_space
                ph = _make_placeholder(group, li, frame, baseline)
                enc.placeholders.append(ph)
                parts.append(
                    (" " if leading_space else "") + f"⟦{len(enc.placeholders) - 1}⟧" + (" " if trailing else "")
                )
                i = j
                continue
            s = r.s
            if _same_look(r.style, base) or not s.strip():
                parts.append(s)
            else:
                tag_no += 1
                enc.tag_styles[tag_no] = r.style
                lead = s[: len(s) - len(s.lstrip())]
                trail = s[len(s.rstrip()) :]
                parts.append(f"{lead}<b{tag_no}>{s.strip()}</b{tag_no}>{trail}")
            i += 1
        line_strs.append(re.sub(r"[  ]+", " ", "".join(parts)).strip())

    text = ""
    for s in line_strs:
        if not s:
            continue
        if not text:
            text = s
        elif re.search(r"[^\W\d_]-$", text) and s[:1].islower():
            text = text[:-1] + s  # césure en fin de ligne
        else:
            text += " " + s
    enc.text = text
    return enc


# ---------------------------------------------------------------------------
# Décodage
# ---------------------------------------------------------------------------


@dataclass
class Token:
    kind: str  # "t" (texte) | "p" (placeholder)
    style: Style | None = None
    text: str = ""
    ph: int = -1


def _restore_spaces(source: str, translated: str) -> str:
    """Les traducteurs suppriment parfois l'espace qui entoure une balise ou un
    marqueur ('clients<b1>durée'). On le rétablit quand la source en avait un."""
    marker = re.compile(r"<\s*/?\s*b\s*\d+\s*>|⟦\s*\d+\s*⟧", re.IGNORECASE)

    def key(m):
        return re.sub(r"\s", "", m.group(0)).lower()

    before, after = set(), set()
    for m in marker.finditer(source):
        k = key(m)
        if m.start() > 0 and source[m.start() - 1] == " ":
            before.add(k)
        if m.end() < len(source) and source[m.end()] == " ":
            after.add(k)
    no_space_after = set("([{«\"'’/-")  # pas d'espace après une ouverture
    no_space_before = set(".,;:!?)]}»\"'’/-")  # ni avant une ponctuation fermante
    out = ""
    pos = 0
    for m in marker.finditer(translated):
        k = key(m)
        out += translated[pos : m.start()]
        if k in before and out and not out[-1].isspace() and out[-1] not in no_space_after:
            out += " "
        out += m.group(0)
        pos = m.end()
        nxt = translated[pos : pos + 1]
        if k in after and nxt and not nxt.isspace() and nxt not in no_space_before:
            out += " "
    return out + translated[pos:]


def decode(enc: Encoded, translated: str) -> list[Token] | None:
    """Transforme la traduction en jetons stylés. None si les marqueurs sont abîmés."""
    translated = _restore_spaces(enc.text, translated)
    found = [int(m.group(1)) for m in PH_RE.finditer(translated)]
    if sorted(found) != list(range(len(enc.placeholders))):
        return None
    tokens: list[Token] = []
    stack: list[Style] = []
    pos = 0
    pattern = re.compile(f"{TAG_RE.pattern}|{PH_RE.pattern}", re.IGNORECASE)
    for m in pattern.finditer(translated):
        if m.start() > pos:
            tokens.append(Token("t", stack[-1] if stack else enc.base, translated[pos : m.start()]))
        if m.group(3) is not None:  # placeholder
            tokens.append(Token("p", ph=int(m.group(3))))
        else:
            closing, num = m.group(1) == "/", int(m.group(2))
            style = enc.tag_styles.get(num)
            if style is not None:
                if closing:
                    if stack:
                        stack.pop()
                else:
                    stack.append(style)
        pos = m.end()
    if pos < len(translated):
        tokens.append(Token("t", stack[-1] if stack else enc.base, translated[pos:]))
    return tokens
