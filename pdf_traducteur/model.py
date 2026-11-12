"""Structures de données et outils géométriques communs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
STYLE_WORDS = re.compile(r"(bold|italic|oblique|regular|roman|semibold|medium|black|heavy|mt|ps)$")

FLAG_ITALIC = 2
FLAG_SERIF = 4
FLAG_MONO = 8
FLAG_BOLD = 16


def clean_font_name(name: str) -> str:
    """'ABCDEF+Arial,Bold' -> 'Arial,Bold'."""
    return SUBSET_PREFIX.sub("", name or "")


def family_key(name: str) -> str:
    """Famille normalisée, sans mention de style : 'Arial-BoldMT' -> 'arial'."""
    n = clean_font_name(name).lower()
    n = re.split(r"[,\-]", n, maxsplit=1)[0]
    n = re.sub(r"[\s_]", "", n)
    prev = None
    while prev != n:
        prev = n
        n = STYLE_WORDS.sub("", n)
    return n


@dataclass(frozen=True)
class Style:
    font: str  # nom de police d'origine (tel que vu dans le PDF)
    size: float
    color: int  # sRGB entier 0xRRGGBB
    flags: int
    xref: int  # xref de la police embarquée (0 si inconnue)
    # Soulignement : (décalage sous la ligne de base, épaisseur, couleur rgb) en pt
    underline: tuple | None = None
    alpha: int = 255  # opacité du texte (0-255)

    @property
    def bold(self) -> bool:
        n = self.font.lower()
        return bool(self.flags & FLAG_BOLD) or any(k in n for k in ("bold", "black", "heavy", "semibold"))

    @property
    def italic(self) -> bool:
        n = self.font.lower()
        return bool(self.flags & FLAG_ITALIC) or "italic" in n or "oblique" in n

    @property
    def rgb(self) -> tuple[float, float, float]:
        c = self.color
        return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0

    def visual_key(self) -> tuple:
        """Clé de comparaison visuelle (police, taille arrondie, couleur)."""
        return (clean_font_name(self.font), round(self.size, 1), self.color, self.underline is not None)


@dataclass
class Char:
    c: str
    origin: tuple[float, float]
    bbox: tuple[float, float, float, float]
    style: Style

    @property
    def is_space(self) -> bool:
        return self.c.isspace() or self.c == " "


@dataclass
class Line:
    chars: list[Char]
    dir: tuple[float, float]
    bbox: pymupdf.Rect
    block: int
    prefix_len: int = 0  # puce conservée telle quelle en début de ligne
    underlines: list = field(default_factory=list)  # rects des traits de soulignement d'origine

    @property
    def body(self) -> list[Char]:
        return self.chars[self.prefix_len :]

    @property
    def text(self) -> str:
        return "".join(c.c for c in self.chars)

    @property
    def body_text(self) -> str:
        return "".join(c.c for c in self.body)

    @property
    def origin(self) -> pymupdf.Point:
        """Origine (ligne de base) du premier caractère du corps de ligne."""
        for ch in self.body:
            if not ch.is_space:
                return pymupdf.Point(ch.origin)
        return pymupdf.Point(self.chars[0].origin)

    def dominant_style(self) -> Style:
        counts: dict[Style, int] = {}
        for ch in self.body:
            if not ch.is_space:
                counts[ch.style] = counts.get(ch.style, 0) + 1
        if not counts:
            return self.chars[0].style
        return max(counts, key=counts.get)


@dataclass
class Paragraph:
    lines: list[Line]
    page: int
    index: int = 0

    @property
    def underlines(self) -> list:
        return [r for line in self.lines for r in line.underlines]

    @property
    def dir(self) -> tuple[float, float]:
        return self.lines[0].dir

    @property
    def text(self) -> str:
        return " / ".join(line.body_text.strip() for line in self.lines)


class Frame:
    """Repère local d'un paragraphe : axe 'along' (sens d'écriture) et 'perp'
    (vers le bas des glyphes). Fonctionne pour toute orientation."""

    def __init__(self, origin, direction):
        self.o = pymupdf.Point(origin)
        dx, dy = direction
        self.d = (dx, dy)
        self.n = (-dy, dx)

    def along(self, p) -> float:
        return (p[0] - self.o.x) * self.d[0] + (p[1] - self.o.y) * self.d[1]

    def perp(self, p) -> float:
        return (p[0] - self.o.x) * self.n[0] + (p[1] - self.o.y) * self.n[1]

    def rect_intervals(self, r) -> tuple[float, float, float, float]:
        """Projection d'un rectangle : (along_min, along_max, perp_min, perp_max)."""
        x0, y0, x1, y1 = r
        pts = ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
        a = [self.along(p) for p in pts]
        q = [self.perp(p) for p in pts]
        return min(a), max(a), min(q), max(q)

    def point(self, along: float, perp: float = 0.0) -> pymupdf.Point:
        return pymupdf.Point(
            self.o.x + along * self.d[0] + perp * self.n[0],
            self.o.y + along * self.d[1] + perp * self.n[1],
        )

    def matrix(self, hscale: float = 1.0) -> pymupdf.Matrix:
        """Matrice de 'morph' TextWriter : compression horizontale puis rotation."""
        dx, dy = self.d
        return pymupdf.Matrix(hscale, 0, 0, 1, 0, 0) * pymupdf.Matrix(dx, -dy, dy, dx, 0, 0)


@dataclass
class PageData:
    """Tout ce qui est extrait d'une page avant modification."""

    number: int
    rotation: int
    paragraphs: list[Paragraph] = field(default_factory=list)
    obstacles: list[tuple[pymupdf.Rect, int]] = field(default_factory=list)  # (rect, id de ligne ou -1)
    page_rect: pymupdf.Rect | None = None
