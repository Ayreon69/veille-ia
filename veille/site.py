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
    provisoire.write_text(_GABARIT.replace("__POLICES__", polices()).replace("__DONNEES__", charge), encoding="utf-8")
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


_GABARIT = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Veille IA</title>
<style>
__POLICES__
/* La palette tient sur deux teintes et une poignée de clartés, en OKLCH — espace
   perceptuellement uniforme, où deux couleurs de même clarté paraissent vraiment
   aussi claires. Les gris ne sont pas neutres : ils portent la teinte du fond, chaude
   en clair, violacée en sombre. Le thème sombre ne redéfinit donc que les bases ;
   --bord et --accent-doux, qui sont des mélanges, suivent tout seuls. */
:root{
  --h-accent:41;     /* terre cuite */
  --h-neutre:68;     /* gris chauds */
  --l-accent:60%;
  --l-accent-doux:95.8%;

  --accent:oklch(var(--l-accent) .136 var(--h-accent));
  --fond:oklch(98.6% .002 var(--h-neutre));
  --fond-carte:oklch(100% 0 var(--h-neutre));
  --fond-doux:oklch(95.6% .0034 var(--h-neutre));
  --texte:oklch(21.9% .005 var(--h-neutre));
  --texte-doux:oklch(51% .012 var(--h-neutre));

  /* Un bord n'est rien d'autre qu'un soupçon d'encre dans le fond doux, et le
     fond d'accent porte la teinte de l'accent, à la clarté d'un fond.

     Le fond d'accent n'est surtout PAS un color-mix : mélanger 10 % d'accent dans le
     fond interpole la teinte, et 10 % ne suffisent pas à ramener un fond sombre de
     295° vers les 41° de la terre cuite — on obtenait un violet au lieu d'un brun. */
  --bord:color-mix(in oklch, var(--texte) 7%, var(--fond-doux));
  --accent-doux:oklch(var(--l-accent-doux) .018 var(--h-accent));

  --ombre:0 1px 2px rgba(0,0,0,.05), 0 4px 12px rgba(0,0,0,.04);

  /* Cinq tailles, pas une de plus. Toute valeur hors de cette échelle est un oubli. */
  --t-1:11.5px;      /* étiquettes, scores, pied de page */
  --t-2:12.5px;      /* méta, lignes secondaires */
  --t-3:13.5px;      /* contrôles, notes, texte dense */
  --t-4:15px;        /* corps de texte et titres d'articles */
  --t-5:19px;        /* titre du site */

  /* Ce qui s'écrit SUR l'accent. En thème clair l'accent est sombre et le blanc
     convient (4,4:1) ; en sombre il est clair, et le blanc y tombe à 2,67:1 — sous le
     seuil minimal de 3. Le fond y remonte à 6,8:1. Mesuré, pas supposé. */
  --sur-accent:oklch(100% 0 0);

  --pile:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --h-neutre:295;
    --l-accent:71.4%;
    --l-accent-doux:25.9%;
    --fond:oklch(19.9% .010 var(--h-neutre));
    --fond-carte:oklch(23.4% .0115 var(--h-neutre));
    --fond-doux:oklch(26.8% .013 var(--h-neutre));
    --texte:oklch(94% .008 var(--h-neutre));
    --texte-doux:oklch(68.2% .020 var(--h-neutre));
    --sur-accent:var(--fond);
    --ombre:0 1px 2px rgba(0,0,0,.3), 0 4px 14px rgba(0,0,0,.25);
  }
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--fond); color:var(--texte);
  font-family:var(--pile); font-size:var(--t-4); line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
a{color:inherit}
/* Deux lignes qui suppriment les mots orphelins : `balance` répartit un titre sur ses
   lignes au lieu d'en laisser un seul mot en dernière, `pretty` fait de même en fin de
   paragraphe. Sans effet là où le navigateur ne les connaît pas. */
h1,h2,h3,h4,.item h3,.signet .t{text-wrap:balance}
p,li,.resume,.analyse{text-wrap:pretty}

/* ---- en-tête ---- */
header{
  position:sticky; top:0; z-index:10; background:var(--fond);
  border-bottom:1px solid var(--bord);
}
.bandeau{max-width:880px; margin:0 auto; padding:18px 20px 12px}
.titre{display:flex; align-items:baseline; gap:12px; flex-wrap:wrap}
h1{font-size:var(--t-5); margin:0; letter-spacing:-.01em}
.meta{font-size:var(--t-2); color:var(--texte-doux)}
.onglets{
  /* `flex-wrap` depuis l'ajout du quatrième onglet : à trois la rangée tenait en
     375 px, à quatre elle poussait la page à 415 et faisait défiler horizontalement.
     Passer à la ligne vaut mieux qu'un défilement latéral, qui cacherait un onglet. */
  display:inline-flex; flex-wrap:wrap; max-width:100%;
  gap:3px; margin-top:14px; padding:3px;
  background:var(--fond-doux); border-radius:10px;
}
.onglet{
  padding:6px 15px; font:inherit; font-size:var(--t-3); font-weight:500; cursor:pointer;
  background:none; border:0; border-radius:8px; color:var(--texte-doux);
}
.onglet:hover{color:var(--texte)}
.onglet[aria-selected="true"]{
  background:var(--fond-carte); color:var(--texte); box-shadow:var(--ombre);
}
.onglet .n{opacity:.6; margin-left:6px; font-variant-numeric:tabular-nums}
.outils{display:flex; gap:10px; margin-top:12px}
#recherche{
  flex:1; min-width:0; padding:8px 12px; font:inherit; font-size:var(--t-3);
  background:var(--fond-carte); color:var(--texte);
  border:1px solid var(--bord); border-radius:8px;
}
#recherche:focus{outline:2px solid var(--accent); outline-offset:-1px}
#tri{
  flex:none; padding:8px 10px; font:inherit; font-size:var(--t-3); cursor:pointer;
  background:var(--fond-carte); color:var(--texte);
  border:1px solid var(--bord); border-radius:8px;
}
#tri:focus{outline:2px solid var(--accent); outline-offset:-1px}
#sauver{
  flex:none; padding:8px 12px; font:inherit; font-size:var(--t-3); font-weight:500; cursor:pointer;
  background:var(--fond-carte); color:var(--accent);
  border:1px solid var(--bord); border-radius:8px; white-space:nowrap;
}
#sauver:hover{background:var(--accent-doux)}
#sauver[hidden]{display:none}
#cle{
  flex:none; padding:8px 12px; font:inherit; font-size:var(--t-3); cursor:pointer;
  background:var(--fond-carte); color:var(--texte-doux);
  border:1px solid var(--bord); border-radius:8px; white-space:nowrap;
}
#cle:hover{color:var(--accent); border-color:var(--accent)}
#cle[hidden]{display:none}
#cle[data-active="true"]{color:var(--accent); border-color:var(--accent)}

/* ---- panneau de clé, site public ---- */
.panneau-cle{
  max-width:880px; margin:0 auto; padding:0 20px 14px; font-size:var(--t-3);
  color:var(--texte-doux); line-height:1.6;
}
.panneau-cle[hidden]{display:none}
.panneau-cle .boite{
  background:var(--fond-carte); border:1px solid var(--bord); border-radius:10px;
  padding:14px 16px; box-shadow:var(--ombre);
}
.panneau-cle h2{font-size:var(--t-3); margin:0 0 8px; color:var(--texte)}
.panneau-cle p{margin:6px 0}
.panneau-cle .rang{display:flex; gap:8px; margin-top:10px; flex-wrap:wrap}
.panneau-cle input{
  flex:1; min-width:220px; padding:8px 11px; font:inherit; font-size:var(--t-3);
  background:var(--fond); color:var(--texte);
  border:1px solid var(--bord); border-radius:7px;
}
.panneau-cle input:focus{outline:2px solid var(--accent); outline-offset:-1px}
.panneau-cle button{
  flex:none; padding:8px 14px; font:inherit; font-size:var(--t-3); font-weight:500;
  cursor:pointer; border-radius:7px; border:1px solid var(--bord);
  background:var(--fond); color:var(--texte);
}
.panneau-cle button.principal{
  background:var(--accent); border-color:var(--accent); color:var(--sur-accent);
}
.panneau-cle button:hover{border-color:var(--accent)}
.panneau-cle .note{margin-top:10px; font-size:var(--t-2); opacity:.85}
.bandeau-public{
  max-width:880px; margin:0 auto; padding:0 20px 12px;
  font-size:var(--t-2); color:var(--texte-doux); line-height:1.55;
}
.bandeau-public[hidden]{display:none}
.filtres{
  display:flex; gap:6px; overflow-x:auto; padding:10px 20px 12px;
  max-width:880px; margin:0 auto; scrollbar-width:none;
}
.filtres::-webkit-scrollbar{display:none}
/* `display:flex` ci-dessus l'emporterait sur la règle par défaut de [hidden]. */
.filtres[hidden]{display:none}
.puce{
  flex:none; padding:5px 11px; font-size:var(--t-2); cursor:pointer; white-space:nowrap;
  background:var(--fond-carte); color:var(--texte-doux);
  border:1px solid var(--bord); border-radius:999px;
}
.puce:hover{color:var(--texte)}
.puce[aria-pressed="true"]{
  background:var(--accent); border-color:var(--accent); color:var(--sur-accent); font-weight:500;
}
.puce .n{opacity:.65; margin-left:5px; font-variant-numeric:tabular-nums}
.voies{padding-bottom:0}
.voies .puce{font-weight:500}
.rangee{display:flex; align-items:center; gap:6px}
.rangee > .etiq{
  flex:none; font-size:var(--t-1); text-transform:uppercase; letter-spacing:.07em;
  color:var(--texte-doux); margin-right:2px;
}

.un-jour > .jour > h2{display:none}
.un-jour > .jour{margin-top:10px}

/* ---- navigation par jour ---- */
.nav-jour{display:flex; align-items:center; gap:6px; margin-top:12px; position:relative}
/* Même piège que `.filtres` : `display:flex` l'emporterait sur la règle de [hidden]. */
.nav-jour[hidden]{display:none}
.nav-jour button{
  font:inherit; font-size:var(--t-3); cursor:pointer; color:var(--texte);
  background:var(--fond-carte); border:1px solid var(--bord); border-radius:8px;
  padding:7px 10px;
}
.nav-jour button:hover:not(:disabled){border-color:var(--accent); color:var(--accent)}
.nav-jour button:disabled{opacity:.35; cursor:default}
.nav-jour .fleche{flex:none; width:34px; padding:7px 0; line-height:1; font-size:16px}
#datejour{flex:1; min-width:0; text-align:left; font-weight:500}
#datejour .n{float:right; font-weight:400; color:var(--texte-doux); font-variant-numeric:tabular-nums}
#tousjours{flex:none; color:var(--texte-doux)}
#tousjours[aria-pressed="true"]{
  background:var(--accent); border-color:var(--accent); color:var(--sur-accent); font-weight:500;
}

.calendrier{
  position:absolute; top:calc(100% + 6px); left:0; z-index:20; width:296px;
  background:var(--fond-carte); border:1px solid var(--bord); border-radius:12px;
  box-shadow:var(--ombre); padding:12px;
}
.calendrier[hidden]{display:none}
.cal-tete{display:flex; align-items:center; justify-content:space-between; margin-bottom:8px}
.cal-tete strong{font-size:var(--t-3); text-transform:capitalize}
.cal-grille{display:grid; grid-template-columns:repeat(7,1fr); gap:2px}
.cal-grille .jsem{
  text-align:center; font-size:var(--t-1); color:var(--texte-doux);
  text-transform:uppercase; letter-spacing:.05em; padding-bottom:4px;
}
.cal-case{
  /* `min-width:0` est indispensable : sans lui, la taille minimale automatique d'un
     élément de grille tient compte de son contenu, les colonnes `1fr` refusent de
     rétrécir et la grille déborde du panneau. Hauteur fixe plutôt qu'`aspect-ratio`,
     qui transfère la hauteur minimale en largeur minimale et reproduit le problème. */
  min-width:0; height:38px;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:1px; padding:0; border:0; border-radius:8px;
  background:none; color:var(--texte-doux); font:inherit; font-size:var(--t-2);
}
.cal-case:disabled{opacity:.3}
.cal-case.plein{background:var(--fond-doux); color:var(--texte); cursor:pointer; font-weight:500}
.cal-case.plein:hover{background:var(--accent-doux); color:var(--accent)}
.cal-case[aria-current="date"]{background:var(--accent); color:var(--sur-accent)}
.cal-case .n{font-size:var(--t-1); font-weight:400; opacity:.7; line-height:1; font-variant-numeric:tabular-nums}
.cal-case[aria-current="date"] .n{opacity:.85}

/* ---- digest hebdomadaire ---- */
.nav-jour .liste-semaines{width:300px; max-height:320px; overflow-y:auto; padding:6px}
.nav-jour .liste-semaines button{
  display:block; width:100%; text-align:left; padding:8px 10px;
  background:none; border:0; border-radius:8px; color:var(--texte);
  font:inherit; font-size:var(--t-3);
}
.nav-jour .liste-semaines button:hover{background:var(--fond-doux); border-color:transparent}
.nav-jour .liste-semaines button[aria-current="true"]{
  background:var(--accent); color:var(--sur-accent); font-weight:500;
}
.hebdo{margin-top:18px}
/* Pleine largeur, comme les cartes de la veille : une colonne de lecture étroite avait
   été essayée — 70 caractères par ligne, le confort typographique classique — et écartée
   le 23/08. Sur une page dont tout le reste occupe les 880 px, la colonne rétrécie se
   voyait comme un défaut d'alignement plutôt que comme une aide à la lecture.
   L'interligne et le rythme des paragraphes, eux, font le travail. */
.hebdo .corps{font-size:var(--t-4); line-height:1.7}
.hebdo .corps p{margin:0 0 16px}
.hebdo .corps h3{
  margin:34px 0 10px; font-size:var(--t-4); color:var(--accent); letter-spacing:0;
}
.hebdo .corps > h3:first-child{margin-top:2px}
.hebdo .corps h4{margin:22px 0 6px; font-size:var(--t-3); color:var(--texte)}
.hebdo .corps ul{margin:0 0 16px; padding-left:20px}
.hebdo .corps li{margin:0 0 9px}
/* « L'essentiel » ouvre la synthèse : la première liste sert de chapeau, on la traite
   comme tel plutôt que comme une liste à puces parmi d'autres. */
.hebdo .corps > h3:first-child + ul{
  margin:0 0 30px; padding:15px 18px 15px 20px; list-style:none;
  background:var(--fond-doux); border-left:3px solid var(--accent);
  border-radius:0 12px 12px 0;
}
.hebdo .corps > h3:first-child + ul li{margin:0 0 10px}
.hebdo .corps > h3:first-child + ul li:last-child{margin:0}
.hebdo .corps hr{border:0; border-top:1px solid var(--bord); margin:34px 0 0}
/* Les renvois vers les quotidiens, rendus cliquables : le digest hebdo est une porte
   d'entrée vers les journées, pas seulement un texte à lire. */
.lien-jour{
  padding:2px 9px; margin:2px 2px 2px 0; border:1px solid var(--bord); border-radius:999px;
  background:var(--fond-carte); color:var(--accent); font:inherit; font-size:var(--t-2);
  cursor:pointer;
}
.lien-jour:hover{border-color:var(--accent); background:var(--accent-doux)}
.lien-jour[disabled]{color:var(--texte-doux); opacity:.55; cursor:default}

/* ---- flux ---- */
main{max-width:880px; margin:0 auto; padding:8px 20px 80px}
.jour{margin-top:26px}
.jour > h2{
  font-size:var(--t-3); font-weight:600; text-transform:uppercase; letter-spacing:.06em;
  color:var(--texte-doux); margin:0 0 12px; padding-bottom:8px;
  border-bottom:1px solid var(--bord);
}
.jour > h2 .n{float:right; text-transform:none; letter-spacing:0; font-weight:400}

.digest{
  background:var(--fond-carte); border:1px solid var(--bord); border-radius:10px;
  padding:0 18px; margin-bottom:16px; box-shadow:var(--ombre);
}
.digest > summary{
  cursor:pointer; padding:12px 0; font-size:var(--t-3); font-weight:600;
  color:var(--accent); list-style:none;
}
.digest > summary::-webkit-details-marker{display:none}
.digest > summary::before{content:"▸ "; display:inline-block; transition:transform .15s}
.digest[open] > summary::before{transform:rotate(90deg)}
.digest[open] > summary{border-bottom:1px solid var(--bord)}
.corps{padding:4px 0 16px; font-size:var(--t-4)}
.corps h3{font-size:var(--t-4); margin:20px 0 8px; letter-spacing:-.01em}
.corps h4{font-size:var(--t-3); margin:16px 0 6px; color:var(--texte-doux)}
.corps p{margin:8px 0}
.corps ul{margin:8px 0; padding-left:20px}
.corps li{margin:5px 0}
.corps code{
  background:var(--fond-doux); padding:1px 5px; border-radius:4px; font-size:var(--t-2);
}
.corps hr{border:0; border-top:1px solid var(--bord); margin:16px 0}

/* L'étoile ne peut pas vivre dans la carte : celle-ci est un <a>, et un bouton
   imbriqué dans un lien est du HTML invalide, inatteignable au clavier. Elle est donc
   posée à côté, dans une enveloppe positionnée — d'où le déplacement au survol qui
   passe de la carte à l'enveloppe, pour que les deux bougent ensemble. */
.enveloppe{position:relative; transition:transform .12s}
.enveloppe:hover{transform:translateX(2px)}
.etoile, .plus{
  position:absolute; top:7px; right:7px; z-index:1;
  width:28px; height:28px; padding:0; line-height:1; font-size:16px; cursor:pointer;
  background:none; border:0; border-radius:6px; color:var(--texte-doux);
  opacity:.3; transition:opacity .12s, color .12s, background .12s;
}
/* Le bouton « développer » partage tout avec l'étoile, sauf sa position. */
.plus{right:35px; font-size:19px; font-weight:300}
.plus[data-fait="true"]{opacity:1; color:var(--accent)}
.enveloppe:hover .etoile, .enveloppe:hover .plus{opacity:.75}
.etoile:hover, .plus:hover{background:var(--fond-doux); color:var(--accent); opacity:1}
.etoile:focus-visible, .plus:focus-visible{outline:2px solid var(--accent); opacity:1}
/* Une fois en favori, l'étoile reste pleine et visible sans survol : c'est elle qui
   signale, dans le flux du jour, ce que j'ai déjà mis de côté. */
.etoile[aria-pressed="true"]{opacity:1; color:var(--accent)}

.item{
  display:block; text-decoration:none; padding:12px 14px; margin-bottom:6px;
  background:var(--fond-carte); border:1px solid var(--bord); border-radius:9px;
  border-left:3px solid transparent; transition:border-color .12s, transform .12s;
}
.item:hover{border-color:var(--bord); border-left-color:var(--accent)}
.item.prio{border-left-color:var(--accent); background:var(--accent-doux)}
.item.lu{opacity:.42}
.score{
  margin-left:auto; padding:1px 7px; border-radius:4px; font-size:var(--t-1);
  font-variant-numeric:tabular-nums; background:var(--fond-doux); color:var(--texte-doux);
}
.score.essentiel{background:var(--accent); color:var(--sur-accent); font-weight:600}
.score.bruit{opacity:.5}
.item h3{font-size:var(--t-4); font-weight:500; margin:0 0 5px; line-height:1.4; padding-right:52px}
.ligne{display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:var(--t-2); color:var(--texte-doux)}
.src{font-weight:500; color:var(--accent)}
.item.lu .src{color:var(--texte-doux)}
.cat{
  padding:1px 7px; border-radius:4px; background:var(--fond-doux);
  font-size:var(--t-1); letter-spacing:.02em;
}
.avis{
  padding:1px 7px; border-radius:4px; font-size:var(--t-1);
  background:var(--fond-doux); border:1px dashed var(--bord);
}
.extrait{
  margin:6px 0 0; font-size:var(--t-3); color:var(--texte-doux); line-height:1.5;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
}
/* ---- carte de signet : accordéon sur la fiche rédigée ---- */
.signet{padding:0}
.signet > summary{
  cursor:pointer; list-style:none; padding:12px 14px 12px 32px; position:relative;
}
.signet > summary::-webkit-details-marker{display:none}
.signet > summary::before{
  content:"›"; position:absolute; left:14px; top:11px;
  font-size:16px; color:var(--texte-doux); transition:transform .15s;
}
.signet[open] > summary::before{transform:rotate(90deg)}
.signet > summary:hover .t{color:var(--accent)}
.signet .t{display:block; font-size:var(--t-4); font-weight:500; line-height:1.4; margin-bottom:5px; padding-right:52px}
.deplie{padding:2px 14px 14px 32px}
.analyse{margin:8px 0 0; font-size:var(--t-3); line-height:1.55}
.pourtoi{
  margin:10px 0 0; padding:9px 11px; border-radius:7px; background:var(--fond-doux);
  font-size:var(--t-3); line-height:1.5;
}
.pourtoi b{color:var(--accent)}
.verdict{padding:1px 8px; border-radius:4px; font-size:var(--t-1); font-weight:600}
.v-fort{background:var(--accent); color:var(--sur-accent)}
.v-moyen{background:var(--fond-doux); color:var(--texte)}
.v-faible{background:var(--fond-doux); color:var(--texte-doux); font-weight:400}
.pieds{
  display:flex; gap:14px; flex-wrap:wrap; margin-top:10px;
  font-size:var(--t-2); color:var(--texte-doux);
}
.pieds a{color:var(--texte-doux)}
.pieds a:hover{color:var(--accent)}
/* ---- panneau de développement ---- */
.developpement{
  margin:-2px 0 10px 16px; padding:12px 16px 14px;
  background:var(--fond-doux); border-left:2px solid var(--accent);
  border-radius:0 8px 8px 0; font-size:var(--t-3); line-height:1.6;
}
.developpement[hidden]{display:none}
.developpement h3{font-size:var(--t-3); margin:16px 0 6px; letter-spacing:.02em; color:var(--accent)}
.developpement h3:first-child{margin-top:0}
.developpement h4{font-size:var(--t-3); margin:12px 0 5px; color:var(--texte-doux)}
.developpement p{margin:6px 0}
.developpement ul{margin:6px 0; padding-left:20px}
.developpement li{margin:4px 0}
.corps pre, .developpement pre{
  margin:8px 0; padding:10px 12px; border-radius:6px; overflow-x:auto;
  font-size:var(--t-2); line-height:1.5; background:var(--fond-carte);
  border:1px solid var(--bord);
}
.corps pre code, .developpement pre code{background:none; padding:0; font-size:inherit}
.developpement code{background:var(--fond-carte); padding:1px 5px; border-radius:4px; font-size:var(--t-2)}
.attente{color:var(--texte-doux); font-style:italic}
.attente.echec{color:var(--accent); font-style:normal}
.pied-dev{
  display:flex; gap:12px; margin-top:12px; padding-top:8px;
  border-top:1px solid var(--bord); font-size:var(--t-1); color:var(--texte-doux);
}
.pied-dev button{
  padding:0; font:inherit; cursor:pointer; background:none; border:0;
  color:var(--texte-doux); text-decoration:underline;
}
.pied-dev button:hover{color:var(--accent)}
.vide{text-align:center; color:var(--texte-doux); padding:60px 20px; font-size:var(--t-4)}

@media(max-width:600px){
  .bandeau{padding:14px 14px 10px}
  .filtres{padding:8px 14px 10px}
  main{padding:4px 14px 60px}
}
</style>
</head>
<body>

<header>
  <div class="bandeau">
    <div class="titre">
      <h1>Veille IA</h1>
      <span class="meta" id="resume"></span>
    </div>
    <div class="onglets" id="onglets" role="tablist"></div>
    <div class="outils">
      <input id="recherche" type="search" placeholder="Rechercher un titre, une source…" autocomplete="off">
      <select id="tri" aria-label="Ordre de tri">
        <option value="pertinence">Pertinence</option>
        <option value="date">Plus récent</option>
        <option value="date-inverse">Plus ancien</option>
      </select>
      <button id="sauver" hidden title="Télécharge un fichier favoris-....json, repris à la prochaine synchronisation">Sauvegarder</button>
      <button id="cle" hidden title="Votre clé Gemini, pour développer un article">Clé API</button>
    </div>
    <div class="nav-jour" id="nav-jour">
      <button class="fleche" id="prec" aria-label="Jour précédent" title="Jour précédent (flèche gauche)">&lsaquo;</button>
      <button id="datejour" aria-haspopup="dialog" aria-expanded="false" title="Choisir une date"></button>
      <button class="fleche" id="suiv" aria-label="Jour suivant" title="Jour suivant (flèche droite)">&rsaquo;</button>
      <button id="tousjours" aria-pressed="false" title="Empiler toutes les journées, comme avant">Tout</button>
      <div class="calendrier" id="calendrier" role="dialog" aria-label="Choisir une date" hidden></div>
    </div>
    <div class="nav-jour" id="nav-semaine" hidden>
      <button class="fleche" id="sem-prec" aria-label="Semaine précédente" title="Semaine précédente (flèche gauche)">&lsaquo;</button>
      <button id="sem-libelle" aria-haspopup="listbox" aria-expanded="false" title="Choisir une semaine"></button>
      <button class="fleche" id="sem-suiv" aria-label="Semaine suivante" title="Semaine suivante (flèche droite)">&rsaquo;</button>
      <div class="calendrier liste-semaines" id="liste-semaines" role="listbox" aria-label="Choisir une semaine" hidden></div>
    </div>
  </div>
  <div class="filtres voies" id="voies"></div>
  <div class="filtres" id="filtres"></div>
  <div class="bandeau-public" id="bandeau" hidden></div>
  <div class="panneau-cle" id="panneau-cle" hidden></div>
</header>

<main id="flux"></main>

<script id="donnees" type="application/json">__DONNEES__</script>
<script>
(function(){
  const D = JSON.parse(document.getElementById('donnees').textContent);
  const flux = document.getElementById('flux');
  const champ = document.getElementById('recherche');
  const barre = document.getElementById('filtres');
  const barreVoies = document.getElementById('voies');
  const boutonSauver = document.getElementById('sauver');

  // Les articles déjà ouverts sont estompés : sur plusieurs jours d'archive, c'est
  // ce qui distingue le nouveau du déjà-vu.
  const CLE = 'veille-lus';
  let lus = new Set(JSON.parse(localStorage.getItem(CLE) || '[]'));
  const marquer = url => {
    lus.add(url);
    localStorage.setItem(CLE, JSON.stringify([...lus].slice(-4000)));
  };

  // ---- favoris ----
  // L'item est stocké EN ENTIER, pas par son URL : la page n'affiche que 90 jours, et
  // un favori doit rester consultable une fois sa journée sortie de la fenêtre. Il est
  // alors rendu depuis cette copie, sans rien devoir aux données de la page.
  //
  // `retires` est la contrepartie nécessaire : les favoris arrivent de deux côtés — le
  // navigateur et le vault — et sans trace datée des retraits, chaque reconstruction du
  // site ferait revenir ce qui vient d'être enlevé. Le retrait l'emporte s'il est
  // postérieur à la mise en favori ; remettre en favori suffit donc à annuler.
  const CLE_FAV = 'veille-favoris';
  const CLE_RETIRES = 'veille-favoris-retires';
  const lire = (cle, defaut) => {
    try { return JSON.parse(localStorage.getItem(cle)) || defaut; } catch { return defaut; }
  };
  let favoris = lire(CLE_FAV, {});
  let retires = lire(CLE_RETIRES, {});

  (D.favoris || []).forEach(f => {
    const retire = retires[f.url];
    if (retire && (f.favori_le || '') <= retire) return;
    const local = favoris[f.url];
    if (!local || (f.favori_le || '') < (local.favori_le || '')) favoris[f.url] = f;
  });

  const ecrireLocal = () => {
    try {
      localStorage.setItem(CLE_FAV, JSON.stringify(favoris));
      localStorage.setItem(CLE_RETIRES, JSON.stringify(retires));
      return true;
    } catch (e) {
      alert("Favori non enregistré : le stockage du navigateur est plein.");
      return false;
    }
  };
  ecrireLocal();   // fige la fusion vault + navigateur

  // Servie par le serveur local, la page pousse les favoris dans le vault d'elle-même :
  // plus rien à télécharger, plus rien à ramasser. Le bouton « Sauvegarder » ne
  // réapparaît que si cet envoi échoue — mieux vaut un bouton de secours qu'une fausse
  // impression d'être enregistré.
  let envoiKO = false;

  function versLeVault(){
    fetch('/api/favoris', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({favoris: listeFavoris(), retires: retires})
    }).then(r => {
      if (!r.ok) throw new Error(r.status);
      envoiKO = false;
      boutonSauver.hidden = true;
    }).catch(() => {
      envoiKO = true;
      boutonSauver.hidden = vue !== 'favoris';
      boutonSauver.title = "L'enregistrement automatique a échoué — cliquer pour "
        + "télécharger un export, repris à la prochaine synchronisation.";
    });
  }

  const sauverFavoris = () => {
    const ok = ecrireLocal();
    if (LOCAL) versLeVault();
    return ok;
  };

  const listeFavoris = () => Object.values(favoris);

  // ---- développements ----
  // Servie en http://, la page peut demander au serveur local d'appeler le modèle.
  // Ouverte par double-clic sur le fichier, elle ne le peut pas — mais elle affiche
  // quand même les développements déjà produits, embarqués à la construction.
  const SERVI = location.protocol === 'http:' || location.protocol === 'https:';

  // Le site public est servi en https lui aussi : le protocole ne suffit donc pas à
  // savoir si l'API locale est joignable. `LOCAL` désigne le site personnel servi par
  // veille.serveur, `PUBLIC` la page publiée où c'est le lecteur qui apporte sa clé.
  const PUBLIC = !!D.public;
  const LOCAL = SERVI && !PUBLIC;

  const CLE_DEV = 'veille-developpements';
  const dev = Object.assign({}, D.developpements || {}, lire(CLE_DEV, {}));
  const memoriserDev = () => {
    // Le lecteur d'un site public garde ses propres développements : les siens, pas
    // ceux d'un autre. Le quota peut être atteint sur un très gros historique — ce
    // n'est pas une raison pour perdre le développement qu'on vient d'afficher.
    try { localStorage.setItem(CLE_DEV, JSON.stringify(dev)); } catch (e) {}
  };

  const LIBELLES = {
    prio:'Claude & Co', labs:'Labos', outils:'Outils',
    agregateur:'Agrégateurs', analyse:'Analyses', francophone:'Francophone',
    // Ne sert que dans les favoris, qui mêlent actualités et signets. Ailleurs le
    // compteur tombe à zéro et la puce est retirée d'elle-même.
    signets:'Signets'
  };

  // Deux vues étanches. Les signets ne sont pas une catégorie de la veille : ce sont mes
  // propres choix, ils se noieraient parmi quarante actualités par jour. Aucun item
  // n'apparaît dans les deux onglets.
  // Publiquement, il n'y a qu'une vue : les signets et les favoris sont des choix
  // personnels, ils ne sont pas dans les données envoyées.
  // Les digests hebdomadaires ne sont pas publiés ; la raison, chiffres à l'appui, est
  // dans _preparer() côté Python. Elle n'est pas répétée ici : ce commentaire-ci part
  // dans la page publique, et n'a donc pas à nommer ce qu'il protège.
  const SEMAINES = D.semaines || [];
  let semaineActive = 0;

  const VUES = D.public
    ? {veille:'Veille'}
    : {veille:'Veille', semaine:'Semaine', signets:'Mes signets', favoris:'Favoris'};
  const estSignet = i => i.categorie === 'signets';

  // Voies cumulatives : « + Utile » contient l'essentiel, et laisse passer les items
  // non notés — une archive antérieure au scoring ne doit pas disparaître en silence.
  const VOIES = {
    essentiel: {nom:'Essentiel', ok: i => i.voie === 'essentiel'},
    utile:     {nom:'+ Utile',   ok: i => i.voie !== 'bruit'},
    tout:      {nom:'Tout',      ok: () => true}
  };

  let vue = 'veille';
  // Sans aucun item noté, s'ouvrir sur une voie filtrée donnerait une page blanche.
  let voie = D.notes ? 'utile' : 'tout';
  let filtre = 'tout';
  let requete = '';
  let tri = 'pertinence';

  // ---- portée temporelle ----
  // Déclarée ici et non dans le bloc « navigation par jour » plus bas : les compteurs
  // de voie et de sujet sont calculés dès l'initialisation, avant que ce bloc ne soit
  // évalué. Les y laisser donnerait une ReferenceError de zone morte temporelle.
  const DATES = D.jours.map(j => j.date);
  const PAR_DATE = new Map(D.jours.map(j => [j.date, j]));
  let jourActif = DATES[0] || null;
  let dernierJour = jourActif;   // pour revenir d'un aller-retour par « Tout »

  // Une recherche qui ne fouillerait que la journée affichée ne servirait à rien : on
  // cherche justement ce dont on ne sait plus quel jour c'était. Elle porte donc sur
  // toute l'archive, et la barre le dit au lieu de le faire en douce.
  const surToutLArchive = () => jourActif === null || !!requete;

  // Les signets ne sont pas un flux quotidien mais une petite collection choisie : les
  // paginer par jour ferait chercher à l'aveugle. Ils restent affichés en entier.
  const joursAffiches = () => (vue === 'signets' || surToutLArchive())
    ? D.jours : D.jours.filter(j => j.date === jourActif);

  // Déclaré ici, avec la portée, plutôt qu'à côté de `sujetOk` : les compteurs des
  // filtres s'en servent, et ils sont calculés dès l'initialisation.
  const texteOk = i =>
    !requete || [i.titre, i.source_nom, i.extrait, i.analyse, i.justification]
      .join(' ').toLowerCase().includes(requete);

  const tous = D.jours.flatMap(j => j.items);
  const parUrl = new Map(tous.map(i => [i.url, i]));
  // Les favoris ne sont pas un sous-ensemble de la page : certains n'y sont plus.
  // Le lot suit la journée affichée, sans quoi les compteurs des filtres annonceraient
  // l'archive entière au-dessus d'une liste qui ne montre qu'un jour.
  const lot = () => (vue === 'favoris'
    ? listeFavoris()
    : joursAffiches().flatMap(j => j.items)
        .filter(i => estSignet(i) === (vue === 'signets'))
  ).filter(texteOk);

  // Règle unique : un compteur décrit la liste qu'il surplombe. Tous se lisent donc
  // dans la journée affichée ET dans la recherche en cours. Ceux de sujet se lisent en
  // plus dans la voie active : afficher « Labos 14 » alors que la voie n'en laisse
  // passer que 3 serait trompeur. Les compteurs de voie, eux, ignorent le sujet —
  // c'est l'axe primaire. Seuls les onglets échappent à la règle : ils comptent des
  // collections entières, et servent à choisir entre elles.
  const compte = cle => {
    const restants = lot().filter(VOIES[voie].ok);
    return cle === 'tout' ? restants.length
      : cle === 'prio' ? restants.filter(i => i.prioritaire).length
      : restants.filter(i => i.categorie === cle).length;
  };

  function rendreOnglets(){
    onglets.innerHTML = Object.entries(VUES).map(([c, nom]) => {
      const n = c === 'favoris' ? listeFavoris().length
        : c === 'semaine' ? SEMAINES.length
        : tous.filter(i => estSignet(i) === (c === 'signets')).length;
      return `<button class="onglet" role="tab" data-vue="${c}" aria-selected="${c === vue}">`
        + `${nom}<span class="n">${n}</span></button>`;
    }).join('');
  }

  function rendreVoies(){
    barreVoies.innerHTML = '<span class="etiq">Voie</span>' + Object.entries(VOIES)
      .map(([c, v]) => `<button class="puce" data-cle="${c}" aria-pressed="${c === voie}">`
        + `${v.nom}<span class="n">${lot().filter(v.ok).length}</span></button>`)
      .join('');
  }

  const cles = ['tout','prio', ...Object.keys(LIBELLES).filter(c => c !== 'prio')];

  function rendreSujets(){
    // Un sujet vide dans la voie courante est retiré plutôt que laissé à zéro : sinon
    // la rangée se remplit de boutons qui ne donnent rien.
    if (!cles.filter(c => c !== 'tout' && compte(c) > 0).includes(filtre)) filtre = 'tout';
    barre.innerHTML = '<span class="etiq">Sujet</span>' + cles
      .filter(c => c === 'tout' || compte(c) > 0)
      .map(c => `<button class="puce" data-cle="${c}" aria-pressed="${c === filtre}">`
        + `${c === 'tout' ? 'Tout' : LIBELLES[c]}<span class="n">${compte(c)}</span></button>`)
      .join('');
  }
  rendreOnglets();
  rendreVoies();
  rendreSujets();

  onglets.addEventListener('click', e => {
    const b = e.target.closest('.onglet');
    if (!b || b.dataset.vue === vue) return;
    vue = b.dataset.vue;
    // La voie disparaît hors de la veille, et pour la même raison dans les deux cas :
    // un signet comme un favori sont des choix que j'ai faits moi-même, ce n'est pas
    // au score de décider de les masquer. Le sujet, lui, reste utile dans les favoris,
    // qui mélangent actualités et signets ; il n'en a aucun dans l'onglet signets, où
    // tout est de la même catégorie.
    const veille = vue === 'veille';
    const hebdo = vue === 'semaine';
    barreVoies.hidden = !veille;
    barre.hidden = vue === 'signets' || hebdo;
    // Filtrer ou trier une synthèse rédigée n'a aucun sens : les contrôles disparaissent
    // au lieu de rester là sans effet.
    champ.hidden = hebdo;
    selecteurTri.hidden = hebdo;
    boutonSauver.hidden = (LOCAL && !envoiKO) || vue !== 'favoris';
    if (!veille) { voie = 'tout'; filtre = 'tout'; }
    else if (voie === 'tout' && D.notes) voie = 'utile';
    rendreOnglets(); rendreVoies(); rendreSujets(); rendre();
  });

  barreVoies.addEventListener('click', e => {
    const b = e.target.closest('.puce');
    if (!b) return;
    voie = b.dataset.cle;
    barreVoies.querySelectorAll('.puce').forEach(p =>
      p.setAttribute('aria-pressed', p.dataset.cle === voie));
    rendreSujets();   // les compteurs de sujet dépendent de la voie
    rendre();
  });

  barre.addEventListener('click', e => {
    const b = e.target.closest('.puce');
    if (!b) return;
    filtre = b.dataset.cle;
    barre.querySelectorAll('.puce').forEach(p =>
      p.setAttribute('aria-pressed', p.dataset.cle === filtre));
    rendre();
  });

  champ.addEventListener('input', () => {
    requete = champ.value.toLowerCase().trim();
    // Saisir un mot change à la fois la portée — la journée cède la place à l'archive
    // entière — et le décompte de chaque voie. Les deux rangées sont donc redessinées.
    rendreVoies(); rendreSujets(); rendre();
  });

  const selecteurTri = document.getElementById('tri');
  selecteurTri.addEventListener('change', () => { tri = selecteurTri.value; rendre(); });

  // L'ordre par pertinence est déjà celui du fichier, calculé à la génération : Claude
  // d'abord, puis le score. Le tri par date ne s'applique qu'à la demande.
  const ordonner = items => {
    if (tri === 'pertinence') {
      // « Pertinence » n'a rien à classer dans les favoris : ils sont tous pertinents,
      // c'est moi qui les ai choisis. L'ordre qui informe est celui de l'ajout.
      return vue === 'favoris'
        ? [...items].sort((a, b) => (b.favori_le || '').localeCompare(a.favori_le || ''))
        : items;
    }
    const cle = i => i.date || '';
    const trie = [...items].sort((a, b) => cle(b).localeCompare(cle(a)));
    return tri === 'date-inverse' ? trie.reverse() : trie;
  };

  const sujetOk = i =>
    filtre === 'tout' || (filtre === 'prio' ? i.prioritaire : i.categorie === filtre);
  const garde = i =>
      vue === 'favoris' ? sujetOk(i) && texteOk(i)
    : vue === 'signets' ? estSignet(i) && texteOk(i)
    : !estSignet(i) && VOIES[voie].ok(i) && sujetOk(i) && texteOk(i);

  const heure = iso => {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  };

  const dateComplete = iso => {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString('fr-FR', {day:'numeric', month:'short', year:'numeric'});
  };

  const echapper = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };

  // Classe de mise en avant du verdict : « Utile » et « À tester » sont des actions,
  // « Pour info » et « Peu d'intérêt » ne méritent pas d'attirer l'œil.
  const RANG = {'Utile':'v-fort', 'À tester':'v-fort', 'Pour info':'v-moyen', "Peu d'intérêt":'v-faible'};

  const domaine = url => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; } };

  function carteSignet(i){
    // Date complète, et non l'heure seule : les signets remontent à plusieurs années,
    // et ils sont archivés au jour de leur import, pas à celui du tweet.
    const q = dateComplete(i.date);
    return `<details class="item signet${i.prioritaire ? ' prio' : ''}${lus.has(i.url) ? ' lu' : ''}"`
      + ` data-url="${echapper(i.url)}"><summary>`
      + `<span class="t">${echapper(i.titre)}</span>`
      + `<span class="ligne"><span class="src">${echapper(i.source_nom)}</span>`
      + (q ? `<span>${q}</span>` : '')
      + (i.verdict ? `<span class="verdict ${RANG[i.verdict] || 'v-moyen'}">${echapper(i.verdict)}</span>` : '')
      + (i.score != null ? `<span class="score ${i.voie}" title="Intérêt estimé pour ton profil (0 à 1)">${i.score.toFixed(2)}</span>` : '')
      + `</span></summary><div class="deplie">`
      + (i.analyse ? `<p class="analyse">${echapper(i.analyse)}</p>` : '')
      + (i.justification ? `<p class="pourtoi"><b>Pour toi</b> — ${echapper(i.justification)}</p>` : '')
      + `<div class="pieds">`
      + (i.cible ? `<a href="${echapper(i.cible)}" target="_blank" rel="noopener">↗ ${echapper(domaine(i.cible))}</a>` : '')
      + `<a href="${echapper(i.url)}" target="_blank" rel="noopener">voir le tweet</a>`
      + `</div></div></details>`;
  }

  function etoile(i){
    const marque = !!favoris[i.url];
    return `<button class="etoile" data-url="${echapper(i.url)}" aria-pressed="${marque}"`
      + ` title="${marque ? 'Retirer des favoris' : 'Mettre en favori'}"`
      + ` aria-label="${marque ? 'Retirer des favoris' : 'Mettre en favori'}">`
      + `${marque ? '★' : '☆'}</button>`;
  }

  function boutonPlus(i){
    const fait = !!dev[i.url];
    return `<button class="plus" data-url="${echapper(i.url)}" data-fait="${fait}"`
      + ` aria-expanded="false" aria-label="Développer"`
      + ` title="${fait ? 'Voir le développement' : "Développer : résumé complet et exemple d'usage"}">`
      + `+</button>`;
  }

  function carte(i){
    return `<div class="enveloppe">`
      + ((estSignet(i) && i.analyse) ? carteSignet(i) : carteLien(i))
      + boutonPlus(i) + (PUBLIC ? '' : etoile(i))
      + `<div class="developpement" hidden></div></div>`;
  }

  function carteLien(i){
    const h = heure(i.date);
    return `<a class="item${i.prioritaire ? ' prio' : ''}${lus.has(i.url) ? ' lu' : ''}"`
      + ` href="${echapper(i.url)}" target="_blank" rel="noopener" data-url="${echapper(i.url)}">`
      + `<h3>${echapper(i.titre)}</h3>`
      + `<div class="ligne"><span class="src">${echapper(i.source_nom)}</span>`
      + (h ? `<span>${h}</span>` : '')
      + (i.categorie && !estSignet(i) ? `<span class="cat">${echapper(LIBELLES[i.categorie] || i.categorie)}</span>` : '')
      // Inutile dans l'onglet signets : tout y est un tweet, la mention n'informe plus.
      + (i.titre_utilisateur && !estSignet(i) ? `<span class="avis" title="Titre rédigé par un utilisateur : affirmation, pas fait vérifié">titre d'utilisateur</span>` : '')
      + (i.score != null ? `<span class="score ${i.voie}" title="Intérêt estimé pour ton profil (0 à 1)">${i.score.toFixed(2)}</span>` : '')
      + `</div>`
      + (i.extrait ? `<p class="extrait">${echapper(i.extrait)}</p>` : '')
      + `</a>`;
  }

  // Les favoris s'étalent sur des mois : les regrouper par journée émietterait la
  // liste en sections d'un seul élément. Une section unique, et le tri fait le reste.
  function sectionFavoris(){
    const items = ordonner(listeFavoris().filter(garde));
    if (!items.length) return {n: 0, html: ''};
    return {
      n: items.length,
      html: `<section class="jour"><h2>Mes favoris<span class="n">${items.length}</span></h2>`
        + items.map(carte).join('') + `</section>`
    };
  }

  // ---- navigation par jour -----------------------------------------------
  // Dix-neuf journées empilées, c'est plusieurs milliers de pixels de défilement pour
  // atteindre avant-hier — alors que l'usage courant est de lire le jour même. La page
  // s'ouvre donc sur la journée la plus récente. `jourActif === null` rétablit
  // l'empilement complet, gardé sous le bouton « Tout » : la vue d'ensemble reste utile
  // pour balayer une semaine, elle ne doit simplement plus être le défaut.
  let moisVu = null;

  const navJour = document.getElementById('nav-jour');
  const calendrier = document.getElementById('calendrier');
  const btDate = document.getElementById('datejour');

  // Compté dans la voie et le sujet actifs, comme les autres compteurs de la page :
  // annoncer 138 sur une journée pour n'en afficher que 12 serait trompeur.
  const compteJour = j =>
    j.items.filter(i => !estSignet(i) && VOIES[voie].ok(i) && sujetOk(i)).length;

  const cleDate = (an, mois, jour) =>
    `${an}-${String(mois + 1).padStart(2, '0')}-${String(jour).padStart(2, '0')}`;

  function rendreNavJour(){
    navJour.hidden = vue !== 'veille';
    if (navJour.hidden) { fermerCalendrier(); return; }

    const i = DATES.indexOf(jourActif);
    const large = surToutLArchive();
    document.getElementById('prec').disabled = large || i < 0 || i >= DATES.length - 1;
    document.getElementById('suiv').disabled = large || i <= 0;
    btDate.disabled = !!requete;

    const jours = `${DATES.length} jour${DATES.length > 1 ? 's' : ''}`;
    btDate.innerHTML = requete
      ? `Recherche sur ${jours}`
      : jourActif === null
        ? `Toutes les journées<span class="n">${DATES.length}</span>`
        : `${echapper(PAR_DATE.get(jourActif).libelle)}`
          + `<span class="n">${compteJour(PAR_DATE.get(jourActif))}</span>`;
    document.getElementById('tousjours').setAttribute('aria-pressed', jourActif === null);
  }

  const allerA = date => {
    jourActif = date;
    if (date !== null) dernierJour = date;
    fermerCalendrier();
    // Les nombres des deux rangées de filtres viennent de changer avec la journée.
    rendreVoies(); rendreSujets(); rendre();
    window.scrollTo(0, 0);
  };

  const decaler = n => {
    const i = DATES.indexOf(jourActif) + n;
    if (i >= 0 && i < DATES.length) allerA(DATES[i]);
  };

  function fermerCalendrier(){
    calendrier.hidden = true;
    btDate.setAttribute('aria-expanded', 'false');
  }

  function rendreCalendrier(){
    const {an, mois} = moisVu;
    const premier = new Date(an, mois, 1);
    const decalage = (premier.getDay() + 6) % 7;              // semaine commençant lundi
    const nb = new Date(an, mois + 1, 0).getDate();
    const courant = `${an}-${String(mois + 1).padStart(2, '0')}`;

    let cases = '';
    for (let k = 0; k < decalage; k++) cases += `<span class="cal-case"></span>`;
    for (let d = 1; d <= nb; d++) {
      const cle = cleDate(an, mois, d);
      const j = PAR_DATE.get(cle);
      cases += j
        ? `<button class="cal-case plein" data-date="${cle}"`
          + `${cle === jourActif ? ' aria-current="date"' : ''}>`
          + `${d}<span class="n">${compteJour(j)}</span></button>`
        : `<button class="cal-case" disabled>${d}</button>`;
    }

    calendrier.innerHTML =
      `<div class="cal-tete">`
      + `<button class="fleche" data-mois="-1" aria-label="Mois précédent"`
      + `${DATES[DATES.length - 1].slice(0, 7) < courant ? '' : ' disabled'}>&lsaquo;</button>`
      + `<strong>${premier.toLocaleDateString('fr-FR', {month:'long', year:'numeric'})}</strong>`
      + `<button class="fleche" data-mois="1" aria-label="Mois suivant"`
      + `${DATES[0].slice(0, 7) > courant ? '' : ' disabled'}>&rsaquo;</button>`
      + `</div><div class="cal-grille">`
      + ['lun','mar','mer','jeu','ven','sam','dim'].map(x => `<span class="jsem">${x}</span>`).join('')
      + cases + `</div>`;
  }

  document.getElementById('prec').addEventListener('click', () => decaler(1));
  document.getElementById('suiv').addEventListener('click', () => decaler(-1));

  document.getElementById('tousjours').addEventListener('click', () => {
    allerA(jourActif === null ? (dernierJour || DATES[0] || null) : null);
  });

  btDate.addEventListener('click', () => {
    if (!calendrier.hidden) return fermerCalendrier();
    const [a, m] = (jourActif || DATES[0] || '').split('-').map(Number);
    if (!a) return;
    moisVu = {an: a, mois: m - 1};
    rendreCalendrier();
    calendrier.hidden = false;
    btDate.setAttribute('aria-expanded', 'true');
  });

  calendrier.addEventListener('click', e => {
    const saut = e.target.closest('[data-mois]');
    if (saut) {
      const d = new Date(moisVu.an, moisVu.mois + Number(saut.dataset.mois), 1);
      moisVu = {an: d.getFullYear(), mois: d.getMonth()};
      return rendreCalendrier();
    }
    const case_ = e.target.closest('.cal-case.plein');
    if (case_) allerA(case_.dataset.date);
  });

  document.addEventListener('click', e => {
    if (!calendrier.hidden && !(e.target instanceof Element && e.target.closest('.nav-jour')))
      fermerCalendrier();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !calendrier.hidden) return fermerCalendrier();
    // Les flèches appartiennent au champ de saisie tant qu'on y écrit. `closest`
    // n'existe que sur un Element : la cible d'un keydown peut être le document.
    if (e.target instanceof Element && e.target.closest('input, select, textarea')) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const recule = e.key === 'ArrowLeft';
    if (vue === 'semaine') {
      e.preventDefault();
      return allerASemaine(semaineActive + (recule ? 1 : -1));
    }
    if (vue !== 'veille' || surToutLArchive()) return;
    e.preventDefault();
    decaler(recule ? 1 : -1);
  });

  // ---- navigation hebdomadaire ----------------------------------------------
  // Même barre que pour les jours, mais une liste plutôt qu'un calendrier : une
  // semaine n'a pas de place dans une grille de mois, et il y en aura toujours peu.
  const navSemaine = document.getElementById('nav-semaine');
  const listeSemaines = document.getElementById('liste-semaines');
  const btSemaine = document.getElementById('sem-libelle');

  const fermerListeSemaines = () => {
    listeSemaines.hidden = true;
    btSemaine.setAttribute('aria-expanded', 'false');
  };

  function rendreNavSemaine(){
    navSemaine.hidden = vue !== 'semaine';
    if (navSemaine.hidden) return fermerListeSemaines();
    document.getElementById('sem-prec').disabled = semaineActive >= SEMAINES.length - 1;
    document.getElementById('sem-suiv').disabled = semaineActive <= 0;
    btSemaine.disabled = SEMAINES.length < 2;
    btSemaine.textContent = SEMAINES.length
      ? SEMAINES[semaineActive].libelle
      : 'Aucune semaine archivée';
  }

  const allerASemaine = i => {
    if (i < 0 || i >= SEMAINES.length) return;
    semaineActive = i;
    fermerListeSemaines();
    rendre();
    window.scrollTo(0, 0);
  };

  document.getElementById('sem-prec').addEventListener('click', () => allerASemaine(semaineActive + 1));
  document.getElementById('sem-suiv').addEventListener('click', () => allerASemaine(semaineActive - 1));

  btSemaine.addEventListener('click', () => {
    if (!listeSemaines.hidden) return fermerListeSemaines();
    listeSemaines.innerHTML = SEMAINES.map((s, i) =>
      `<button role="option" data-i="${i}" aria-current="${i === semaineActive}">`
      + `${echapper(s.libelle)}</button>`).join('');
    listeSemaines.hidden = false;
    btSemaine.setAttribute('aria-expanded', 'true');
  });

  listeSemaines.addEventListener('click', e => {
    const b = e.target.closest('[data-i]');
    if (b) allerASemaine(Number(b.dataset.i));
  });

  document.addEventListener('click', e => {
    if (!listeSemaines.hidden && !(e.target instanceof Element && e.target.closest('#nav-semaine')))
      fermerListeSemaines();
  });

  // Un renvoi du digest hebdo vers une journée bascule sur elle, dans l'onglet Veille.
  // C'est ce qui relie les deux vues : la synthèse dit quoi, la journée montre d'où.
  flux.addEventListener('click', e => {
    const b = e.target instanceof Element && e.target.closest('.lien-jour');
    if (!b || b.disabled) return;
    vue = 'veille';
    barreVoies.hidden = false;
    barre.hidden = false;
    champ.hidden = false;
    selecteurTri.hidden = false;
    boutonSauver.hidden = true;
    rendreOnglets();
    allerA(b.dataset.date);
  });

  function rendreSemaine(){
    if (!SEMAINES.length) {
      flux.innerHTML = `<p class="vide">Aucun digest hebdomadaire pour l'instant.<br><br>`
        + `Le premier est écrit le lundi matin qui suit une semaine complète, `
        + `ou à la demande avec <code>python .veille/run_weekly.py</code>.</p>`;
      return resumer(0, 'rien à lire', 'semaine');
    }
    const s = SEMAINES[semaineActive];
    flux.innerHTML = `<section class="jour hebdo"><div class="corps">${s.html}</div></section>`;
    // Une journée sortie de la fenêtre d'affichage n'est plus atteignable : le renvoi
    // reste lisible, mais cesse d'être un bouton qui ne mènerait nulle part.
    flux.querySelectorAll('.lien-jour').forEach(b => {
      if (!PAR_DATE.has(b.dataset.date)) b.disabled = true;
    });
    resumer(SEMAINES.length, s.libelle, 'semaine');
  }

  function rendre(){
    // Les deux barres se rafraîchissent avant tout retour anticipé : chacune se masque
    // d'elle-même hors de sa vue, encore faut-il qu'on l'appelle.
    rendreNavJour();
    rendreNavSemaine();
    if (vue === 'semaine') return rendreSemaine();
    if (vue === 'favoris') return rendreFavoris();
    const portee = joursAffiches();
    let visibles = 0;
    const html = portee.map(j => {
      const items = ordonner(j.items.filter(garde));
      if (!items.length) return '';
      visibles += items.length;
      // Le digest rédigé porte sur la veille : il n'a rien à faire dans les signets.
      const digests = (vue === 'veille' && filtre === 'tout' && !requete)
        ? j.digests.map(d => `<details class="digest"${j === portee[0] ? ' open' : ''}>`
            + `<summary>Digest${d.heure ? ' de ' + d.heure : ''}</summary>`
            + `<div class="corps">${d.html}</div></details>`).join('')
        : '';
      return `<section class="jour"><h2>${echapper(j.libelle)}`
        + `<span class="n">${items.length}</span></h2>${digests}`
        + items.map(carte).join('') + `</section>`;
    }).join('');

    const aucunSignet = vue === 'signets' && !tous.some(estSignet);
    // Sur une seule journée, le titre de section répète mot pour mot la barre de
    // navigation juste au-dessus. Deux fois la même date, c'est une de trop.
    flux.classList.toggle('un-jour', vue === 'veille' && !surToutLArchive());
    flux.innerHTML = html || (aucunSignet
      ? `<p class="vide">Aucun signet relevé pour l'instant.<br><br>`
        + `Lancer une fois <code>python run_signets.py --connexion</code> pour ouvrir la `
        + `session X, puis le relevé se fait tout seul à chaque synchronisation.</p>`
      : portee.length === 1 && !requete
        ? `<p class="vide">Rien ce jour-là dans cette voie.<br><br>`
          + `Élargir la voie ci-dessus, ou passer à la journée précédente avec &lsaquo;.</p>`
        : `<p class="vide">Aucun élément ne correspond.</p>`);
    resumer(visibles, (vue === 'signets' || surToutLArchive())
      ? `${D.jours.length} jour${D.jours.length > 1 ? 's' : ''}`
      : PAR_DATE.get(jourActif).libelle);
  }

  function rendreFavoris(){
    const section = sectionFavoris();
    flux.innerHTML = section.html || (listeFavoris().length
      ? `<p class="vide">Aucun favori ne correspond.</p>`
      : `<p class="vide">Aucun favori pour l'instant.<br><br>`
        + `Cliquer sur l'étoile ☆ en haut d'un élément, dans n'importe quel onglet, `
        + `pour le mettre de côté. Il restera ici même quand sa journée sera sortie `
        + `de l'archive.</p>`);
    resumer(section.n, 'mis de côté');
  }

  const resumer = (n, suffixe, unite = 'élément') => {
    document.getElementById('resume').textContent =
      `${n} ${unite}${n > 1 ? 's' : ''} · ${suffixe} · maj ${D.genere}`;
  };

  const itemPour = url => parUrl.get(url) || favoris[url] || null;

  // Transposition du convertisseur markdown du générateur : sur la page publique, le
  // texte arrive du modèle directement dans le navigateur, il n'est jamais passé par
  // Python. Même sous-ensemble, mêmes règles — titres, listes, gras, code, blocs.
  function markdownHtml(md){
    const sortie = [];
    let dansListe = false, dansBloc = false;
    const enligne = t => t
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
               '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(?!\s)([^*\n]+?)(?<!\s)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');

    for (const ligne of String(md).split('\n')) {
      const brute = ligne.replace(/\s+$/, '');

      if (brute.trim().startsWith('```')) {
        if (dansBloc) sortie.push('</code></pre>');
        else {
          if (dansListe) { sortie.push('</ul>'); dansListe = false; }
          sortie.push('<pre><code>');
        }
        dansBloc = !dansBloc;
        continue;
      }
      if (dansBloc) { sortie.push(echapper(brute)); continue; }

      const nue = echapper(brute.trim());
      if (!nue) { if (dansListe) { sortie.push('</ul>'); dansListe = false; } continue; }

      const puce = nue.match(/^(?:[-*]|\d+\.)\s+(.*)$/);
      if (puce) {
        if (!dansListe) { sortie.push('<ul>'); dansListe = true; }
        sortie.push('<li>' + enligne(puce[1]) + '</li>');
        continue;
      }
      if (dansListe) { sortie.push('</ul>'); dansListe = false; }

      const titre = nue.match(/^(#{1,6})\s+(.*)$/);
      if (titre) {
        const niveau = Math.min(titre[1].length + 1, 6);
        sortie.push(`<h${niveau}>` + enligne(titre[2]) + `</h${niveau}>`);
        continue;
      }
      if (/^-{3,}$/.test(nue)) { sortie.push('<hr>'); continue; }
      sortie.push('<p>' + enligne(nue) + '</p>');
    }

    if (dansListe) sortie.push('</ul>');
    if (dansBloc) sortie.push('</code></pre>');
    return sortie.join('\n');
  }

  const rendu = url => dev[url].html
    + `<div class="pied-dev"><span>Développé le ${(dev[url].genere || '').slice(0, 10)}</span>`
    + ((LOCAL || PUBLIC) ? `<button class="refaire" data-url="${echapper(url)}">refaire</button>` : '')
    + `</div>`;

  // ---- clé du lecteur (site public) ----
  // Elle ne quitte jamais ce navigateur : la page appelle Gemini directement, et il
  // n'existe aucun serveur à qui elle pourrait être envoyée. C'est écrit sur le
  // panneau, parce que personne ne devrait coller une clé sans savoir où elle va.
  const CLE_GEMINI = 'veille-cle-gemini';
  const laCle = () => { try { return localStorage.getItem(CLE_GEMINI) || ''; } catch { return ''; } };
  const boutonCle = document.getElementById('cle');
  const panneauCle = document.getElementById('panneau-cle');

  function rendrePanneauCle(){
    const posee = !!laCle();
    boutonCle.dataset.active = posee;
    boutonCle.textContent = posee ? 'Clé ✓' : 'Clé API';
    panneauCle.innerHTML = `<div class="boite">`
      + `<h2>Développer un article avec votre clé</h2>`
      + `<p>Le bouton <b>+</b> de chaque carte demande à Gemini un résumé complet de `
      + `l'article et un exemple d'usage. L'appel part <b>de votre navigateur</b>, avec `
      + `votre clé : elle est enregistrée ici seulement, elle n'est envoyée à aucun `
      + `serveur de ce site, et l'auteur du site ne la voit jamais.</p>`
      + `<p>Une clé gratuite s'obtient sur `
      + `<a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">`
      + `aistudio.google.com/apikey</a>. Les appels sont décomptés de votre quota.</p>`
      + `<div class="rang">`
      + `<input id="saisie-cle" type="password" autocomplete="off" spellcheck="false"`
      + ` placeholder="${posee ? 'Clé enregistrée — en saisir une autre pour la remplacer' : 'AIza…'}">`
      + `<button class="principal" id="poser-cle">Enregistrer</button>`
      + (posee ? `<button id="oublier-cle">Effacer</button>` : '')
      + `</div>`
      + `<p class="note">Rien d'autre n'est conservé : le site est une page statique, `
      + `sans compte, sans traceur et sans base de données.</p>`
      + `</div>`;
  }

  if (PUBLIC) {
    boutonCle.hidden = false;
    rendrePanneauCle();
    boutonCle.addEventListener('click', () => {
      panneauCle.hidden = !panneauCle.hidden;
      if (!panneauCle.hidden) document.getElementById('saisie-cle').focus();
    });
    panneauCle.addEventListener('click', e => {
      if (e.target.id === 'poser-cle') {
        const valeur = document.getElementById('saisie-cle').value.trim();
        if (!valeur) return;
        try { localStorage.setItem(CLE_GEMINI, valeur); } catch (e) {}
        rendrePanneauCle();
        panneauCle.hidden = true;
      }
      if (e.target.id === 'oublier-cle') {
        try { localStorage.removeItem(CLE_GEMINI); } catch (e) {}
        rendrePanneauCle();
      }
    });

    document.getElementById('bandeau').hidden = false;
    document.getElementById('bandeau').innerHTML =
      `Veille quotidienne sur l'IA — collectée, triée et résumée automatiquement. `
      + `Le score de chaque élément mesure son intérêt <b>pour la ligne éditoriale du `
      + `site</b> (Claude et Claude Code d'abord, puis les autres modèles et l'agentic `
      + `coding), et non son importance générale.`;
    // Un seul onglet : la barre n'aurait rien à faire.
    document.getElementById('onglets').hidden = true;
  }

  async function developperAvecCle(url, panneau){
    const cle = laCle();
    if (!cle) {
      panneau.innerHTML = `<p class="attente">Il faut d'abord renseigner une clé Gemini `
        + `— bouton <b>Clé API</b> en haut de la page. Elle reste dans ce navigateur.</p>`;
      panneauCle.hidden = false;
      return;
    }

    const item = itemPour(url);
    if (!item) { panneau.innerHTML = `<p class="attente echec">Article introuvable.</p>`; return; }
    const cible = (item.cible || '').trim() || url;

    // Le navigateur ne peut pas lire un site tiers : c'est le Worker qui va chercher le
    // texte. Sans lui, on développe à partir du titre et de l'extrait — le modèle le
    // sait, les consignes lui demandent de le dire plutôt que de broder.
    let contenu = '';
    if (D.worker) {
      panneau.innerHTML = `<p class="attente">Lecture de l'article…</p>`;
      try {
        const r = await fetch(D.worker + '/?url=' + encodeURIComponent(cible));
        const d = await r.json();
        contenu = d.texte || '';
      } catch (e) { contenu = ''; }
    }

    panneau.innerHTML = `<p class="attente">Rédaction par Gemini…</p>`;
    try {
      const corps = await appelerGemini(cle, promptDeveloppement(item, contenu));
      dev[url] = {html: markdownHtml(corps), genere: new Date().toISOString()};
      memoriserDev();
      panneau.innerHTML = rendu(url);
      marquerFait(url);
    } catch (e) {
      panneau.innerHTML = `<p class="attente echec">Échec : ${echapper(String(e.message || e))}</p>`;
    }
  }

  function promptDeveloppement(item, contenu){
    const lignes = [`Titre : ${item.titre || ''}`, `Source : ${item.source_nom || ''}`];
    if (item.date) lignes.push(`Date : ${item.date}`);
    lignes.push(`URL : ${item.url || ''}`);
    if (item.extrait) lignes.push(`\nExtrait collecté :\n${item.extrait}`);
    lignes.push(`\nContenu de la page :\n${contenu || '(non récupéré)'}`);
    return `Tu produis une veille IA personnelle pour ce profil :\n\n${D.profil}\n\n`
      + `${D.consignes}\n\nVoici l'article :\n\n` + lignes.join('\n');
  }

  async function appelerGemini(cle, prompt){
    const reponse = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${D.modele}:generateContent`,
      {
        method: 'POST',
        headers: {'x-goog-api-key': cle, 'Content-Type': 'application/json'},
        body: JSON.stringify({
          contents: [{parts: [{text: prompt}]}],
          generationConfig: {maxOutputTokens: 12000, temperature: 0.3}
        })
      }
    );
    const donnees = await reponse.json().catch(() => ({}));
    if (!reponse.ok) {
      const message = (donnees.error && donnees.error.message) || ('HTTP ' + reponse.status);
      throw new Error(reponse.status === 400 ? 'clé refusée — ' + message : message);
    }
    const parts = ((donnees.candidates || [])[0] || {}).content;
    const texte = ((parts && parts.parts) || []).map(p => p.text || '').join('').trim();
    if (!texte) throw new Error('réponse vide du modèle');
    return texte;
  }

  const marquerFait = url =>
    document.querySelectorAll(`.plus[data-url="${CSS.escape(url)}"]`)
      .forEach(b => { b.dataset.fait = 'true'; b.title = 'Voir le développement'; });

  async function developper(bouton, refaire){
    const url = bouton.dataset.url;
    const panneau = bouton.closest('.enveloppe').querySelector('.developpement');

    // Replier n'a de sens que s'il y a quelque chose à replier. Sur un panneau resté en
    // attente ou en échec — clé manquante, appel raté — le clic suivant doit réessayer :
    // c'est ce qu'on fait spontanément après avoir renseigné sa clé.
    if (!refaire && bouton.getAttribute('aria-expanded') === 'true' && dev[url]) {
      panneau.hidden = true;
      bouton.setAttribute('aria-expanded', 'false');
      bouton.textContent = '+';
      return;
    }

    panneau.hidden = false;
    bouton.setAttribute('aria-expanded', 'true');
    bouton.textContent = '\u2212';

    if (dev[url] && !refaire) { panneau.innerHTML = rendu(url); return; }
    if (PUBLIC) return developperAvecCle(url, panneau);
    if (!LOCAL) {
      panneau.innerHTML = `<p class="attente">Ouvrir le site par le raccourci `
        + `<code>ouvrir_site.cmd</code> pour développer un article : la page a besoin `
        + `du serveur local, qui seul détient la clé de l'API.</p>`;
      return;
    }

    const item = itemPour(url);
    if (!item) { panneau.innerHTML = `<p class="attente echec">Article introuvable.</p>`; return; }

    // Lecture de la page puis rédaction : une vingtaine de secondes. Le dire, plutôt
    // que de laisser un panneau vide qui donne l'impression d'un bouton mort.
    panneau.innerHTML = `<p class="attente">Lecture de l'article et rédaction…</p>`;
    try {
      const reponse = await fetch('/api/developper', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({item: item, refaire: !!refaire})
      });
      const donnees = await reponse.json();
      if (!reponse.ok || donnees.erreur) throw new Error(donnees.erreur || reponse.status);
      dev[url] = donnees;
      panneau.innerHTML = rendu(url);
      marquerFait(url);
    } catch (e) {
      panneau.innerHTML = `<p class="attente echec">Échec : ${echapper(String(e.message || e))}`
        + `<br>Détail dans <code>.veille/state/serveur.log</code>.</p>`;
    }
  }

  function basculer(url){
    if (favoris[url]) {
      delete favoris[url];
      retires[url] = new Date().toISOString();
    } else {
      const item = parUrl.get(url);
      if (!item) return;
      favoris[url] = Object.assign({}, item, {favori_le: new Date().toISOString()});
      delete retires[url];
    }
    sauverFavoris();
    rendreOnglets();
    // Hors de l'onglet Favoris, un rendu complet replierait les signets ouverts et
    // ramènerait la page en haut. On ne retouche donc que le bouton concerné.
    if (vue === 'favoris') { rendreSujets(); rendre(); return; }
    flux.querySelectorAll(`.etoile[data-url="${CSS.escape(url)}"]`).forEach(b => {
      const marque = !!favoris[url];
      b.setAttribute('aria-pressed', marque);
      b.title = b.ariaLabel = marque ? 'Retirer des favoris' : 'Mettre en favori';
      b.textContent = marque ? '★' : '☆';
    });
  }

  flux.addEventListener('click', e => {
    const bouton = e.target.closest('.etoile');
    if (bouton) { e.preventDefault(); basculer(bouton.dataset.url); return; }
    const plus = e.target.closest('.plus');
    if (plus) { e.preventDefault(); developper(plus, false); return; }
    const refaire = e.target.closest('.refaire');
    if (refaire) {
      e.preventDefault();
      developper(refaire.closest('.enveloppe').querySelector('.plus'), true);
      return;
    }
    const carte = e.target.closest('.item');
    if (!carte) return;
    // Déplier un signet n'est pas le lire : on ne l'estompe qu'une fois parti vers la
    // ressource. Sinon le contenu qu'on vient d'ouvrir s'afficherait grisé.
    if (carte.classList.contains('signet') && !e.target.closest('a')) return;
    marquer(carte.dataset.url);
    carte.classList.add('lu');
  });

  // La page est un fichier local : elle ne peut rien écrire dans le vault. Elle produit
  // donc un fichier de téléchargement, que la synchronisation suivante ramasse — même
  // circuit que l'export des signets. Les retraits partent avec, sans quoi l'import
  // ressusciterait ce qui vient d'être enlevé.
  boutonSauver.addEventListener('click', () => {
    const charge = {
      genere: new Date().toISOString(),
      favoris: listeFavoris(),
      retires: retires
    };
    const blob = new Blob([JSON.stringify(charge, null, 1)], {type: 'application/json'});
    const lien = document.createElement('a');
    lien.href = URL.createObjectURL(blob);
    lien.download = 'favoris-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.json';
    document.body.appendChild(lien);
    lien.click();
    lien.remove();
    setTimeout(() => URL.revokeObjectURL(lien.href), 5000);

    boutonSauver.textContent = 'Sauvegardé ✓';
    setTimeout(() => { boutonSauver.textContent = 'Sauvegarder'; }, 2500);
  });

  // Des favoris ont pu être posés pendant que le serveur ne tournait pas : ils partent
  // au premier chargement servi, sans rien demander.
  if (LOCAL) {
    boutonSauver.hidden = true;
    if (listeFavoris().length || Object.keys(retires).length) versLeVault();
  }

  rendre();
})();
</script>
</body>
</html>
"""
