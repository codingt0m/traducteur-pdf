"""Test de bout en bout sur un PDF généré, avec un faux traducteur (sans réseau)."""

import re
import tempfile
import unittest
from pathlib import Path

import pymupdf

from pdf_traducteur.pipeline import translate_document
from pdf_traducteur.translators import Translator

LEXIQUE = {
    "hello": "bonjour",
    "world": "monde",
    "this": "ceci",
    "is": "est",
    "a": "un",
    "simple": "simple",
    "test": "essai",
    "document": "document",
}


class FauxTraducteur(Translator):
    """Traduit mot à mot via LEXIQUE en conservant balises et marqueurs."""

    name = "faux"

    def translate_many(self, texts, progress=None):
        def tr(m):
            w = m.group(0)
            out = LEXIQUE.get(w.lower(), w)
            return out.capitalize() if w[0].isupper() else out

        return [re.sub(r"(?<![<⟦/b])\b[A-Za-z]+\b", tr, t) for t in texts]


def make_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((50, 60), "Hello world", fontsize=24, fontname="helv")
    page.insert_text((50, 120), "This is a simple", fontsize=14, fontname="helv")
    page.insert_text((180, 120), "test", fontsize=14, fontname="helv", color=(1, 0, 0))
    page.draw_rect(pymupdf.Rect(40, 200, 300, 260), color=(0, 0, 1), width=2)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(400, 200, 480, 280), pixmap=pix)

    rotated = doc.new_page(width=400, height=600)
    rotated.insert_text((50, 60), "Hello document", fontsize=18, fontname="helv")
    rotated.set_rotation(90)
    doc.save(path)


class TestBoutEnBout(unittest.TestCase):
    def test_traduction_et_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src.pdf", Path(tmp) / "out" / "src_fr.pdf"
            make_pdf(src)
            summary = translate_document(src, dst, FauxTraducteur("fr"), log=lambda m: None)

            self.assertEqual(summary["statuts"].get("échec : original conservé", 0), 0)
            with pymupdf.open(src) as a, pymupdf.open(dst) as b:
                self.assertEqual(a.page_count, b.page_count)
                text0 = b[0].get_text()
                self.assertIn("Bonjour monde", text0)
                self.assertIn("Ceci est un simple", text0)
                self.assertIn("essai", text0)
                self.assertNotIn("Hello", text0)
                self.assertIn("Bonjour document", b[1].get_text())

                # Fond non textuel strictement identique
                for pa, pb in zip(a, b):
                    self.assertEqual(pa.rect, pb.rect)
                    self.assertEqual(pa.rotation, pb.rotation)
                    ia = [(tuple(i["bbox"]), i["digest"]) for i in pa.get_image_info(hashes=True)]
                    ib = [(tuple(i["bbox"]), i["digest"]) for i in pb.get_image_info(hashes=True)]
                    self.assertEqual(ia, ib)
                    self.assertEqual([d["rect"] for d in pa.get_drawings()], [d["rect"] for d in pb.get_drawings()])

                # Le mot en couleur garde sa couleur et sa position de ligne
                spans = [
                    s for blk in b[0].get_text("dict")["blocks"] for ln in blk.get("lines", []) for s in ln["spans"]
                ]
                red = [s for s in spans if s["color"] == 0xFF0000]
                self.assertTrue(red and "essai" in red[0]["text"])
                self.assertAlmostEqual(red[0]["origin"][1], 120, delta=0.5)


if __name__ == "__main__":
    unittest.main()
