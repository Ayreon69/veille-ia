"""
Lecture du contenu pointé par un lien.

Un tweet fait 280 caractères : sa valeur est dans le lien, pas dans le texte. Sans cette
étape, résumer un signet revient à paraphraser « regardez ce dépôt » — ce qui n'apprend
rien et reproduit exactement le défaut qui a produit l'erreur factuelle du 8 août, où une
affirmation non vérifiée avait été reprise faute de pouvoir consulter la source.

Trois traitements, du plus spécifique au plus générique : dépôt GitHub, article arXiv,
page web quelconque.
"""
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from . import config

LONGUEUR_MAX = 2500

_BALISES_INUTILES = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript")


def _tronquer(texte: str, limite: int = LONGUEUR_MAX) -> str:
    texte = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", texte)).strip()
    if len(texte) > limite:
        texte = texte[:limite].rsplit(" ", 1)[0] + "…"
    return texte


def _get(url: str, **kwargs) -> httpx.Response:
    return httpx.get(
        url,
        timeout=config.TIMEOUT_HTTP,
        follow_redirects=True,
        headers={"User-Agent": config.USER_AGENT, **kwargs.pop("headers", {})},
        **kwargs,
    )


def _depot_github(proprietaire: str, depot: str, limite: int = LONGUEUR_MAX) -> str:
    """Fiche d'un dépôt : métadonnées puis début du README.

    L'API non authentifiée suffit largement (60 requêtes/heure) pour quelques signets
    par jour. Au-delà, elle renvoie 403 et on retombe sur la lecture de page.
    """
    base = f"https://api.github.com/repos/{proprietaire}/{depot}"
    fiche = _get(base, headers={"Accept": "application/vnd.github+json"})
    if fiche.status_code != 200:
        raise httpx.HTTPError(f"API GitHub : {fiche.status_code}")

    donnees = fiche.json()
    entete = [
        f"Dépôt GitHub {proprietaire}/{depot}",
        f"Description : {donnees.get('description') or '(aucune)'}",
        f"Langage : {donnees.get('language') or 'n/a'} | "
        f"étoiles : {donnees.get('stargazers_count', 0)} | "
        f"dernier push : {(donnees.get('pushed_at') or '')[:10]}",
    ]
    if donnees.get("topics"):
        entete.append("Thèmes : " + ", ".join(donnees["topics"][:10]))
    if donnees.get("archived"):
        entete.append("⚠ Dépôt archivé.")

    readme = _get(base + "/readme", headers={"Accept": "application/vnd.github.raw"})
    if readme.status_code == 200:
        # Le markdown brut est lisible tel quel par le modèle ; on retire seulement les
        # images et badges, qui occupent beaucoup de place pour aucune information.
        corps = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", readme.text)
        entete.append("\nREADME :\n" + corps)

    return _tronquer("\n".join(entete), limite)


def _article_arxiv(identifiant: str, limite: int = LONGUEUR_MAX) -> str:
    """Titre, auteurs et résumé d'un article arXiv."""
    reponse = _get(f"http://export.arxiv.org/api/query?id_list={identifiant}")
    reponse.raise_for_status()
    soupe = BeautifulSoup(reponse.text, "xml") if _xml_dispo() else BeautifulSoup(
        reponse.text, "html.parser"
    )
    entree = soupe.find("entry")
    if not entree:
        raise ValueError("article arXiv introuvable")

    auteurs = [a.get_text(strip=True) for a in entree.find_all("name")][:6]
    return _tronquer(
        f"Article arXiv {identifiant}\n"
        f"Titre : {entree.find('title').get_text(strip=True)}\n"
        f"Auteurs : {', '.join(auteurs)}\n\n"
        f"Résumé : {entree.find('summary').get_text(strip=True)}",
        limite,
    )


def _xml_dispo() -> bool:
    try:
        BeautifulSoup("<a/>", "xml")
        return True
    except Exception:  # noqa: BLE001 — lxml absent
        return False


def _page_web(url: str, limite: int = LONGUEUR_MAX) -> str:
    """Texte principal d'une page web quelconque."""
    reponse = _get(url)
    reponse.raise_for_status()

    type_contenu = reponse.headers.get("content-type", "")
    if "html" not in type_contenu and "text" not in type_contenu:
        raise ValueError(f"contenu non textuel ({type_contenu or 'inconnu'})")

    soupe = BeautifulSoup(reponse.text, "html.parser")
    for balise in soupe(_BALISES_INUTILES):
        balise.decompose()

    principal = soupe.find("article") or soupe.find("main") or soupe.body or soupe
    titre = soupe.title.get_text(strip=True) if soupe.title else ""
    return _tronquer(
        (f"{titre}\n\n" if titre else "") + principal.get_text("\n", strip=True), limite
    )


def enrichir(url: str, limite: int = LONGUEUR_MAX) -> str:
    """Renvoie une description textuelle de la cible, ou "" en cas d'échec.

    Ne lève jamais : un lien mort ou protégé ne doit pas faire échouer le traitement du
    signet, dont le texte du tweet reste exploitable.

    Args:
        limite: longueur de texte conservée. La valeur par défaut suffit à juger un
            signet ; développer un article demande davantage de matière, sans quoi le
            modèle résumerait une introduction en croyant résumer l'article.
    """
    domaine = urlparse(url).netloc.lower().removeprefix("www.")

    try:
        depot = re.match(r"^https?://github\.com/([\w.-]+)/([\w.-]+)/?$", url.rstrip("/") + "/")
        if domaine == "github.com" and depot:
            return _depot_github(depot.group(1), depot.group(2), limite)

        arxiv = re.search(r"arxiv\.org/(?:abs|pdf)/([\d.]+v?\d*)", url)
        if arxiv:
            return _article_arxiv(arxiv.group(1).removesuffix(".pdf"), limite)

        return _page_web(url, limite)
    except Exception as e:  # noqa: BLE001 — l'enrichissement est un bonus, jamais un bloquant
        return f"(contenu du lien non récupéré — {type(e).__name__})"
