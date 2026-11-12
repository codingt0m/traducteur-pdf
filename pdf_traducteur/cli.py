"""Ligne de commande.

Exemples :
  python traduire_pdf.py cours.pdf
  python traduire_pdf.py dossier_pdf -o traductions --target es
  python traduire_pdf.py cours.pdf --pages 1-5 --apercus 1,3,5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .files import cache_dir, list_pdfs, output_path, parse_pages, report_path
from .languages import LANGUAGES
from .pipeline import translate_document
from .translators import make_translator


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="traduire_pdf",
        description="Traduit des PDF de cours en conservant exactement la mise en page.",
    )
    ap.add_argument("pdf", nargs="+", type=Path, help="fichier(s) PDF ou dossier(s)")
    ap.add_argument("-o", "--out", type=Path, default=Path("traductions"), help="dossier de sortie")
    ap.add_argument(
        "--target",
        default="fr",
        choices=list(LANGUAGES),
        metavar="LANGUE",
        help="langue cible : " + ", ".join(LANGUAGES) + " (défaut : fr)",
    )
    ap.add_argument("--pause", type=float, default=0.4, help="pause entre deux requêtes, en secondes")
    ap.add_argument("--pages", default=None, help="pages à traiter, ex. 1-5,8 (défaut : toutes)")
    ap.add_argument("--apercus", default="1,2,3", help="pages des aperçus avant/après (vide : aucun)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    files = list_pdfs(args.pdf)
    if not files:
        print("Aucun PDF trouvé.", file=sys.stderr)
        return 1

    translator = make_translator(args.target, cache_dir=cache_dir(args.out), pause=args.pause)
    for f in files:
        print(f"• {f.name}")
        dst = output_path(f, args.out, args.target)
        summary = translate_document(
            f,
            dst,
            translator,
            pages=parse_pages(args.pages),
            report_path=report_path(f, args.out),
            preview_dir=args.out / "apercus" if args.apercus else None,
            preview_pages=parse_pages(args.apercus),
            log=lambda m: print(m, flush=True),
        )
        print(
            f"  -> {dst}  ({summary['duree_s']} s) statuts={summary['statuts']} "
            f"lignes ajustées={summary['lignes_ajustees']} taille min={summary['taille_min']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
