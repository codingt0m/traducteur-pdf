"""Rapport de contrôle (JSON) et aperçus avant/après côte à côte (PNG)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pymupdf


def summarize(entries: list[dict], meta: dict) -> dict:
    """Statistiques globales d'une traduction (statuts, ajustements de mise en page)."""
    squeezed = [e for e in entries if e.get("ratio", 1) > 1.0]
    return {
        **meta,
        "paragraphes": len(entries),
        "statuts": dict(Counter(e["statut"] for e in entries)),
        "lignes_ajustees": len(squeezed),
        "styles_internes_perdus": sum(e.get("styles_perdus", 0) for e in entries),
        "compression_min": round(min((e["hscale"] for e in squeezed), default=1.0), 3),
        "taille_min": round(min((e["taille"] for e in squeezed), default=1.0), 3),
    }


def write_report(summary: dict, entries: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"resume": summary, "paragraphes": entries}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def make_previews(src: Path, dst: Path, pages: list[int], outdir: Path, dpi: int = 80) -> list[Path]:
    """Une image par page : original à gauche, traduction à droite."""
    outdir.mkdir(parents=True, exist_ok=True)
    files = []
    with pymupdf.open(src) as a, pymupdf.open(dst) as b:
        for pno in pages:
            if pno >= a.page_count:
                continue
            pa, pb = a[pno].get_pixmap(dpi=dpi), b[pno].get_pixmap(dpi=dpi)
            gap = 12
            size = pymupdf.IRect(0, 0, pa.width + pb.width + gap, max(pa.height, pb.height))
            sheet = pymupdf.Pixmap(pymupdf.csRGB, size, False)
            sheet.clear_with(150)
            pa.set_origin(0, 0)
            pb.set_origin(pa.width + gap, 0)
            sheet.copy(pa, pa.irect)
            sheet.copy(pb, pb.irect)
            f = outdir / f"{src.stem}_p{pno + 1:03d}.png"
            sheet.save(f)
            files.append(f)
    return files
