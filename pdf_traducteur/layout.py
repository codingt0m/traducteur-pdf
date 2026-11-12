"""Mise en page de la traduction dans la géométrie d'origine.

Pour chaque paragraphe :
1. on mesure chaque mot traduit avec la police de rendu ;
2. on calcule la largeur disponible de chaque ligne d'origine (zone libre
   jusqu'au prochain obstacle : texte, image, tracé, bord de page) ;
3. on répartit les mots sur EXACTEMENT le même nombre de lignes, en suivant
   au mieux les proportions des lignes d'origine (programmation dynamique) ;
4. si une ligne déborde : compression horizontale (jusqu'à MIN_HSCALE), puis
   réduction uniforme de la taille du paragraphe en dernier recours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from .encoding import Encoded, Placeholder, Token
from .fonts import FontManager
from .languages import is_cjk_char
from .model import Frame, PageData, Paragraph, Style

MIN_HSCALE = 0.85
MIN_SIZE_WARN = 0.7


@dataclass
class Piece:
    kind: str  # "t" | "p"
    width: float
    style: Style | None = None
    text: str = ""
    font: pymupdf.Font | None = None
    ph: Placeholder | None = None


@dataclass
class Word:
    pieces: list[Piece]
    space: float  # largeur de l'espace qui suit

    @property
    def width(self) -> float:
        return sum(p.width for p in self.pieces)


@dataclass
class Chunk:
    """Un morceau de texte à écrire en un seul appel."""

    point: pymupdf.Point
    text: str
    font: pymupdf.Font
    size: float
    color: tuple[float, float, float]
    underline: tuple | None = None  # (décalage, épaisseur, couleur), déjà mis à l'échelle
    alpha: int = 255


@dataclass
class ParaLayout:
    para: Paragraph
    chunks: list[Chunk] = field(default_factory=list)
    matrix: pymupdf.Matrix | None = None
    frame: Frame | None = None
    hscale: float = 1.0
    size_factor: float = 1.0
    ratio: float = 1.0
    align: str = "left"
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mots
# ---------------------------------------------------------------------------


def build_words(tokens: list[Token], enc: Encoded, fm: FontManager) -> list[Word]:
    words: list[list[Piece]] = []
    cur: list[Piece] = []
    glued: set[int] = set()  # mots suivis d'aucune espace (CJK)
    for tok in tokens:
        if tok.kind == "p":
            ph = enc.placeholders[tok.ph]
            cur.append(Piece("p", ph.width, ph=ph))
            continue
        text = tok.text.replace(" ", " ")
        for part in re.split(r"([ \t\r\n]+)", text):
            if not part:
                continue
            if part.strip(" \t\r\n") == "":
                if cur:
                    words.append(cur)
                    cur = []
                continue
            # Écritures sans espaces (CJK) : chaque idéogramme est sécable
            for seg in re.findall(r"[　-ヿ㐀-䶿一-鿿가-힯豈-﫿＀-￯]|[^　-ヿ㐀-䶿一-鿿가-힯豈-﫿＀-￯]+", part):
                font = fm.for_translation(tok.style, seg)
                piece = Piece("t", font.text_length(seg, fontsize=tok.style.size), tok.style, seg, font)
                if is_cjk_char(seg[0]):
                    if cur:
                        words.append(cur)
                        glued.add(len(words) - 1)
                    cur = [piece]
                    words.append(cur)
                    glued.add(len(words) - 1)
                    cur = []
                else:
                    cur.append(piece)
    if cur:
        words.append(cur)
    base_font = fm.for_translation(enc.base, " ")
    space = base_font.text_length(" ", fontsize=enc.base.size)
    return [Word(w, 0.0 if i in glued else space) for i, w in enumerate(words)]


# ---------------------------------------------------------------------------
# Répartition en N lignes
# ---------------------------------------------------------------------------


def partition(widths: list[float], spaces: list[float], caps: list[float], props: list[float]):
    """Découpe les mots en len(caps) lignes consécutives.
    Retourne (liste de (debut, fin), ratio_max)."""
    W, N = len(widths), len(caps)
    if N == 1 or W == 0:
        tot = sum(widths) + sum(spaces[:-1]) if W else 0.0
        return [(0, W)] + [(W, W)] * (N - 1), (tot / caps[0] if caps[0] > 0 else 1.0)
    pw = [0.0]
    for w in widths:
        pw.append(pw[-1] + w)
    ps = [0.0]
    for s in spaces:
        ps.append(ps[-1] + s)

    def width(j, k):
        return 0.0 if k <= j else (pw[k] - pw[j]) + (ps[k - 1] - ps[j])

    n_lines = min(N, W)  # chaque ligne utilisée reçoit au moins un mot
    INF = float("inf")
    if W > 400:  # garde-fou : glouton proportionnel
        bounds, j = [], 0
        for i in range(n_lines):
            k = W if i == n_lines - 1 else max(j + 1, min(W - (n_lines - i - 1), round(props[i] * W)))
            bounds.append((j, k))
            j = k
        r = max(width(a, b) / caps[i] for i, (a, b) in enumerate(bounds))
        return bounds + [(W, W)] * (N - n_lines), r

    # 1) minimiser le débordement maximal
    best = [[INF] * (W + 1) for _ in range(n_lines + 1)]
    best[0][0] = 0.0
    for i in range(1, n_lines + 1):
        cap = caps[i - 1]
        for k in range(i, W - (n_lines - i) + 1):
            m = INF
            for j in range(i - 1, k):
                if best[i - 1][j] == INF:
                    continue
                v = max(best[i - 1][j], width(j, k) / cap)
                if v < m:
                    m = v
            best[i][k] = m
    r_min = best[n_lines][W]
    bound = max(1.0, r_min) * (1 + 1e-9) + 1e-9

    # 2) sous cette contrainte, coller aux proportions des lignes d'origine
    total = width(0, W) or 1.0
    cum_target = []
    acc = 0.0
    for p in props[:n_lines]:
        acc += p
        cum_target.append(acc)
    cost = [[INF] * (W + 1) for _ in range(n_lines + 1)]
    back = [[-1] * (W + 1) for _ in range(n_lines + 1)]
    cost[0][0] = 0.0
    for i in range(1, n_lines + 1):
        cap = caps[i - 1]
        for k in range(i, W - (n_lines - i) + 1):
            dev = (width(0, k) / total - cum_target[i - 1]) ** 2 if i < n_lines else 0.0
            for j in range(i - 1, k):
                if cost[i - 1][j] == INF or width(j, k) / cap > bound:
                    continue
                v = cost[i - 1][j] + dev
                if v < cost[i][k]:
                    cost[i][k] = v
                    back[i][k] = j
    bounds = []
    k = W
    for i in range(n_lines, 0, -1):
        j = back[i][k]
        if j < 0:  # ne devrait pas arriver ; repli
            j = k - 1
        bounds.append((j, k))
        k = j
    bounds.reverse()
    r = max(width(a, b) / caps[i] for i, (a, b) in enumerate(bounds))
    return bounds + [(W, W)] * (N - n_lines), r


# ---------------------------------------------------------------------------
# Géométrie du paragraphe
# ---------------------------------------------------------------------------


@dataclass
class _LineGeo:
    s: float  # début (along)
    e: float  # fin
    o: float  # origine du texte (along)
    p: float  # ligne de base (perp)
    q0: float  # haut
    q1: float  # bas


def _line_geo(frame: Frame, line) -> _LineGeo:
    a, q = [], []
    for ch in line.body:
        if ch.is_space:
            continue
        a0, a1, q0, q1 = frame.rect_intervals(ch.bbox)
        a += [a0, a1]
        q += [q0, q1]
    o = line.origin
    if not a:
        v = frame.along(o)
        return _LineGeo(v, v, v, frame.perp(o), frame.perp(o), frame.perp(o))
    return _LineGeo(min(a), max(a), frame.along(o), frame.perp(o), min(q), max(q))


def _limits(frame: Frame, geos: list[_LineGeo], page: PageData, para_idx: int, size: float):
    smin, emax = min(g.s for g in geos), max(g.e for g in geos)
    band0 = min(g.q0 for g in geos) + 0.2 * size
    band1 = max(g.q1 for g in geos) - 0.2 * size
    if band1 <= band0:
        mid = (band0 + band1) / 2
        band0, band1 = mid - 0.1, mid + 0.1
    pa0, pa1, _, _ = frame.rect_intervals(page.page_rect)
    margin = 0.012 * (pa1 - pa0)
    left, right = pa0 + margin, pa1 - margin
    container = None
    pad = 0.25 * size
    for rect, owner in page.obstacles:
        if owner == para_idx:
            continue
        a0, a1, q0, q1 = frame.rect_intervals(rect)
        if min(q1, band1) - max(q0, band0) <= 0.3:
            continue
        if a0 <= smin + 0.5 and a1 >= emax - 0.5:
            # vrai conteneur (cadre, forme), pas le fond de page ; on garde le plus serré
            is_frame = (a1 - a0) < 0.97 * (pa1 - pa0)
            if is_frame and (container is None or (a1 - a0) < (container[1] - container[0])):
                container = (a0, a1)
            right = min(right, a1 - pad) if a1 - pad > emax else right
            left = max(left, a0 + pad) if a0 + pad < smin else left
        elif a0 >= emax - 0.5:
            right = min(right, a0 - pad)
        elif a1 <= smin + 0.5:
            left = max(left, a1 + pad)
        # chevauchement partiel (soulignement, surlignage) : ignoré
    return min(left, smin), max(right, emax), container


def _left_anchored(frame: Frame, geo: _LineGeo, page: PageData, para_idx: int, size: float) -> bool:
    """Vrai si une autre ligne de texte de la page commence au même endroit
    (colonne commune) : le texte est alors aligné à gauche, pas centré."""
    for rect, owner in page.obstacles:
        if owner < 0 or owner == para_idx:
            continue
        a0, _, q0, _ = frame.rect_intervals(rect)
        if abs(a0 - geo.s) < 0.4 * size and abs(q0 - geo.q0) < 12 * size:
            return True
    return False


def _alignment(
    geos: list[_LineGeo], left: float, right: float, container, size: float, left_anchored: bool = False
) -> str:
    if len(geos) >= 2:
        tol = 0.5 * size
        dl = max(abs(g.s - geos[0].s) for g in geos)
        dr = max(abs(g.e - geos[0].e) for g in geos[:-1])  # dernière ligne libre
        dc = max(abs((g.s + g.e) / 2 - (geos[0].s + geos[0].e) / 2) for g in geos)
        if dl <= tol:
            return "justify" if dr <= tol and len(geos) >= 3 else "left"
        if dc <= tol:
            return "center"
        if max(abs(g.e - geos[0].e) for g in geos) <= tol:
            return "right"
        return "left"
    g = geos[0]
    if left_anchored:  # même marge gauche qu'une autre ligne de la page
        return "left"
    c = (g.s + g.e) / 2
    if container is not None:
        cc = (container[0] + container[1]) / 2
        if abs(c - cc) < 0.04 * (container[1] - container[0]) + 0.3 * size:
            return "center"
    lf, rf = g.s - left, right - g.e
    if lf > 2 * size and rf > 2 * size and abs(lf - rf) < max(1.0 * size, 0.04 * (lf + rf)):
        return "center"
    return "left"


def layout_paragraph(enc: Encoded, tokens: list[Token], fm: FontManager, page: PageData) -> ParaLayout:
    para = enc.para
    frame = Frame(para.lines[0].origin, para.dir)
    geos = [_line_geo(frame, line) for line in para.lines]
    size = enc.base.size
    left, right, container = _limits(frame, geos, page, para.index, size)
    anchored = len(geos) == 1 and _left_anchored(frame, geos[0], page, para.index, size)
    align = _alignment(geos, left, right, container, size, anchored)
    smin, emax = min(g.s for g in geos), max(g.e for g in geos)
    W0 = max(emax - smin, size)
    ext = max(0.6 * W0, 4 * size) if len(geos) == 1 else 0.15 * W0 + size

    caps = []
    for g in geos:
        own = max(g.e - g.s, 1.0)
        if align in ("left", "justify"):
            cap = min(right, emax + ext) - g.o
        elif align == "right":
            cap = g.e - max(left, smin - ext)
        else:
            c = (g.s + g.e) / 2
            half = min(min(right, emax + ext / 2) - c, c - max(left, smin - ext / 2))
            cap = 2 * half
        caps.append(max(cap, own))

    words = build_words(tokens, enc, fm)
    widths = [w.width for w in words]
    spaces = [w.space for w in words]
    orig = [max(g.e - g.s, 0.0) for g in geos]
    tot = sum(orig) or 1.0
    props = [v / tot for v in orig]
    bounds, ratio = partition(widths, spaces, caps, props)

    lay = ParaLayout(para, align=align, ratio=ratio)
    if ratio > 1.0:
        lay.hscale = max(1.0 / ratio, MIN_HSCALE)
        lay.size_factor = min(1.0, (1.0 / ratio) / lay.hscale)
        if lay.size_factor < MIN_SIZE_WARN:
            lay.warnings.append(f"taille réduite à {lay.size_factor:.0%}")
    g_scale = lay.hscale * lay.size_factor
    sf = lay.size_factor
    lay.matrix = frame.matrix(lay.hscale)
    lay.frame = frame

    def ul(style: Style):
        u = style.underline
        return None if u is None else (u[0] * sf, u[1] * sf, u[2])

    for li, (geo, (j, k)) in enumerate(zip(geos, bounds)):
        line_words = words[j:k]
        if not line_words:
            continue
        nat = sum(w.width for w in line_words) + sum(w.space for w in line_words[:-1])
        width = nat * g_scale
        extra_gap = 0.0
        if align in ("left", "justify"):
            start = geo.o
            if align == "justify" and li < len(geos) - 1 and len(line_words) > 1:
                target = geo.e - geo.o
                gap = (target - width) / (len(line_words) - 1)
                if 0 < gap <= 3 * line_words[0].space * g_scale:
                    extra_gap = gap
        elif align == "right":
            start = geo.e - width
        else:
            start = (geo.s + geo.e) / 2 - width / 2

        adv = start
        for wi, w in enumerate(line_words):
            for pc in w.pieces:
                if pc.kind == "t":
                    lay.chunks.append(
                        Chunk(
                            frame.point(adv, geo.p),
                            pc.text,
                            pc.font,
                            pc.style.size * sf,
                            pc.style.rgb,
                            ul(pc.style),
                            pc.style.alpha,
                        )
                    )
                else:
                    ph = pc.ph
                    for ch, (oa, op) in zip(ph.chars, ph.offsets):
                        font = fm.for_original(ch.style, ch.c)
                        pt = frame.point(adv + oa * g_scale, geo.p + (ph.rise + op) * sf)
                        lay.chunks.append(
                            Chunk(pt, ch.c, font, ch.style.size * sf, ch.style.rgb, ul(ch.style), ch.style.alpha)
                        )
                adv += pc.width * g_scale
            if wi < len(line_words) - 1:
                adv += w.space * g_scale + extra_gap
    _merge_chunks(lay, frame)
    return lay


def _merge_chunks(lay: ParaLayout, frame: Frame) -> None:
    """Fusionne les morceaux contigus de même style (fragments d'un même mot).

    Les mots ne sont jamais fusionnés à travers une espace : dans beaucoup de
    polices l'espace et l'espace insécable partagent un glyphe, et le PDF
    produit se lirait « mot mot ». Chaque mot est donc placé à sa position
    et les lecteurs PDF reconstituent les espaces d'après les écarts."""
    out: list[Chunk] = []
    for c in lay.chunks:
        if out:
            p = out[-1]
            if (
                p.font is c.font
                and abs(p.size - c.size) < 1e-6
                and p.color == c.color
                and p.underline == c.underline
                and p.alpha == c.alpha
                and len(c.text) > 0
            ):
                expected = p.font.text_length(p.text, fontsize=p.size) * lay.hscale
                da = frame.along(c.point) - frame.along(p.point)
                dp = frame.perp(c.point) - frame.perp(p.point)
                if abs(dp) < 0.01 and abs(da - expected) < 0.05:
                    p.text += c.text
                    continue
        out.append(c)
    lay.chunks = out
