"""
Site statique de consultation de la veille.

Deux responsabilités distinctes :

1. **Archiver** les items bruts (titre, URL, source, date) dans `data/AAAA-MM-JJ.json`.
   La note Obsidian ne contient que de la prose rédigée par le modèle : les URLs y
   sont noyées dans le texte, inexploitables pour un affichage cliquable. On garde
   donc les items tels que collectés, à côté du digest.

   Un fichier par jour, et non une archive unique : une fois écrit, un fichier ne
   change plus. Git ne stocke donc chaque journée qu'une fois (~40 Ko), là où une
   archive globale serait réécrite intégralement à chaque run.

2. **Construire** `site/index.html`, autonome et sans dépendance réseau : les données
   sont injectées dans la page. Un `fetch()` vers un JSON voisin échouerait, le
   navigateur refusant les requêtes cross-origin sur `file://` — or le site est fait
   pour être ouvert par double-clic, sans serveur.
"""
import base64
import html
import json
import os
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from . import config, developpements, favoris, summarize

DOSSIER_DATA = config.RACINE / "data"
DOSSIER_SITE = config.RACINE / "site"
FICHIER_INDEX = DOSSIER_SITE / "index.html"

# Le site public est une seconde construction des mêmes données, expurgée : ni
# signets, ni favoris, ni développements. Un dossier distinct, pour qu'aucune
# confusion ne soit possible entre ce qui reste ici et ce qui est publié.
DOSSIER_PUBLIC = config.RACINE / "site-public"

# Nombre de jours affichés. Au-delà, les fichiers restent dans data/ (et dans git)
# mais ne sont plus chargés : inutile d'alourdir la page avec de l'archive froide.
JOURS_AFFICHES = 90

# Extrait conservé pour l'affichage. Les changelogs sont collectés jusqu'à 6000
# caractères pour le résumé ; les recopier en entier ferait une page de plusieurs
# mégaoctets pour un texte que personne ne lit dans une liste.
EXTRAIT_SITE = 320

# Repérage de la priorité n°1 du profil. Volontairement large : mieux vaut mettre en
# avant un item limite que d'en manquer un.
_MOTS_PRIORITAIRES = (
    "claude",
    "anthropic",
    "mcp",
    "model context protocol",
)


# --------------------------------------------------------------------------- #
# Archivage
# --------------------------------------------------------------------------- #


def _chemin_jour(jour: date) -> Path:
    return DOSSIER_DATA / f"{jour.isoformat()}.json"


def _alleger(item: dict) -> dict:
    """Ne conserve que ce dont la page a besoin, extrait tronqué."""
    extrait = (item.get("extrait") or "").strip()
    if len(extrait) > EXTRAIT_SITE:
        extrait = extrait[:EXTRAIT_SITE].rsplit(" ", 1)[0] + "…"

    date_item = item.get("date")
    return {
        "titre": item.get("titre", ""),
        "url": item.get("url", ""),
        "date": date_item.isoformat() if isinstance(date_item, datetime) else date_item,
        "extrait": extrait,
        "source_id": item.get("source_id", ""),
        "source_nom": item.get("source_nom", ""),
        "categorie": item.get("categorie", ""),
        "poids": item.get("poids", 1),
        "titre_utilisateur": bool(item.get("titre_utilisateur")),
        # Absent si le modèle n'a pas noté cet item (au-delà du plafond envoyé, ou
        # bloc de scores illisible). La page traite ce cas comme « à afficher ».
        "score": item.get("score"),
        # Fiche rédigée, pour les signets. C'est elle qui porte la valeur : sans elle,
        # la carte ne montrerait que le texte du tweet, soit rien de plus que X.
        "analyse": item.get("analyse", ""),
        "verdict": item.get("verdict", ""),
        "justification": item.get("justification", ""),
        # Cible réelle du signet : le dépôt ou l'article, pas le tweet qui le relaie.
        "cible": (item.get("liens") or [""])[0],
    }


def enregistrer_jour(jour: date, items: list[dict], digest: str = "") -> Path:
    """Archive les items du jour, en complétant le fichier s'il existe déjà.

    Une seconde exécution le même jour n'apporte que les items arrivés depuis la
    première : elle complète l'archive, comme elle complète la note Obsidian.
    """
    chemin = _chemin_jour(jour)
    existant = {"date": jour.isoformat(), "items": [], "digests": []}

    if chemin.exists():
        try:
            existant = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass  # fichier illisible : on repart d'une base saine plutôt qu'échouer

    connues = {it.get("url") for it in existant.get("items", [])}
    nouveaux = [_alleger(it) for it in items if it.get("url") not in connues]

    existant["items"] = existant.get("items", []) + nouveaux
    if digest.strip():
        existant.setdefault("digests", []).append(
            {"heure": datetime.now(config.FUSEAU).strftime("%Hh%M"), "corps": digest.strip()}
        )
    existant["maj"] = datetime.now(config.FUSEAU).isoformat(timespec="seconds")

    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(existant, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return chemin


def retirer_categorie(jour: date, categorie: str) -> int:
    """Retire d'une journée archivée tous les items d'une catégorie.

    `enregistrer_jour` ne fait qu'ajouter : un item déjà connu par son URL n'est jamais
    mis à jour. Retraiter des signets pour en améliorer les fiches n'aurait donc aucun
    effet visible sans ce nettoyage préalable.

    Returns:
        le nombre d'items retirés.
    """
    chemin = _chemin_jour(jour)
    if not chemin.exists():
        return 0

    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    avant = len(donnees.get("items", []))
    donnees["items"] = [
        it for it in donnees.get("items", []) if it.get("categorie") != categorie
    ]
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    return avant - len(donnees["items"])


def annoter_jour(jour: date, scores: dict[str, float], digest: str = "") -> int:
    """Écrit des scores dans une archive déjà enregistrée, appariés par URL.

    Sert à rattraper une journée non notée : jours amorcés avant l'ajout du scoring,
    run où le bloc de scores s'est perdu, ou renotation après un changement de prompt.

    Returns:
        le nombre d'items effectivement annotés.
    """
    chemin = _chemin_jour(jour)
    if not chemin.exists():
        return 0

    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    touches = 0
    for it in donnees.get("items", []):
        if it.get("url") in scores:
            it["score"] = scores[it["url"]]
            touches += 1

    if digest.strip() and not donnees.get("digests"):
        donnees["digests"] = [{"heure": "", "corps": digest.strip()}]

    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    return touches


def charger_jours(limite: int = JOURS_AFFICHES) -> list[dict]:
    """Charge les archives quotidiennes, de la plus récente à la plus ancienne."""
    if not DOSSIER_DATA.exists():
        return []

    jours = []
    for chemin in sorted(DOSSIER_DATA.glob("????-??-??.json"), reverse=True)[:limite]:
        try:
            jours.append(json.loads(chemin.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return jours


# --------------------------------------------------------------------------- #
# Rendu markdown -> HTML
# --------------------------------------------------------------------------- #

_MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _inline(texte: str) -> str:
    """Applique le balisage en ligne sur du texte déjà échappé."""
    texte = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', texte)
    texte = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", texte)
    # Italiques, après le gras : ce qui reste entre astérisques simples. Les bornes ne
    # doivent pas être collées à une espace, sinon « 3 * 4 * 5 » passerait en italique.
    texte = re.sub(r"\*(?!\s)([^*\n]+?)(?<!\s)\*", r"<em>\1</em>", texte)
    texte = re.sub(r"`([^`]+)`", r"<code>\1</code>", texte)
    # URL nue : uniquement si elle n'est pas déjà dans un href produit ci-dessus.
    texte = re.sub(
        r'(?<!href=")(?<!>)(https?://[^\s<>"]+)',
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        texte,
    )
    return texte


def markdown_html(md: str) -> str:
    """Convertit le sous-ensemble de markdown produit par le modèle.

    Volontairement minimal : titres, listes, gras, code, liens, paragraphes et blocs
    clôturés. Une dépendance markdown complète serait disproportionnée pour ce que le
    modèle écrit, et ajouterait un paquet à installer dans le runner.
    """
    sortie: list[str] = []
    dans_liste = False
    dans_bloc = False

    for ligne in md.splitlines():
        brute = ligne.rstrip()

        # Bloc clôturé : tout y est pris au pied de la lettre, indentation comprise.
        # C'est le mode « développer » qui l'a rendu nécessaire — un exemple d'usage
        # sans bloc de code se retrouvait aplati en paragraphes.
        if brute.strip().startswith("```"):
            if dans_bloc:
                sortie.append("</code></pre>")
            else:
                if dans_liste:
                    sortie.append("</ul>")
                    dans_liste = False
                sortie.append("<pre><code>")
            dans_bloc = not dans_bloc
            continue

        if dans_bloc:
            sortie.append(html.escape(brute))
            continue

        nue = html.escape(brute.strip())

        if not nue:
            if dans_liste:
                sortie.append("</ul>")
                dans_liste = False
            continue

        puce = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", nue)
        if puce:
            if not dans_liste:
                sortie.append("<ul>")
                dans_liste = True
            sortie.append(f"<li>{_inline(puce.group(1))}</li>")
            continue

        if dans_liste:
            sortie.append("</ul>")
            dans_liste = False

        titre = re.match(r"^(#{1,6})\s+(.*)$", nue)
        if titre:
            # Le digest commence en `##` ; on le décale pour rester sous le <h2> du jour.
            niveau = min(len(titre.group(1)) + 1, 6)
            sortie.append(f"<h{niveau}>{_inline(titre.group(2))}</h{niveau}>")
            continue

        if re.fullmatch(r"-{3,}", nue):
            sortie.append("<hr>")
            continue

        sortie.append(f"<p>{_inline(nue)}</p>")

    if dans_liste:
        sortie.append("</ul>")
    if dans_bloc:
        sortie.append("</code></pre>")   # bloc laissé ouvert par le modèle
    return "\n".join(sortie)


# --------------------------------------------------------------------------- #
# Construction de la page
# --------------------------------------------------------------------------- #


def _prioritaire(item: dict) -> bool:
    champs = f"{item.get('titre', '')} {item.get('extrait', '')} {item.get('source_id', '')}".lower()
    return any(mot in champs for mot in _MOTS_PRIORITAIRES)


def _libelle_jour(iso: str) -> str:
    try:
        j = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{_JOURS[j.weekday()]} {j.day} {_MOIS[j.month - 1]} {j.year}"


SEMAINES_AFFICHEES = 26

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_LIEN_JOUR = re.compile(r"\[\[(\d{4}-\d{2}-\d{2})\]\]")


def _libelle_semaine(champs: dict, identifiant: str) -> str:
    """« semaine 33 · 10 au 16 août 2026 », ou l'identifiant si les dates manquent."""
    try:
        debut = date.fromisoformat(champs["debut"])
        fin = date.fromisoformat(champs["fin"])
    except (KeyError, ValueError):
        return identifiant
    numero = champs.get("semaine", identifiant).split("-W")[-1].lstrip("0") or "?"
    # Le mois n'est répété que s'il change en cours de semaine.
    ouverture = f"{debut.day}" if debut.month == fin.month else f"{debut.day} {_MOIS[debut.month - 1]}"
    return f"semaine {numero} · {ouverture} au {fin.day} {_MOIS[fin.month - 1]} {fin.year}"


def charger_semaines(limite: int = SEMAINES_AFFICHEES) -> list[dict]:
    """Lit les digests hebdomadaires, du plus récent au plus ancien.

    Ils sont relus depuis le vault et non depuis `data/` : ce sont des notes rédigées,
    écrites par `run_weekly.py`, dont le vault est la source. En tenir une seconde copie
    ici la ferait diverger le jour où une note est corrigée à la main — ce qui arrive,
    puisqu'elles sont faites pour être lues et annotées.
    """
    dossier = config.DOSSIER_DIGESTS
    if not dossier.exists():
        return []

    semaines = []
    for chemin in sorted(dossier.glob("????-W??.md"), reverse=True)[:limite]:
        try:
            texte = chemin.read_text(encoding="utf-8")
        except OSError:
            continue

        champs = {}
        entete = _FRONTMATTER.match(texte)
        if entete:
            for ligne in entete.group(1).splitlines():
                cle, sep, valeur = ligne.partition(":")
                if sep:
                    champs[cle.strip()] = valeur.strip()
            texte = texte[entete.end():]

        # Le <h1> de la note répète mot pour mot ce que la barre de navigation affiche.
        texte = re.sub(r"\A\s*#\s+.*\n", "", texte)

        # Les liens de la note vers les quotidiens ne mènent nulle part dans une page
        # web. Transformés en boutons, ils y mènent : un clic bascule sur la journée.
        corps = _LIEN_JOUR.sub(
            lambda m: f'<button class="lien-jour" data-date="{m.group(1)}">'
                      f"{_libelle_jour(m.group(1))}</button>",
            markdown_html(texte),
        )

        semaines.append({
            "id": chemin.stem,
            "debut": champs.get("debut", ""),
            "fin": champs.get("fin", ""),
            "libelle": _libelle_semaine(champs, chemin.stem),
            "html": corps,
        })
    return semaines


def _preparer(jours: list[dict], public: bool = False) -> dict:
    """Assemble la structure consommée par la page.

    Args:
        public: expurge tout ce qui est personnel. Les signets et les favoris sont
            des choix propres à une personne, et les fiches de signets portent des
            justifications rattachées à son profil : rien de tout cela n'a sa place
            sur une page publique.

            Les digests hebdomadaires non plus, et ce n'est pas une précaution de
            principe : la synthèse du 16/08 conclut sur « des chantiers de
            modernisation et de migration de pipelines de données patrimoniaux (SAS
            vers Python) ». Le prompt hebdo travaille sur sept notes d'affilée et
            ressort la ligne éditoriale bien plus franchement que le quotidien. Tant
            qu'il en est ainsi, ces notes restent personnelles.
    """
    prepares = []
    total = 0

    for jour in jours:
        items = []
        for it in jour.get("items", []):
            if not it.get("url"):
                continue
            if public and it.get("categorie") == "signets":
                continue
            it = dict(it)
            it["prioritaire"] = _prioritaire(it)
            it["voie"] = config.voie(it.get("score"))
            items.append(it)

        # Claude reste en tête quoi qu'il arrive, avant même le score : c'est la
        # priorité n°1 du profil, et le scoring d'un modèle est reconnu instable d'une
        # exécution à l'autre. Le score départage ensuite, puis le poids de source.
        items.sort(
            key=lambda it: (
                it["prioritaire"],
                it.get("score") if it.get("score") is not None else -1,
                it.get("poids", 1),
                it.get("date") or "",
            ),
            reverse=True,
        )

        digests = [
            {"heure": d.get("heure", ""), "html": markdown_html(d.get("corps", ""))}
            for d in jour.get("digests", [])
            if d.get("corps")
        ]

        total += len(items)
        prepares.append(
            {
                "date": jour.get("date", ""),
                "libelle": _libelle_jour(jour.get("date", "")),
                "items": items,
                "digests": digests,
            }
        )

    # Les favoris viennent du vault, pas de l'archive : un favori doit survivre à la
    # sortie de sa journée de la fenêtre de 90 jours. La page les fusionne avec ceux
    # que le navigateur détient — voir le bloc `favoris` du script.
    enregistres = []
    for f in ([] if public else favoris.charger()["favoris"]):
        f = dict(f)
        f["prioritaire"] = _prioritaire(f)
        f["voie"] = config.voie(f.get("score"))
        enregistres.append(f)

    # Les développements sont embarqués pour les seules URLs affichables : ceux des
    # journées sorties de la fenêtre ne sont plus atteignables, les embarquer ferait
    # grossir la page indéfiniment. Le cache complet reste dans data/, lui.
    atteignables = {it["url"] for j in prepares for it in j["items"]}
    atteignables.update(f.get("url") for f in enregistres)
    # Rien n'est publié côté public : le développement d'un article de tiers y est
    # produit à la demande, dans le navigateur du lecteur et avec sa propre clé, puis
    # gardé chez lui. Le site ne rediffuse donc pas de résumés substitutifs.
    semaines = [] if public else charger_semaines()

    tous_dev = {} if public else developpements.charger()
    dev = {
        url: {"html": markdown_html(d.get("corps", "")), "genere": d.get("genere", "")}
        for url, d in tous_dev.items()
        if url in atteignables
    }

    return {
        "jours": prepares,
        "semaines": semaines,
        "favoris": enregistres,
        "developpements": dev,
        "total": total,
        "public": public,
        # Le prompt de développement voyage avec la page publique : le lecteur appelle
        # Gemini lui-même, il faut donc qu'elle sache quoi lui demander. Un prompt n'est
        # pas un secret — la clé, si, et elle ne quitte jamais le navigateur du lecteur.
        "profil": config.PROFIL_PUBLIC if public else "",
        "consignes": summarize.CONSIGNES_DEVELOPPER if public else "",
        "modele": config.MODELE_GEMINI if public else "",
        "worker": config.WORKER_LECTURE if public else "",
        # Tant qu'aucun item n'est noté — archive antérieure au scoring, ou bloc de
        # scores perdu — la page s'ouvre sur « Tout ». Filtrer par défaut sur une voie
        # vide donnerait une page blanche.
        "notes": any(it.get("score") is not None for j in prepares for it in j["items"]),
        "genere": datetime.now(config.FUSEAU).strftime("%d/%m/%Y à %Hh%M"),
    }


DOSSIER_ASSETS = config.RACINE / "assets"

# IBM Plex Sans, fonte variable 400-600, découpée par Google Fonts en sous-ensembles.
# Seuls latin et latin-ext sont embarqués : ils couvrent le français et les noms
# d'auteurs européens. Le cyrillique et le grec pèseraient sans jamais servir.
_SOUS_ENSEMBLES = (
    ("ibm-plex-sans-latin.woff2",
     "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
     "U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, "
     "U+2212, U+2215, U+FEFF, U+FFFD"),
    ("ibm-plex-sans-latin-ext.woff2",
     "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, "
     "U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, "
     "U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF"),
)


@lru_cache(maxsize=1)
def polices() -> str:
    """Renvoie les @font-face, fontes comprises, encodées en base64.

    Embarquées et non chargées depuis Google Fonts, pour trois raisons qui tiennent
    toutes à des promesses déjà écrites ailleurs : la page reste autonome et s'ouvre
    hors ligne, elle n'ajoute aucune requête réseau, et le site public ne laisse rien
    fuiter de ses lecteurs — un <link> vers fonts.googleapis.com enverrait leur IP à
    Google, ce que la note Site public affirme ne pas faire.

    Si les fichiers manquent, on renvoie une chaîne vide : la pile système reprend la
    main et la page reste parfaitement lisible.
    """
    blocs = []
    for nom, plage in _SOUS_ENSEMBLES:
        fichier = DOSSIER_ASSETS / nom
        if not fichier.exists():
            continue
        b64 = base64.b64encode(fichier.read_bytes()).decode("ascii")
        blocs.append(
            "@font-face{font-family:'IBM Plex Sans';font-style:normal;"
            "font-weight:400 600;font-display:swap;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
            f"unicode-range:{plage}}}"
        )
    return "\n".join(blocs)


def construire(limite: int = JOURS_AFFICHES, public: bool = False) -> Path:
    """Génère la page et renvoie son chemin.

    Args:
        public: construit le site publiable dans site-public/, sans rien de personnel.
    """
    donnees = _preparer(charger_jours(limite), public=public)

    # `</script>` apparaissant dans un extrait fermerait la balise avant l'heure.
    charge = json.dumps(donnees, ensure_ascii=False).replace("<", "\\u003c")

    dossier = DOSSIER_PUBLIC if public else DOSSIER_SITE
    dossier.mkdir(parents=True, exist_ok=True)
    index = dossier / "index.html"

    # Écriture atomique : le serveur local reconstruit la page pendant qu'un navigateur
    # peut être en train de la lire. Un write_text direct la lui servirait tronquée.
    provisoire = index.with_suffix(".html.tmp")
    provisoire.write_text(gabarit().replace("__POLICES__", polices()).replace("__DONNEES__", charge), encoding="utf-8")
    os.replace(provisoire, index)

    if public:
        # Liste blanche du Worker de lecture : sans elle, il servirait de proxy ouvert à
        # qui voudrait s'en servir pour aller chercher n'importe quoi sur Internet. Ces
        # URLs sont déjà toutes des liens de la page, la publier n'apprend rien.
        cibles = sorted(
            {it["url"] for j in donnees["jours"] for it in j["items"]}
            | {it.get("cible") for j in donnees["jours"] for it in j["items"] if it.get("cible")}
        )
        (dossier / "urls.json").write_text(
            json.dumps(cibles, ensure_ascii=False), encoding="utf-8"
        )

    return index


# Le gabarit vit dans veille/gabarit/ depuis le 2026-09-17 : page.html, style.css
# et app.js. Il était jusque-là une chaîne Python de 1 500 lignes, où aucun éditeur
# ne colorait le CSS ni ne signalait une erreur de JavaScript. La page produite est
# inchangée : les trois fichiers sont réassemblés en un seul HTML autonome, qui
# s'ouvre hors ligne et n'émet aucune requête (voir polices()).
DOSSIER_GABARIT = Path(__file__).parent / "gabarit"


@lru_cache(maxsize=1)
def gabarit() -> str:
    """Assemble page.html + style.css + app.js, et renvoie le gabarit complet."""
    page = (DOSSIER_GABARIT / "page.html").read_text(encoding="utf-8")
    return (
        page
        .replace("__STYLE__", (DOSSIER_GABARIT / "style.css").read_text(encoding="utf-8").rstrip("\n"))
        .replace("__SCRIPT__", (DOSSIER_GABARIT / "app.js").read_text(encoding="utf-8").rstrip("\n"))
    )
