"""Traduction de PDF de cours en conservant la mise en page.

Principe : le texte vectoriel est extrait ligne par ligne avec son style et sa
position exacte, traduit par paragraphe, puis réécrit au même endroit (même
police, taille, couleur, orientation, mêmes sauts de ligne). Les images et les
tracés vectoriels ne sont jamais modifiés : seuls les glyphes du texte source
sont retirés (redaction ciblée).
"""

__version__ = "1.1.0"
