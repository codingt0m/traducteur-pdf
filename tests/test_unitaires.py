"""Tests unitaires (sans réseau) : python -m unittest"""

import unittest
from pathlib import Path

from pdf_traducteur.encoding import _restore_spaces
from pdf_traducteur.files import output_path, parse_pages
from pdf_traducteur.layout import partition
from pdf_traducteur.postprocess import fix_punctuation, insert_tag, looks_like


class TestFichiers(unittest.TestCase):
    def test_parse_pages(self):
        self.assertIsNone(parse_pages(None))
        self.assertEqual(parse_pages("1-3,7"), [0, 1, 2, 6])
        self.assertEqual(parse_pages("2, 2,3"), [1, 2])

    def test_output_path(self):
        self.assertEqual(output_path(Path("a/cours.pdf"), Path("out"), "es"), Path("out/cours_es.pdf"))


class TestPartition(unittest.TestCase):
    def test_meme_nombre_de_lignes(self):
        widths, spaces = [10.0] * 6, [2.0] * 6
        bounds, ratio = partition(widths, spaces, caps=[50.0, 50.0], props=[0.5, 0.5])
        self.assertEqual(len(bounds), 2)
        self.assertEqual(bounds, [(0, 3), (3, 6)])  # proportions d'origine respectées
        self.assertLessEqual(ratio, 1.0)

    def test_debordement_minimise(self):
        bounds, ratio = partition([30.0, 30.0, 30.0], [3.0] * 3, caps=[40.0, 40.0], props=[0.5, 0.5])
        self.assertEqual(len(bounds), 2)
        self.assertAlmostEqual(ratio, 63 / 40)  # 2 mots sur une ligne : (30+3+30)/40

    def test_moins_de_mots_que_de_lignes(self):
        bounds, _ = partition([10.0], [2.0], caps=[50.0, 50.0, 50.0], props=[0.4, 0.3, 0.3])
        self.assertEqual(bounds[0], (0, 1))
        self.assertTrue(all(a == b for a, b in bounds[1:]))  # lignes suivantes vides


class TestPostTraitement(unittest.TestCase):
    def test_espaces_autour_des_balises(self):
        src = "Client samples <b1>round trip time</b1> ⟦0⟧ ="
        self.assertEqual(
            _restore_spaces(src, "Échantillons<b1>durée</b1>⟦0⟧ ="),
            "Échantillons <b1>durée</b1> ⟦0⟧ =",
        )

    def test_detection_langue(self):
        self.assertTrue(looks_like("Architectures et programmation par composants", "fr"))
        self.assertFalse(looks_like("The happens before relation is a partial order", "fr"))
        self.assertTrue(looks_like("The happens before relation is a partial order", "en"))
        self.assertFalse(looks_like("Bonjour le monde et la lune", "es"))  # pas d'heuristique : on traduit

    def test_point_final(self):
        self.assertEqual(fix_punctuation("Every node returns data", "Chaque nœud renvoie."), "Chaque nœud renvoie")
        self.assertEqual(fix_punctuation("It works.", "Ça marche."), "Ça marche.")
        self.assertEqual(fix_punctuation("Wait", "Attendez..."), "Attendez...")

    def test_recuperation_style(self):
        text, ok = insert_tag("Même avec la synchronisation NTP, la dérive", 1, ["synchronisation NTP"])
        self.assertTrue(ok)
        self.assertEqual(text, "Même avec la <b1>synchronisation NTP</b1>, la dérive")
        _, ok = insert_tag("Rien à voir", 2, ["absent"])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
