# Traducteur de PDF de cours (mise en page préservée)

Le PDF traduit est identique à l'original, sauf la langue du texte : mêmes
positions, polices, tailles, couleurs, sauts de ligne, soulignements,
orientation. Les images et les tracés vectoriels ne sont **jamais** modifiés.

## Exécutable Windows (aucune installation)

**`Traducteur PDF.exe`** est autonome : Python et PyMuPDF sont inclus. On
peut le copier seul sur n'importe quel PC Windows 10 ou 11 64 bits et
l'ouvrir par un double-clic. Il faut seulement une connexion Internet, pour
Google Traduction.

- On peut aussi **glisser un dossier sur l'exe** : le champ source est alors pré-rempli.
- Le premier lancement prend quelques secondes, le temps que l'exe se décompresse.
- L'exe n'est pas signé. Windows SmartScreen peut afficher « Windows a protégé
  votre ordinateur » : cliquez sur *Informations complémentaires*, puis sur
  *Exécuter quand même*.
- L'exe se télécharge depuis les *releases* (archive `TraducteurPDF-vX.Y.Z-windows-x64.zip`) ou se recompile avec `build.bat`.

## Utilisation depuis les sources

```powershell
pip install -r requirements.txt
```

### Interface graphique

Lancez `pythonw interface.pyw` (ou `python -m pdf_traducteur.gui`), puis :
1. **PDF à traduire** : le dossier qui contient les PDF ;
2. **Destination** : le dossier où écrire les traductions (proposé par défaut : `<source>\traductions`) ;
3. **Langue cible** : français par défaut. Le dernier choix est mémorisé ;
4. **Lancer**.

La barre de progression et le journal suivent l'avancement. L'option « Ignorer
les PDF déjà traduits » permet de relancer sur un dossier sans tout refaire.

### Ligne de commande

```powershell
python traduire_pdf.py cours.pdf                     # -> traductions\cours_fr.pdf
python traduire_pdf.py dossier_pdf -o traductions    # tout un dossier
python traduire_pdf.py cours.pdf --pages 1-5 --apercus 1,3
python traduire_pdf.py cours.pdf --target es         # autre langue cible
python -m pdf_traducteur --help                      # équivalent
```

Langues disponibles : fr, en, es, de, it, pt, nl, pl, ro, sv, da, cs, tr, el,
ru, uk, zh-CN, zh-TW, ja, ko. Le fichier produit s'appelle `<nom>_<langue>.pdf`.
Pour le chinois, le japonais et le coréen, les lignes sont coupées entre les
caractères et les polices CJK de Windows sont utilisées (Microsoft YaHei, Yu
Gothic, Malgun Gothic). L'arabe, l'hébreu et les écritures indiennes ne sont
pas proposés : ils demandent une mise en forme (écriture de droite à gauche,
ligatures) que le moteur d'écriture de PyMuPDF ne fait pas.

Sorties dans le dossier de destination :

| Chemin | Contenu |
|---|---|
| `<nom>_<langue>.pdf` | le PDF traduit |
| `rapports/<nom>.json` | chaque paragraphe : source, traduction, statut, compression appliquée |
| `apercus/*.png` | original et traduction côte à côte (ligne de commande uniquement) |
| `.cache/` | les traductions déjà faites (une relance ne retraduit rien) |

## Traduction : Google Traduction (gratuit)

**Google est-il gratuit ?** Oui. Le programme utilise le point d'accès public
de Google Traduction (celui des extensions de navigateur) : pas de clé, pas de
compte, pas de facturation. C'est toutefois un service non officiel, sans
garantie. Google peut le limiter (erreur 429, que le programme gère par des
pauses et des reprises) ou le bloquer, et le texte des cours lui est envoyé.
L'API officielle, Cloud Translation, offre 500 000 caractères gratuits par mois
puis environ 20 $ par million de caractères, mais elle demande un compte Google
Cloud avec facturation. À titre de repère, les 3 PDF d'exemple font environ
43 000 caractères.

Un modèle local (TranslateGemma 4B) a été évalué puis écarté : il est 200 fois
plus lent et perd des styles internes (gras, couleurs), même si sa terminologie
est meilleure.

## Développement

```powershell
pip install -e .[dev]           # installe le paquet + ruff + pyinstaller
python -m unittest              # tests (sans réseau : faux traducteur)
ruff check . ; ruff format .    # lint et formatage
build.bat                       # compile « Traducteur PDF.exe »
```

```
pdf_traducteur/
├── cli.py          ligne de commande
├── gui.py          interface graphique (Tkinter)
├── pipeline.py     orchestration : extraction → traduction → rendu
├── extract.py      lecture caractère par caractère, paragraphes, soulignements
├── encoding.py     balises de style <bN> et marqueurs protégés ⟦N⟧
├── translators.py  Google Traduction + cache disque
├── postprocess.py  langue déjà cible, ponctuation, récupération des styles
├── layout.py       répartition sur les lignes d'origine, alignement, ajustement
├── render.py       redaction ciblée et écriture du texte traduit
├── fonts.py        choix des polices (système / embarquées / CJK)
├── languages.py    langues proposées
├── model.py        structures de données et géométrie
├── report.py       rapport JSON et aperçus PNG
└── files.py        chemins et utilitaires
tests/              tests unitaires et de bout en bout
interface.pyw       point d'entrée de l'exe (interface)
traduire_pdf.py     point d'entrée ligne de commande
```

## Fonctionnement

1. **Extraction** (`extract.py`) : chaque caractère est relevé avec sa police, sa taille, sa couleur, sa position et son orientation. Pages tournées, puces et soulignements vectoriels sont gérés. Les espaces implicites sont reconstitués. Le texte invisible (calque d'accessibilité) est ignoré.
2. **Encodage** (`encoding.py`) : les lignes sont regroupées en paragraphes. Les mots de style différent sont balisés `<bN>…</bN>`. Les formules, indices, symboles, URL et e-mails sont protégés par des marqueurs `⟦N⟧`.
3. **Traduction** (`translators.py`, `postprocess.py`) : traduction par lots avec cache ; le texte déjà dans la langue cible n'est pas envoyé ; si le traducteur perd un style interne, le fragment stylé est retraduit seul et replacé.
4. **Mise en page** (`layout.py`) : la traduction est répartie sur **le même nombre de lignes** que l'original, en suivant les proportions des lignes d'origine. Le texte peut s'étendre dans l'espace libre, jusqu'au prochain obstacle (texte, image, cadre ou bord). En cas de débordement, il est resserré horizontalement (jusqu'à 85 %), puis réduit en taille en dernier recours.
5. **Rendu** (`render.py`) : seuls les glyphes d'origine sont retirés, par une redaction ciblée qui préserve les images et le dessin vectoriel. Le texte traduit est ensuite écrit à la même position, avec la police système de la même famille. Les formules sont reproduites avec la police embarquée d'origine.

## Limites connues

- Le texte **contenu dans les images** (captures d'écran) n'est pas traduit : il faudrait modifier l'image.
- Le texte invisible (calque OCR ou d'accessibilité) reste dans la langue d'origine.
- Les polices embarquées sont des sous-ensembles sans accents. Le texte traduit utilise donc la police système de la même famille (Calibri, Arial, Times…). Le dessin est le même, mais le fichier est un peu plus lourd.
- Google commet parfois des contresens techniques (« ordering » → « commande »). Les rapports JSON permettent de les repérer.
