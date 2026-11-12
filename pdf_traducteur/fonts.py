"""Résolution des polices : police d'origine -> police utilisable pour écrire.

Les polices embarquées dans les PDF sont presque toujours des sous-ensembles
(subsets) qui ne contiennent que les glyphes utilisés : pas de « é », « à »...
On les réutilise donc uniquement pour les éléments recopiés à l'identique
(formules, symboles). Le texte traduit est écrit avec la police système de la
même famille (Calibri, Arial, Times New Roman...).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pymupdf

from .languages import CJK_FONTS
from .model import FLAG_MONO, FLAG_SERIF, Style, clean_font_name

# famille (forme compacte, minuscules) -> (regular, bold, italic, bold-italic)
FAMILIES: list[tuple[str, tuple[str, str, str, str]]] = [
    ("calibrilight", ("calibril.ttf", "calibrib.ttf", "calibrili.ttf", "calibriz.ttf")),
    ("calibri", ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf")),
    ("arialnarrow", ("ARIALN.TTF", "ARIALNB.TTF", "ARIALNI.TTF", "ARIALNBI.TTF")),
    ("arialblack", ("ariblk.ttf", "ariblk.ttf", "ariblk.ttf", "ariblk.ttf")),
    ("arial", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")),
    ("helvetica", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")),
    ("liberationsans", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")),
    ("timesnewroman", ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf")),
    ("times", ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf")),
    ("georgia", ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf")),
    ("cambria", ("cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf")),
    ("verdana", ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf")),
    ("tahoma", ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf")),
    ("trebuchet", ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf")),
    ("segoeui", ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf")),
    ("garamond", ("GARA.TTF", "GARABD.TTF", "GARAIT.TTF", "GARABD.TTF")),
    ("bookantiqua", ("BKANT.TTF", "ANTQUAB.TTF", "ANTQUAI.TTF", "ANTQUABI.TTF")),
    ("centurygothic", ("GOTHIC.TTF", "GOTHICB.TTF", "GOTHICI.TTF", "GOTHICBI.TTF")),
    ("consolas", ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf")),
    ("couriernew", ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf")),
    ("courier", ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf")),
    ("lucidaconsole", ("lucon.ttf", "lucon.ttf", "lucon.ttf", "lucon.ttf")),
    ("comicsans", ("comic.ttf", "comicbd.ttf", "comici.ttf", "comicz.ttf")),
]
SANS_FALLBACK = FAMILIES[4][1]  # Arial
SERIF_FALLBACK = FAMILIES[7][1]  # Times New Roman
MONO_FALLBACK = FAMILIES[19][1]  # Courier New
# Polices essayées pour les symboles absents ailleurs (flèches, lettres mathématiques...)
SYMBOL_CANDIDATES = ("seguisym.ttf", "cambria.ttc", "arial.ttf", "segoeui.ttf", "times.ttf")


def _font_dirs() -> list[Path]:
    dirs = []
    if sys.platform.startswith("win"):
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts", Path("/usr/local/share/fonts")]
    return [d for d in dirs if d.exists()]


class FontManager:
    def __init__(self, doc: pymupdf.Document, target: str = "fr"):
        self.doc = doc
        cjk = CJK_FONTS.get(target, ())
        others = tuple(f for fs in CJK_FONTS.values() for f in fs if f not in cjk)
        self.symbol_candidates = SYMBOL_CANDIDATES + cjk + others
        self._dirs = _font_dirs()
        self._file_index: dict[str, Path] | None = None
        self._fonts: dict[str, pymupdf.Font | None] = {}
        self._embedded: dict[int, pymupdf.Font | None] = {}
        self.substitutions: dict[str, str] = {}  # pour le rapport

    # ---- chargement ---------------------------------------------------------
    def _find_file(self, filename: str) -> Path | None:
        if self._file_index is None:
            self._file_index = {}
            for d in self._dirs:
                for p in d.rglob("*"):
                    if p.suffix.lower() in (".ttf", ".otf", ".ttc"):
                        self._file_index.setdefault(p.name.lower(), p)
        return self._file_index.get(filename.lower())

    def _load_file(self, filename: str) -> pymupdf.Font | None:
        if filename not in self._fonts:
            path = self._find_file(filename)
            font = None
            if path:
                try:
                    font = pymupdf.Font(fontfile=str(path))
                except Exception:
                    font = None
            self._fonts[filename] = font
        return self._fonts[filename]

    def embedded(self, xref: int) -> pymupdf.Font | None:
        if not xref:
            return None
        if xref not in self._embedded:
            font = None
            try:
                _, ext, _, buf = self.doc.extract_font(xref)
                if buf and ext not in ("n/a", ""):
                    font = pymupdf.Font(fontbuffer=buf)
            except Exception:
                font = None
            self._embedded[xref] = font
        return self._embedded[xref]

    @staticmethod
    def covers(font: pymupdf.Font | None, text: str) -> bool:
        if font is None:
            return False
        for ch in text:
            if ch.isspace():
                continue
            try:
                if not font.has_glyph(ord(ch)):
                    return False
            except Exception:
                return False
        return True

    # ---- résolution ---------------------------------------------------------
    def _system_files(self, style: Style) -> tuple[str, str, str, str]:
        compact = (
            clean_font_name(style.font).lower().replace(" ", "").replace("-", "").replace(",", "").replace("_", "")
        )
        for key, files in FAMILIES:
            if key in compact:
                return files
        if style.flags & FLAG_MONO or "mono" in compact or "code" in compact:
            return MONO_FALLBACK
        if style.flags & FLAG_SERIF or ("serif" in compact and "sans" not in compact):
            return SERIF_FALLBACK
        return SANS_FALLBACK

    def system_font(self, style: Style) -> pymupdf.Font:
        files = self._system_files(style)
        idx = (2 if style.italic else 0) + (1 if style.bold else 0)
        order = [idx, idx & 1, idx & 2, 0]
        for i in order:
            f = self._load_file(files[i])
            if f is not None:
                self.substitutions[clean_font_name(style.font)] = files[i]
                return f
        for files2 in (SANS_FALLBACK, SERIF_FALLBACK):
            f = self._load_file(files2[0])
            if f is not None:
                return f
        return pymupdf.Font("helv")  # police de base interne (Latin-1)

    def for_translation(self, style: Style, text: str) -> pymupdf.Font:
        """Police pour du texte traduit (doit contenir les accents français)."""
        f = self.system_font(style)
        if self.covers(f, text):
            return f
        emb = self.embedded(style.xref)
        if self.covers(emb, text):
            return emb
        return self.for_symbols(style, text, prefer=f)

    def for_original(self, style: Style, text: str) -> pymupdf.Font:
        """Police pour des glyphes recopiés à l'identique (formules, symboles) :
        la police embarquée d'origine en priorité."""
        emb = self.embedded(style.xref)
        if self.covers(emb, text):
            return emb
        f = self.system_font(style)
        if self.covers(f, text):
            return f
        return self.for_symbols(style, text, prefer=emb or f)

    def for_symbols(self, style: Style, text: str, prefer: pymupdf.Font | None) -> pymupdf.Font:
        for name in self.symbol_candidates:
            f = self._load_file(name)
            if self.covers(f, text):
                return f
        return prefer or self.system_font(style)
