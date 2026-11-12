"""Extraction du texte (caractère par caractère) et regroupement en paragraphes."""

from __future__ import annotations

import math
from dataclasses import replace

import pymupdf

from .model import Char, Frame, Line, PageData, Paragraph, Style, clean_font_name, family_key

TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP

BULLETS = set("•◦▪▫■□●○◆◇►▸▹▶➢➤➣➔→✓✔✗–—-*·∙‣⁃")
BULLET_FONTS = ("wingding", "symbol", "dingbat", "webding", "zapf")
TERMINAL = ".!?:;"


def _font_xrefs(page: pymupdf.Page) -> dict[str, int]:
    out = {}
    for xref, _ext, _typ, basefont, _name, _enc in [f[:6] for f in page.get_fonts(full=False)]:
        out[clean_font_name(basefont)] = xref
    return out


def _lookup_xref(fontname: str, xrefs: dict[str, int]) -> int:
    name = clean_font_name(fontname)
    if name in xrefs:
        return xrefs[name]
    for k, v in xrefs.items():  # noms de spans parfois tronqués
        if k.startswith(name) or name.startswith(k):
            return v
    return 0


def _is_bullet(ch: Char) -> bool:
    if ch.c in BULLETS:
        return True
    cp = ord(ch.c)
    if 0xE000 <= cp <= 0xF8FF:  # zone privée : puces Wingdings/Symbol
        return True
    return any(k in ch.style.font.lower() for k in BULLET_FONTS)


def _bullet_prefix(chars: list[Char]) -> int:
    """Longueur du préfixe 'puce + espaces' à conserver tel quel."""
    i = 0
    while i < len(chars) and chars[i].is_space:
        i += 1
    if i >= len(chars) or not _is_bullet(chars[i]):
        return 0
    j = i + 1
    if j < len(chars) and not chars[j].is_space and chars[i].c in "-–—*":
        return 0  # tiret collé à un mot : pas une puce
    while j < len(chars) and chars[j].is_space:
        j += 1
    return j if j < len(chars) else 0


def _synthesize_spaces(chars: list[Char], direction) -> list[Char]:
    """Certains PDF espacent les mots par positionnement, sans caractère espace :
    on insère un espace virtuel quand l'écart entre deux glyphes est large."""
    fr = Frame(chars[0].origin, direction)
    out = [chars[0]]
    for prev, cur in zip(chars, chars[1:]):
        if not prev.is_space and not cur.is_space:
            _, pe, _, _ = fr.rect_intervals(prev.bbox)
            cs, _, _, _ = fr.rect_intervals(cur.bbox)
            size = max(prev.style.size, cur.style.size)
            if cs - pe > 0.10 * size:
                pt = fr.point(pe, fr.perp(prev.origin))
                out.append(Char(" ", (pt.x, pt.y), (pt.x, pt.y, pt.x, pt.y), prev.style))
        out.append(cur)
    return out


def extract_lines(page: pymupdf.Page) -> list[Line]:
    xrefs = _font_xrefs(page)
    lines: list[Line] = []
    raw = page.get_text("rawdict", flags=TEXT_FLAGS)
    for bno, block in enumerate(raw["blocks"]):
        if block.get("type") != 0:
            continue
        for raw_line in block["lines"]:
            dx, dy = raw_line["dir"]
            norm = math.hypot(dx, dy) or 1.0
            direction = (dx / norm, dy / norm)
            # Une ligne peut être coupée en segments : un glyphe invisible au
            # milieu d'une ligne visible signale un objet graphique en ligne
            # (symbole dessiné en vectoriel) qui ne bougera pas ; le texte de
            # part et d'autre est alors traité séparément.
            segments: list[list[Char]] = [[]]
            for s in raw_line["spans"]:
                alpha = int(s.get("alpha", 255))
                cflags = s.get("char_flags")
                # Texte invisible (opacité nulle ou mode de rendu 3 : ni rempli ni
                # tracé) : calque d'accessibilité/OCR, laissé intact.
                if alpha == 0 or (cflags is not None and not cflags & (16 | 32)):
                    if any(not c["c"].isspace() for c in s["chars"]) and segments[-1]:
                        segments.append([])
                    continue
                style = Style(s["font"], s["size"], s["color"], s["flags"], _lookup_xref(s["font"], xrefs), alpha=alpha)
                for c in s["chars"]:
                    segments[-1].append(Char(c["c"], tuple(c["origin"]), tuple(c["bbox"]), style))
            for chars in segments:
                if not chars or all(c.is_space for c in chars):
                    continue
                chars = _synthesize_spaces(chars, direction)
                bbox = pymupdf.Rect(
                    min(c.bbox[0] for c in chars),
                    min(c.bbox[1] for c in chars),
                    max(c.bbox[2] for c in chars),
                    max(c.bbox[3] for c in chars),
                )
                line = Line(chars, direction, bbox if len(segments) > 1 else pymupdf.Rect(raw_line["bbox"]), bno)
                line.prefix_len = _bullet_prefix(chars)
                lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Regroupement en paragraphes
# ---------------------------------------------------------------------------


def _extent(line: Line, frame_origin, direction) -> tuple[float, float]:

    fr = Frame(frame_origin, direction)
    vals = []
    for ch in line.body:
        if ch.is_space:
            continue
        a0, a1, _, _ = fr.rect_intervals(ch.bbox)
        vals += [a0, a1]
    if not vals:
        return 0.0, 0.0
    return min(vals), max(vals)


def _first_letter(text: str) -> str:
    for c in text.strip():
        return c
    return ""


def _can_merge(para: list[Line], nxt: Line) -> bool:

    prev = para[-1]
    if nxt.prefix_len:  # nouvelle puce = nouveau paragraphe
        return False
    d1, d2 = prev.dir, nxt.dir
    if d1[0] * d2[0] + d1[1] * d2[1] < 0.999:
        return False
    s1, s2 = prev.dominant_style(), nxt.dominant_style()
    if family_key(s1.font) != family_key(s2.font) or s1.color != s2.color:
        return False
    size = max(s1.size, s2.size)
    if abs(s1.size - s2.size) > 0.05 * size + 0.1:
        return False

    fr = Frame(prev.origin, prev.dir)
    gap = fr.perp(nxt.origin)
    if not (0.6 * size <= gap <= 1.9 * size):
        return False
    if len(para) >= 2:
        prev_gap = Frame(para[-2].origin, prev.dir).perp(prev.origin)
        if abs(gap - prev_gap) > 0.3 * size:
            return False

    a0, a1 = _extent(prev, prev.origin, prev.dir)
    b0, b1 = _extent(nxt, prev.origin, prev.dir)
    tol = 0.8 * size
    aligned = abs(a0 - b0) <= tol or abs((a0 + a1) / 2 - (b0 + b1) / 2) <= tol or abs(a1 - b1) <= tol
    if not aligned:
        return False

    prev_text = prev.body_text.rstrip()
    first = _first_letter(nxt.body_text)
    if not prev_text or not first:
        return False
    last = prev_text[-1]
    if first.islower() or first.isdigit() or first in "([{«\"'":
        return True
    if last in ",;-–(/&+":
        return True
    # Ligne précédente non terminée et même bloc d'origine : continuation probable
    if prev.block == nxt.block and last not in TERMINAL:
        return True
    # Ligne pleine qui se termine par un mot en minuscules ("... solution to the")
    # suivie d'une ligne alignée : retour à la ligne automatique.
    words = prev_text.split()
    full = (a1 - a0) >= 0.7 * max(a1 - a0, b1 - b0)
    return bool(words) and words[-1][:1].islower() and full and len(words) >= 3


def group_paragraphs(lines: list[Line], page_no: int) -> list[Paragraph]:
    paras: list[Paragraph] = []
    current: list[Line] = []
    for line in lines:
        if current and _can_merge(current, line):
            current.append(line)
        else:
            if current:
                paras.append(Paragraph(current, page_no))
            current = [line]
    if current:
        paras.append(Paragraph(current, page_no))
    for i, p in enumerate(paras):
        p.index = i
    return paras


def _attach_underlines(lines: list[Line], drawings: list[dict]) -> set[int]:
    """Repère les traits fins tracés juste sous la ligne de base (soulignements
    vectoriels) et les rattache aux caractères concernés, sous forme d'attribut
    de style. Retourne les indices des tracés utilisés."""
    used: set[int] = set()
    for di, dr in enumerate(drawings):
        r = pymupdf.Rect(dr["rect"])
        if r.width < 2 and r.height < 2:
            continue
        thin = min(r.width, r.height)
        if thin > 3:
            continue
        for line in lines:
            size = line.dominant_style().size
            fr = Frame(line.origin, line.dir)
            a0, a1, q0, q1 = fr.rect_intervals(r)
            if a1 - a0 < 2 or (q1 - q0) > max(0.15 * size, 1.5):
                continue
            mid = (q0 + q1) / 2
            if not (-0.05 * size <= mid <= 0.4 * size):
                continue
            covered = []
            for k, ch in enumerate(line.chars):
                if k < line.prefix_len or ch.is_space:
                    continue
                ca0, ca1, _, _ = fr.rect_intervals(ch.bbox)
                if a0 - 0.5 <= (ca0 + ca1) / 2 <= a1 + 0.5 and abs(fr.perp(ch.origin)) < 0.3 * size:
                    covered.append(k)
            if not covered:
                continue
            ca = fr.rect_intervals(line.chars[covered[0]].bbox)[0]
            cb = fr.rect_intervals(line.chars[covered[-1]].bbox)[1]
            if a0 < ca - 1.0 * size or a1 > cb + 1.0 * size:
                continue  # filet décoratif plus long que le texte : pas un soulignement
            thickness = max(q1 - q0, float(dr.get("width") or 0.0), 0.4)
            col = dr.get("fill") if dr.get("type", "").startswith("f") and dr.get("fill") else dr.get("color")
            col = tuple(col) if col else line.chars[covered[0]].style.rgb
            for k in range(covered[0], covered[-1] + 1):  # espaces internes compris
                ch = line.chars[k]
                ch.style = replace(ch.style, underline=(round(mid, 2), round(thickness, 2), col))
            line.underlines.append(r)
            used.add(di)
            break
    return used


def extract_page(page: pymupdf.Page) -> PageData:
    """À appeler avec page.rotation == 0 (repère non tourné)."""
    data = PageData(number=page.number, rotation=page.rotation, page_rect=pymupdf.Rect(page.rect))
    lines = extract_lines(page)
    drawings = page.get_drawings()
    used = _attach_underlines(lines, drawings)
    data.paragraphs = group_paragraphs(lines, page.number)
    # Obstacles pour savoir jusqu'où une ligne traduite peut s'étendre
    for pi, para in enumerate(data.paragraphs):
        for line in para.lines:
            data.obstacles.append((pymupdf.Rect(line.bbox), pi))
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"])
        if not r.is_empty:
            data.obstacles.append((r, -1))
    for di, dr in enumerate(drawings):
        r = pymupdf.Rect(dr["rect"])
        if di not in used and (r.width > 0.5 or r.height > 0.5):
            data.obstacles.append((r, -1))
    return data
