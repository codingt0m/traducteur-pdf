"""Orchestration : extraction -> traduction -> mise en page -> rendu -> sauvegarde."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .encoding import TAG_RE, Encoded, decode, encode
from .extract import extract_page
from .fonts import FontManager
from .layout import layout_paragraph
from .model import PageData
from .postprocess import fix_punctuation, insert_tag, looks_like, missing_tags, tag_inner
from .render import redact_paragraphs, write_layout
from .report import make_previews, summarize, write_report
from .translators import Translator

Log = Callable[[str], None]

STATUS_OK = "traduit"
STATUS_SAME = "inchangé (déjà dans la langue cible ou intraduisible)"
STATUS_FAILED = "échec : original conservé"


@dataclass
class _Page:
    data: PageData
    encoded: list[Encoded]


@dataclass
class _Translations:
    text: dict[str, str | None] = field(default_factory=dict)  # source encodée -> traduction
    styles_lost: dict[str, int] = field(default_factory=dict)  # source -> nb de styles non récupérés


def _same_text(a: str, b: str) -> bool:
    """Deux textes identiques aux espaces et apostrophes près (« IC1: » ≡ « IC1 : »)."""

    def norm(s: str) -> str:
        return re.sub(r"\s+", "", TAG_RE.sub("", s).replace("’", "'")).lower()

    return norm(a) == norm(b)


# ---------------------------------------------------------------------------
# Étapes
# ---------------------------------------------------------------------------


def _extract(doc: pymupdf.Document, page_nums: list[int]) -> tuple[list[_Page], dict[int, int]]:
    """Extrait chaque page dans son repère non tourné. Retourne aussi les
    rotations d'origine, à restaurer avant la sauvegarde."""
    pages, rotations = [], {}
    for pno in page_nums:
        page = doc[pno]
        rotations[pno] = page.rotation
        if page.rotation:
            page.set_rotation(0)
        data = extract_page(page)
        pages.append(_Page(data, [encode(p) for p in data.paragraphs]))
    return pages, rotations


def _translate(pages: list[_Page], translator: Translator, log: Log) -> _Translations:
    encoded = {e.text: e for p in pages for e in p.encoded if e.translatable}
    already = {t for t in encoded if looks_like(t, translator.target)}
    todo = [t for t in encoded if t not in already]
    log(
        f"  {len(todo)} segments à traduire ({sum(map(len, todo))} caractères), "
        f"{len(already)} déjà dans la langue cible"
    )

    last = [0.0]

    def progress(done: int, total: int) -> None:
        if time.time() - last[0] > 2 or done == total:
            last[0] = time.time()
            log(f"    traduction {done}/{total}")

    result = _Translations()
    result.text = dict(zip(todo, translator.translate_many(todo, progress)))
    result.text.update({t: t for t in already})
    result.text = {s: fix_punctuation(s, tr) for s, tr in result.text.items()}
    _recover_styles(encoded, result, translator, log)
    return result


def _recover_styles(encoded: dict[str, Encoded], tr: _Translations, translator: Translator, log: Log) -> None:
    """Quand le traducteur a supprimé des balises de style, on traduit chaque
    fragment stylé seul et on le retrouve dans la phrase traduite."""
    lost = {s: m for s, t in tr.text.items() if t is not None and (m := missing_tags(encoded[s], t))}
    if not lost:
        return
    inners = list(dict.fromkeys(i for s, tags in lost.items() for n in tags if (i := tag_inner(encoded[s], n))))
    log(f"  {len(lost)} segments aux styles internes perdus : récupération de {len(inners)} fragments")
    inner_tr = dict(zip(inners, translator.translate_many(inners)))
    for s, tags in lost.items():
        text, n_lost = tr.text[s], 0
        for n in tags:
            inner = tag_inner(encoded[s], n)
            text, ok = insert_tag(text, n, [inner_tr.get(inner), inner])
            n_lost += not ok
        tr.text[s] = text
        if n_lost:
            tr.styles_lost[s] = n_lost


def _render(page: pymupdf.Page, item: _Page, tr: _Translations, fm: FontManager) -> list[dict]:
    """Remplace le texte des paragraphes traduits. Retourne les entrées du rapport."""
    entries, plans = [], []
    for enc in item.encoded:
        if not enc.translatable:
            continue
        translated = tr.text.get(enc.text)
        entry = {"page": item.data.number + 1, "source": enc.text, "traduction": translated}
        if enc.text in tr.styles_lost:
            entry["styles_perdus"] = tr.styles_lost[enc.text]
        tokens = decode(enc, translated) if translated is not None else None
        if tokens is None:
            entry["statut"] = STATUS_FAILED
        elif _same_text(translated, enc.text):
            entry["statut"] = STATUS_SAME  # l'original est conservé à l'identique
        else:
            lay = layout_paragraph(enc, tokens, fm, item.data)
            plans.append(lay)
            entry.update(
                statut=STATUS_OK,
                lignes=len(enc.para.lines),
                alignement=lay.align,
                ratio=round(lay.ratio, 3),
                hscale=round(lay.hscale, 3),
                taille=round(lay.size_factor, 3),
            )
            if lay.warnings:
                entry["alertes"] = lay.warnings
        entries.append(entry)
    redact_paragraphs(page, [lay.para for lay in plans])
    for lay in plans:
        write_layout(page, lay)
    return entries


def _save(doc: pymupdf.Document, dst: Path, log: Log) -> None:
    try:
        doc.subset_fonts()  # n'embarque que les glyphes utilisés
    except Exception as e:  # optimisation de taille uniquement
        log(f"  (sous-ensemble des polices ignoré : {e})")
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(dst, garbage=3, deflate=True)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def translate_document(
    src: Path,
    dst: Path,
    translator: Translator,
    pages: list[int] | None = None,
    report_path: Path | None = None,
    preview_dir: Path | None = None,
    preview_pages: list[int] | None = None,
    log: Log = print,
) -> dict:
    """Traduit `src` vers `dst` et retourne un résumé (statuts, ajustements...)."""
    t0 = time.time()
    with pymupdf.open(src) as doc:
        fm = FontManager(doc, translator.target)
        page_nums = [p for p in (pages or range(doc.page_count)) if 0 <= p < doc.page_count]

        items, rotations = _extract(doc, page_nums)
        log(f"  {len(page_nums)} pages, {sum(len(i.encoded) for i in items)} paragraphes extraits")
        translations = _translate(items, translator, log)
        entries = [e for item in items for e in _render(doc[item.data.number], item, translations, fm)]

        for pno, rot in rotations.items():
            if rot:
                doc[pno].set_rotation(rot)
        _save(doc, dst, log)

    meta = {
        "source": str(src),
        "sortie": str(dst),
        "moteur": translator.name,
        "langue": translator.target,
        "duree_s": round(time.time() - t0, 1),
        "polices_substituees": fm.substitutions,
    }
    summary = summarize(entries, meta)
    if report_path is not None:
        write_report(summary, entries, report_path)
    if preview_dir is not None:
        make_previews(src, dst, preview_pages or page_nums[:3], preview_dir)
    return summary
