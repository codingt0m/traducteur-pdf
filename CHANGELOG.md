# Journal des versions

## v1.1.0 — 2026-11-12

### Nouveautés
- Choix de la **langue cible** (20 langues : alphabets latin, cyrillique, grec et CJK),
  dans l'interface (choix mémorisé) et en ligne de commande (`--target`).
- Chinois, japonais, coréen : coupure des lignes entre les caractères et polices CJK de Windows.
- Exécutable autonome `Traducteur PDF.exe` ; glisser un dossier sur l'exe pré-remplit la source.

### Corrections
- Le texte produit contenait des espaces insécables (U+00A0) à la place des espaces :
  recherche et copier-coller sont désormais corrects.
- Espace manquante entre une balise de style et un symbole protégé (« durée δ »).

### Interne
- Code restructuré : `cli.py`, `gui.py`, `files.py` ; pipeline découpé en étapes.
- Moteur LLM local retiré (évalué, non retenu).
- Tests unitaires et de bout en bout ; configuration ruff dans `pyproject.toml`.

## v1.0.0

- Traduction de PDF en conservant positions, polices, couleurs, sauts de ligne,
  soulignements et orientation ; images et tracés vectoriels inchangés.
- Formules, indices et symboles recopiés à l'identique ; texte invisible ignoré.
- Google Traduction (gratuit) avec cache ; rapports JSON et aperçus avant/après.
