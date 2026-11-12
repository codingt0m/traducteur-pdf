"""Utilitaires de fichiers communs à la ligne de commande et à l'interface."""

from __future__ import annotations

from pathlib import Path


def list_pdfs(paths: list[Path]) -> list[Path]:
    """Fichiers PDF désignés par une liste de fichiers et/ou de dossiers."""
    files: list[Path] = []
    for p in paths:
        files += sorted(f for f in p.iterdir() if f.is_file()) if p.is_dir() else [p]
    return [f for f in dict.fromkeys(files) if f.suffix.lower() == ".pdf" and f.exists()]


def output_path(src: Path, out_dir: Path, target: str) -> Path:
    """cours.pdf -> <out_dir>/cours_<langue>.pdf"""
    return out_dir / f"{src.stem}_{target}.pdf"


def report_path(src: Path, out_dir: Path) -> Path:
    return out_dir / "rapports" / f"{src.stem}.json"


def cache_dir(out_dir: Path) -> Path:
    return out_dir / ".cache"


def parse_pages(spec: str | None) -> list[int] | None:
    """'1-3,7' -> [0, 1, 2, 6] (numérotation humaine -> index). None = toutes."""
    if not spec:
        return None
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a) - 1, int(b))
        elif part:
            out.append(int(part) - 1)
    return sorted(set(out))
