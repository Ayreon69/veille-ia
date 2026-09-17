"""
Récupération des signets X, par pilotage du navigateur.

Pourquoi pas l'API officielle : depuis le 6 février 2026, X a remplacé ses paliers par
du paiement à l'usage et il n'existe plus de tier gratuit. L'endpoint signets reste
accessible (0,005 $ par post lu), mais il exige un compte développeur approuvé et un
jeton OAuth 2.0 qui **tourne à chaque rafraîchissement** — donc à réécrire à chaque
exécution, sous peine de rupture silencieuse au bout de quelques jours. C'est le mode
de panne qui avait déjà disqualifié `claude -p`.

Contrepartie assumée de ce choix : l'extraction automatisée est contraire aux CGU de X,
même sur ses propres données, et elle casse quand X remanie sa page.

SÉCURITÉ — le profil de navigateur contient les cookies de session X, qui valent un mot
de passe. Il vit donc **hors du vault**, dans %LOCALAPPDATA%, pour qu'aucune erreur de
`git add` ne puisse l'envoyer sur GitHub.
"""
import html
import json
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config

URL_SIGNETS = "https://x.com/i/bookmarks"

# Canal du navigateur. « chrome » utilise le Chrome installé sur la machine ; vide, le
# Chromium livré par Playwright. Le Chrome réel est préféré : c'est un binaire signé,
# à jour, avec l'empreinte d'un navigateur ordinaire — là où le Chromium de Playwright
# est un build de test que X traite plus durement. Constaté le 09/08/2026 : la connexion
# depuis le Chromium fourni est refusée d'emblée.
CANAL = os.getenv("VEILLE_CANAL_NAVIGATEUR", "chrome").strip().lower()

# Pages qui signalent une absence de session, quel que soit le chemin emprunté.
_MARQUEURS_DECONNECTE = ("/i/flow/login", "/login", "/i/jf/onboarding", "/i/flow/signup")

# Hors du dépôt, délibérément : voir l'avertissement de sécurité ci-dessus.
PROFIL_NAVIGATEUR = Path(
    os.getenv("VEILLE_PROFIL_X")
    or Path(os.getenv("LOCALAPPDATA", Path.home())) / "veille-x-profile"
)

# Domaines dont un lien n'apporte rien : ce sont des renvois internes à X.
_LIENS_IGNORES = ("x.com", "twitter.com", "t.co")


class SessionAbsente(RuntimeError):
    """Le profil n'a pas de session X valide."""


def _options_lancement(headless: bool) -> dict:
    """Arguments communs aux deux modes de lancement."""
    options = {
        "user_data_dir": str(PROFIL_NAVIGATEUR),
        "headless": headless,
        "viewport": {"width": 1280, "height": 1400},
        "locale": "fr-FR",
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    if CANAL and CANAL != "chromium":
        # Avec le Chrome réel, ne pas forcer le User-Agent : le sien est cohérent avec
        # le reste de son empreinte, un UA bricolé ne ferait que créer une incohérence.
        options["channel"] = CANAL
    else:
        options["user_agent"] = config.USER_AGENT
    return options


def _deconnecte(page) -> bool:
    """Vrai si la page affiche un parcours de connexion plutôt que le contenu."""
    return any(marqueur in page.url for marqueur in _MARQUEURS_DECONNECTE)


def _texte(locator) -> str:
    """Texte d'un locator, chaîne vide s'il est absent."""
    try:
        return locator.first.inner_text(timeout=2000).strip()
    except Exception:  # noqa: BLE001 — un champ manquant n'est pas une erreur
        return ""


# La cible réelle, dans la page intermédiaire servie par t.co.
_CIBLE_TCO = re.compile(r'URL=([^"\'<>\s]+)', re.I)
_TITRE_TCO = re.compile(r"<title>([^<]+)</title>", re.I)


def _resoudre(url: str) -> str:
    """Développe un lien t.co vers sa cible réelle.

    X n'expose que le lien raccourci dans le DOM. Et t.co ne redirige pas en HTTP : il
    répond 200 avec une page intermédiaire de 250 octets, où la vraie adresse figure dans
    un `meta refresh` et dans le titre. Suivre les redirections ne suffit donc pas — c'est
    ce qui faisait retomber tous les liens sur le domaine t.co, écarté comme interne, et
    disparaître en silence.
    """
    if "t.co/" not in url:
        return url

    try:
        reponse = httpx.get(
            url,
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": config.USER_AGENT},
        )
    except httpx.HTTPError:
        return url

    finale = str(reponse.url)
    if urlparse(finale).netloc.lower().removeprefix("www.") != "t.co":
        return finale  # une vraie redirection a eu lieu

    trouve = _CIBLE_TCO.search(reponse.text) or _TITRE_TCO.search(reponse.text)
    return html.unescape(trouve.group(1)).strip() if trouve else url


def _nettoyer_liens(hrefs: list[str]) -> list[str]:
    """Développe les t.co et écarte les renvois internes à X."""
    sortants = []
    for href in dict.fromkeys(hrefs):  # dédoublonne en gardant l'ordre
        cible = _resoudre(href)
        domaine = urlparse(cible).netloc.lower().removeprefix("www.")
        if domaine and not domaine.endswith(_LIENS_IGNORES):
            sortants.append(cible)
    return sortants


def _titre(texte: str, auteur: str) -> str:
    """Le titre d'un signet, c'est le début du tweet : il n'y en a pas d'autre."""
    titre = re.sub(r"\s+", " ", texte or "").strip()
    if len(titre) > 110:
        titre = titre[:110].rsplit(" ", 1)[0] + "…"
    return titre or (f"Signet de {auteur}" if auteur else "Signet X")


def _liens_utiles(article) -> list[str]:
    """Liens sortants d'un tweet, hors renvois internes à X."""
    trouves: list[str] = []
    for selecteur in ('[data-testid="tweetText"] a', '[data-testid="card.wrapper"] a'):
        for lien in article.locator(selecteur).all():
            href = lien.get_attribute("href") or ""
            if href.startswith("http"):
                trouves.append(href)
    return _nettoyer_liens(trouves)


def _extraire_article(article) -> dict | None:
    """Transforme un article du DOM en item, ou None s'il est inexploitable."""
    permalien = ""
    for lien in article.locator('a[href*="/status/"]').all():
        href = lien.get_attribute("href") or ""
        if re.search(r"/status/\d+$", href):
            permalien = "https://x.com" + href if href.startswith("/") else href
            break
    if not permalien:
        return None

    auteur = ""
    correspondance = re.search(r"x\.com/([^/]+)/status/", permalien)
    if correspondance:
        auteur = "@" + correspondance.group(1)

    date = None
    horodatage = article.locator("time").first
    try:
        brut = horodatage.get_attribute("datetime", timeout=2000)
        if brut:
            date = datetime.fromisoformat(brut.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        pass

    texte = _texte(article.locator('[data-testid="tweetText"]'))
    return {
        "titre": _titre(texte, auteur),
        "url": permalien,
        "date": date or datetime.now(UTC),
        "extrait": texte,
        "auteur": auteur,
        "liens": _liens_utiles(article),
    }


# --------------------------------------------------------------------------- #
# Voie retenue : export produit par l'utilisateur depuis son propre navigateur
# --------------------------------------------------------------------------- #

MOTIF_EXPORT = "signets-x-*.json"
DOSSIER_TRAITES = config.DOSSIER_STATE / "signets-traites"

# Dossiers fouillés pour retrouver un export, dans l'ordre.
DOSSIERS_EXPORT = [
    Path(os.getenv("VEILLE_DOSSIER_EXPORT") or Path.home() / "Downloads"),
    Path.home() / "Téléchargements",
    config.RACINE,
]


def trouver_export() -> Path | None:
    """Renvoie l'export de signets le plus récent, s'il en existe un."""
    candidats = [
        chemin
        for dossier in DOSSIERS_EXPORT
        if dossier.is_dir()
        for chemin in dossier.glob(MOTIF_EXPORT)
    ]
    return max(candidats, key=lambda p: p.stat().st_mtime) if candidats else None


def charger_export(chemin: Path) -> list[dict]:
    """Lit un export produit par collecte_signets.js.

    Les liens y sont bruts — souvent des t.co, que X substitue dans le DOM. Ils sont
    développés ici, une requête par lien, ce que la page n'aurait pas pu faire.
    """
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    bruts = donnees.get("signets", donnees if isinstance(donnees, list) else [])

    items = []
    for brut in bruts:
        url = (brut.get("url") or "").strip()
        if not url:
            continue

        date = None
        if brut.get("date"):
            try:
                date = datetime.fromisoformat(str(brut["date"]).replace("Z", "+00:00"))
            except ValueError:
                date = None

        auteur = (brut.get("auteur") or "").lstrip("@")
        texte = brut.get("texte") or ""
        items.append(
            {
                "titre": _titre(texte, auteur),
                "url": url,
                "date": date or datetime.now(UTC),
                "extrait": texte,
                "auteur": f"@{auteur}" if auteur else "",
                "liens": _nettoyer_liens(list(brut.get("liens") or [])),
            }
        )
    return items


# Découpage des fiches rédigées, pour les rattacher à leur signet. Sans cela, l'analyse
# n'existe que dans la note Obsidian et le site n'affiche que le texte brut du tweet —
# c'est-à-dire aucune plus-value par rapport aux signets de X eux-mêmes.
_BLOC = re.compile(r"^###\s+(?P<titre>.+?)[ \t]*$\n(?P<corps>.*?)(?=^###\s|\Z)", re.M | re.S)
# Le libellé est tolérant : le modèle écrit parfois « Ce que c me » au lieu de « c'est ».
_QUOI = re.compile(r"\*\*Ce que c[^*]*\*\*\s*[—–-]?\s*(.+?)(?=\n\s*\*\*|\Z)", re.S)
_POUR = re.compile(r"\*\*Pour toi\*\*\s*[—–-]?\s*(.+?)(?=\n\s*\[|\n\s*\*\*|\Z)", re.S)
_LIEN = re.compile(r"\[lien\]\((https?://[^)\s]+)\)")

_VERDICTS = ("Utile", "À tester", "Pour info", "Peu d'intérêt")


def _sans_balisage(texte: str) -> str:
    """Retire le balisage markdown : les cartes du site affichent du texte brut.

    Sans cela, « **À tester :** » s'affiche avec ses astérisques et, surtout, ne
    correspond plus à aucun verdict connu — l'étiquette n'est alors pas détachée.
    """
    texte = re.sub(r"\*\*([^*]+)\*\*", r"\1", texte)
    texte = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", texte)
    texte = re.sub(r"`([^`]+)`", r"\1", texte)
    return " ".join(texte.split())


def associer_fiches(corps: str, items: list[dict]) -> int:
    """Rattache chaque fiche rédigée à son signet, apparié par l'URL du tweet.

    Returns:
        le nombre de signets effectivement enrichis d'une fiche.
    """
    par_url = {it["url"]: it for it in items}
    associes = 0

    for bloc in _BLOC.finditer(corps):
        texte = bloc.group("corps")
        lien = _LIEN.search(texte)
        cible = par_url.get(lien.group(1)) if lien else None
        if cible is None:
            continue

        quoi = _QUOI.search(texte)
        pour = _POUR.search(texte)
        analyse = _sans_balisage(quoi.group(1)) if quoi else ""
        verdict_complet = _sans_balisage(pour.group(1)) if pour else ""

        # « Utile : ... » -> étiquette d'un côté, justification de l'autre.
        etiquette, _, justification = verdict_complet.partition(":")
        etiquette = etiquette.strip()
        if etiquette not in _VERDICTS:
            etiquette, justification = "", verdict_complet

        cible["titre_fiche"] = _sans_balisage(bloc.group("titre"))
        cible["analyse"] = analyse
        cible["verdict"] = etiquette
        cible["justification"] = justification.strip()
        associes += 1

    return associes


def archiver_export(chemin: Path) -> Path:
    """Déplace un export traité, pour qu'il ne soit pas repris au relevé suivant."""
    DOSSIER_TRAITES.mkdir(parents=True, exist_ok=True)
    destination = DOSSIER_TRAITES / chemin.name
    if destination.exists():
        destination = DOSSIER_TRAITES / f"{chemin.stem}-{int(time.time())}{chemin.suffix}"
    shutil.move(str(chemin), destination)
    return destination


# --------------------------------------------------------------------------- #
# Voie par navigateur piloté — conservée, mais bloquée en pratique
# --------------------------------------------------------------------------- #


def collecter(limite: int = 40, headless: bool = True) -> list[dict]:
    """Lit la page des signets et renvoie les items, du plus récent au plus ancien.

    Raises:
        SessionAbsente: si le profil n'a pas de session X ouverte.
    """
    from playwright.sync_api import sync_playwright

    items: list[dict] = []

    with sync_playwright() as p:
        contexte = p.chromium.launch_persistent_context(**_options_lancement(headless))
        page = contexte.pages[0] if contexte.pages else contexte.new_page()

        try:
            page.goto(URL_SIGNETS, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)

            if _deconnecte(page):
                raise SessionAbsente(
                    "Aucune session X dans le profil de navigateur.\n"
                    "  → Lancer `python run_signets.py --connexion`, se connecter dans la\n"
                    "    fenêtre qui s'ouvre, puis fermer la fenêtre. La session est\n"
                    "    conservée pour les exécutions suivantes."
                )

            vus: set[str] = set()
            stagnations = 0

            # La page est virtualisée : les articles hors écran sont retirés du DOM.
            # On récolte donc au fil du défilement, sans espérer tout lire d'un coup.
            while len(items) < limite and stagnations < 3:
                articles = page.locator('article[data-testid="tweet"]').all()
                avant = len(items)

                for article in articles:
                    if len(items) >= limite:
                        break
                    try:
                        item = _extraire_article(article)
                    except Exception:  # noqa: BLE001 — un article illisible n'arrête rien
                        continue
                    if item and item["url"] not in vus:
                        vus.add(item["url"])
                        items.append(item)

                stagnations = stagnations + 1 if len(items) == avant else 0
                page.mouse.wheel(0, 2600)
                page.wait_for_timeout(1800)

            if not items and not page.locator('article[data-testid="tweet"]').count():
                raise SessionAbsente(
                    "La page des signets n'a renvoyé aucun tweet. Session expirée, ou "
                    "structure de page modifiée par X.\n"
                    "  → Vérifier avec `python run_signets.py --connexion`."
                )
        finally:
            contexte.close()

    return items


def ouvrir_session() -> None:
    """Ouvre un navigateur visible sur X pour une connexion manuelle.

    La connexion est faite par l'utilisateur, dans sa propre fenêtre : aucun identifiant
    ne transite par ce code.
    """
    from playwright.sync_api import sync_playwright

    PROFIL_NAVIGATEUR.mkdir(parents=True, exist_ok=True)
    print(f"Profil     : {PROFIL_NAVIGATEUR}")
    print(f"Navigateur : {CANAL or 'Chromium fourni par Playwright'}")
    print("Connecte-toi à X dans la fenêtre, puis ferme-la. La session sera conservée.")

    with sync_playwright() as p:
        options = _options_lancement(headless=False)
        options["viewport"] = {"width": 1280, "height": 900}
        contexte = p.chromium.launch_persistent_context(**options)
        page = contexte.pages[0] if contexte.pages else contexte.new_page()
        page.goto(URL_SIGNETS, wait_until="domcontentloaded")

        # Le script rend la main quand la fenêtre est fermée, pas avant.
        while True:
            try:
                if not contexte.pages:
                    break
                page.wait_for_timeout(1000)
            except Exception:  # noqa: BLE001 — fenêtre fermée par l'utilisateur
                break

        try:
            contexte.close()
        except Exception:  # noqa: BLE001
            pass
