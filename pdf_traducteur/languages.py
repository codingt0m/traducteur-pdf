"""Langues de destination proposées.

Seules les écritures que PyMuPDF sait écrire correctement sont listées :
alphabets latin, cyrillique et grec, et écritures CJK (chinois, japonais,
coréen). L'arabe, l'hébreu et les écritures indiennes demandent une mise en
forme du texte (droite à gauche, ligatures) qui n'est pas disponible ici.
"""

LANGUAGES: dict[str, str] = {
    "fr": "Français",
    "en": "Anglais",
    "es": "Espagnol",
    "de": "Allemand",
    "it": "Italien",
    "pt": "Portugais",
    "nl": "Néerlandais",
    "pl": "Polonais",
    "ro": "Roumain",
    "sv": "Suédois",
    "da": "Danois",
    "cs": "Tchèque",
    "tr": "Turc",
    "el": "Grec",
    "ru": "Russe",
    "uk": "Ukrainien",
    "zh-CN": "Chinois (simplifié)",
    "zh-TW": "Chinois (traditionnel)",
    "ja": "Japonais",
    "ko": "Coréen",
}

# Polices système de secours pour les écritures CJK (Windows), par ordre de préférence
CJK_FONTS = {
    "zh-CN": ("msyh.ttc", "simsun.ttc"),
    "zh-TW": ("msjh.ttc", "mingliub.ttc", "msyh.ttc"),
    "ja": ("YuGothM.ttc", "meiryo.ttc", "msgothic.ttc"),
    "ko": ("malgun.ttf", "gulim.ttc"),
}


def is_cjk_char(c: str) -> bool:
    cp = ord(c)
    return (
        0x3040 <= cp <= 0x30FF
        or 0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xAC00 <= cp <= 0xD7AF
        or 0xF900 <= cp <= 0xFAFF
        or 0x3000 <= cp <= 0x303F
        or 0xFF00 <= cp <= 0xFFEF
    )
