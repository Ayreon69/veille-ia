"""
Lecture des flux RSS/Atom et de l'API Hacker News (Algolia).
"""
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import feedparser
import httpx

from . import config

_dernier_appel: dict[str, float] = {}


def _throttle(url: str) -> None:
    """Respecte l'intervalle minimum configuré pour le domaine appelé."""
    domaine = urlparse(url).netloc.lower().removeprefix("www.")
    intervalle = config.DELAI_DOMAINES.get(domaine, 0.0)
    if not intervalle:
        return

    ecoule = time.monotonic() - _dernier_appel.get(domaine, 0.0)
    if ecoule < intervalle:
        time.sleep(intervalle - ecoule)
    _dernier_appel[domaine] = time.monotonic()


def _http_get(url: str, params: dict | None = None) -> httpx.Response:
    """GET avec User-Agent navigateur, suivi des redirections et retry sur 429."""
    derniere: httpx.Response | None = None

    for tentative in range(3):
        _throttle(url)
        reponse = httpx.get(
            url,
            params=params,
            timeout=config.TIMEOUT_HTTP,
            follow_redirects=True,
            headers={"User-Agent": config.USER_AGENT},
        )
        if reponse.status_code != 429:
            return reponse

        derniere = reponse
        if tentative < 2:
            attente = float(reponse.headers.get("retry-after") or 5 * (tentative + 1))
            time.sleep(min(attente, 20.0))

    return derniere


def nettoyer_html(texte: str, limite: int = 400) -> str:
    """Supprime les balises HTML et tronque proprement."""
    if not texte:
        return ""
    texte = re.sub(r"<[^>]+>", " ", texte)
    texte = texte.replace("&nbsp;", " ").replace("\xa0", " ")
    texte = re.sub(r"&#?\w{2,8};", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()
    if len(texte) > limite:
        texte = texte[:limite].rsplit(" ", 1)[0] + "…"
    return texte


def _date_entree(entree) -> datetime | None:
    """Extrait une date UTC depuis une entrée feedparser, si disponible."""
    for champ in ("published_parsed", "updated_parsed", "created_parsed"):
        valeur = entree.get(champ)
        if valeur:
            try:
                return datetime(*valeur[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None


def lire_rss(source: dict) -> list[dict]:
    """Lit un flux RSS/Atom et renvoie une liste d'items normalisés.

    Les entrées sans date sont conservées (date=None) : la déduplication empêche
    de les remonter plusieurs fois, et certains flux n'exposent pas de date fiable.
    """
    reponse = _http_get(source["url"])
    reponse.raise_for_status()

    flux = feedparser.parse(reponse.content)
    items = []

    # Les changelogs déclarent un extrait plus long : leur contenu utile est la liste
    # complète des puces, pas les deux premières.
    limite_extrait = source.get("extrait_max", config.EXTRAIT_MAX_DEFAUT)

    for entree in flux.entries:
        lien = entree.get("link") or ""
        titre = nettoyer_html(entree.get("title", ""), limite=200)
        if not lien or not titre:
            continue

        extrait = entree.get("summary") or entree.get("description") or ""
        if not extrait and entree.get("content"):
            extrait = entree["content"][0].get("value", "")

        items.append(
            {
                "titre": titre,
                "url": lien,
                "date": _date_entree(entree),
                "extrait": nettoyer_html(extrait, limite=limite_extrait),
            }
        )

    return items


def lire_hackernews(source: dict) -> list[dict]:
    """Interroge l'API Algolia de Hacker News, un appel par mot-clé.

    Le filtrage par score est le seul moyen d'obtenir un signal exploitable :
    sans lui, HN remonte surtout du bruit.
    """
    params_source = source.get("params", {})
    mots_cles = params_source.get("mots_cles", ["LLM"])
    min_points = params_source.get("min_points", 30)

    items = []
    vus = set()

    for mot in mots_cles:
        reponse = _http_get(
            source["url"],
            params={
                "query": mot,
                "tags": "story",
                "numericFilters": f"points>{min_points}",
                "hitsPerPage": 30,
            },
        )
        reponse.raise_for_status()

        for hit in reponse.json().get("hits", []):
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
            if url in vus:
                continue
            vus.add(url)

            date = None
            if hit.get("created_at_i"):
                date = datetime.fromtimestamp(hit["created_at_i"], tz=UTC)

            items.append(
                {
                    "titre": hit.get("title", ""),
                    "url": url,
                    "date": date,
                    "extrait": (
                        f"{hit.get('points', 0)} points, "
                        f"{hit.get('num_comments', 0)} commentaires — "
                        f"https://news.ycombinator.com/item?id={hit['objectID']}"
                    ),
                }
            )

    return items
