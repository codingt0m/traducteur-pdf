"""Effacement ciblé du texte source et écriture du texte traduit."""

from __future__ import annotations

import pymupdf

from .layout import ParaLayout
from .model import Frame, Paragraph

R = 0.3  # demi-côté des micro-rectangles de redaction (pt)


def _center(bbox) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def redact_paragraphs(page: pymupdf.Page, paras: list[Paragraph]) -> int:
    """Retire uniquement les glyphes des paragraphes traduits.

    Chaque rectangle de redaction est une fine bande qui relie le centre du
    premier et du dernier glyphe d'un segment : il ne touche jamais les glyphes
    voisins, et les images / tracés vectoriels sont explicitement préservés."""
    n = 0
    for para in paras:
        axis = abs(para.dir[0]) > 0.999 or abs(para.dir[1]) > 0.999
        for line in para.lines:
            glyphs = [c for c in line.body if not c.is_space]
            if not glyphs:
                continue
            if not axis:  # texte incliné : un rectangle par glyphe
                for c in glyphs:
                    x, y = _center(c.bbox)
                    page.add_redact_annot(pymupdf.Rect(x - R, y - R, x + R, y + R), fill=False)
                    n += 1
                continue
            fr = Frame(glyphs[0].origin, line.dir)
            seg = [glyphs[0]]
            for c in glyphs[1:] + [None]:
                if (
                    c is not None
                    and abs(fr.perp(c.origin) - fr.perp(seg[-1].origin)) < 0.5
                    and c.style == seg[-1].style
                ):
                    seg.append(c)
                    continue
                x0, y0 = _center(seg[0].bbox)
                x1, y1 = _center(seg[-1].bbox)
                rect = pymupdf.Rect(min(x0, x1) - R, min(y0, y1) - R, max(x0, x1) + R, max(y0, y1) + R)
                page.add_redact_annot(rect, fill=False)
                n += 1
                if c is not None:
                    seg = [c]
    if n:
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
    # Soulignements d'origine (traits vectoriels) : retirés uniquement s'ils sont
    # entièrement couverts, pour être redessinés sous le texte traduit.
    ul = [r for para in paras for r in para.underlines]
    for r in ul:
        page.add_redact_annot(pymupdf.Rect(r.x0 - 0.3, r.y0 - 0.3, r.x1 + 0.3, r.y1 + 0.3), fill=False)
    if ul:
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
            text=pymupdf.PDF_REDACT_TEXT_NONE,
        )
    return n


def write_layout(page: pymupdf.Page, lay: ParaLayout) -> None:
    """Écrit les morceaux d'un paragraphe : un TextWriter par couleur.

    La transformation (rotation + compression) est appliquée autour d'un point
    fixe F : p' = F + (p - F)·M. On ajoute donc chaque morceau au point
    F + (P - F)·M⁻¹ pour qu'il atterrisse exactement en P."""
    chunks = [c for c in lay.chunks if c.text.strip()]
    if not chunks:
        return
    m = lay.matrix
    identity = abs(m.a - 1) < 1e-9 and abs(m.d - 1) < 1e-9 and abs(m.b) < 1e-9 and abs(m.c) < 1e-9
    # 'morph' agit dans le repère PDF (axe y inversé) : l'effet réel en
    # coordonnées de page est F·M·F avec F = diag(1, -1).
    inv = ~pymupdf.Matrix(m.a, -m.b, -m.c, m.d, 0, 0)
    by_color: dict[tuple, list] = {}
    for c in chunks:
        by_color.setdefault((c.color, c.alpha), []).append(c)
    for (color, alpha), group in by_color.items():
        opacity = alpha / 255.0
        fix = pymupdf.Point(group[0].point)
        tw = pymupdf.TextWriter(page.rect)
        for c in group:
            pt = c.point if identity else fix + (c.point - fix) * inv
            tw.append(pt, c.text, font=c.font, fontsize=c.size)
        if identity:
            tw.write_text(page, color=color, opacity=opacity)
        else:
            tw.write_text(page, color=color, opacity=opacity, morph=(fix, m))

    _draw_underlines(page, lay, chunks)


def _draw_underlines(page: pymupdf.Page, lay: ParaLayout, chunks: list) -> None:
    """Redessine les soulignements : un trait continu par suite de mots soulignés
    consécutifs sur une même ligne (espaces inter-mots comprises)."""
    fr = lay.frame
    runs: list[list] = []  # [style_soulignement, perp, début, fin]
    for c in chunks:
        if not c.underline:
            continue
        a0 = fr.along(c.point)
        a1 = a0 + c.font.text_length(c.text, fontsize=c.size) * lay.hscale
        q = fr.perp(c.point)
        last = runs[-1] if runs else None
        if last and last[0] == c.underline and abs(last[1] - q) < 0.01 and 0 <= a0 - last[3] <= 0.6 * c.size:
            last[3] = a1
        else:
            runs.append([c.underline, q, a0, a1])
    for (off, thick, col), q, a0, a1 in runs:
        page.draw_line(fr.point(a0, q + off), fr.point(a1, q + off), color=col, width=thick)
