"""
Scrapers pour les sources sans flux RSS.

Ces pages sont rendues côté serveur : titres et dates figurent dans le HTML initial,
sans exécution de JavaScript.

Attention à la répartition des contenus Anthropic : `anthropic.com/news` porte les
annonces corporate, tandis que **`claude.com/blog` porte le produit et Claude Code**.
Ne suivre que le premier fait manquer l'essentiel de ce qui intéresse ce profil.
"""
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .feeds import _http_get, nettoyer_html


def _parser_date(valeur: str) -> datetime | None:
    """Parse une date ISO ou 'Jan 15, 2026' en datetime UTC."""
    if not valeur:
        return None

    valeur = valeur.strip()
    try:
        date = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
        return date if date.tzinfo else date.replace(tzinfo=UTC)
    except ValueError:
        pass

    for gabarit in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valeur, gabarit).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _titre_depuis_slug(url: str) -> str:
    """Repli quand aucun titre n'est trouvé : reconstruit depuis le slug."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").capitalize()


def _scraper_liens(source: dict, prefixe: str, exclure: set[str]) -> list[dict]:
    """Extrait les articles d'une page de listing.

    Pour chaque lien commençant par `prefixe`, récupère le titre (h2/h3 imbriqué)
    et la date (<time> dans le lien ou son parent).
    """
    reponse = _http_get(source["url"])
    reponse.raise_for_status()

    soup = BeautifulSoup(reponse.text, "lxml")
    items = []
    vus = set()

    for lien in soup.select(f'a[href^="{prefixe}"]'):
        href = lien.get("href", "")
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if not slug or slug in exclure or href in vus:
            continue
        vus.add(href)

        titre_tag = lien.find(["h1", "h2", "h3"])
        titre = titre_tag.get_text(strip=True) if titre_tag else ""
        if not titre:
            # Le titre est parfois en dehors du <a>, dans le bloc parent.
            parent = lien.find_parent(["article", "div", "li"])
            if parent:
                titre_tag = parent.find(["h1", "h2", "h3"])
                titre = titre_tag.get_text(strip=True) if titre_tag else ""
        if not titre:
            titre = _titre_depuis_slug(href)

        time_tag = lien.find("time") or (
            lien.find_parent(["article", "div", "li"]).find("time")
            if lien.find_parent(["article", "div", "li"])
            else None
        )
        date = None
        if time_tag:
            date = _parser_date(time_tag.get("datetime", "")) or _parser_date(
                time_tag.get_text(strip=True)
            )

        items.append(
            {
                "titre": nettoyer_html(titre, limite=200),
                "url": urljoin(source["url"], href),
                "date": date,
                "extrait": "",
            }
        )

    return items


def scraper_anthropic(source: dict) -> list[dict]:
    """Articles de anthropic.com/news (aucun flux RSS n'existe)."""
    return _scraper_liens(source, "/news/", exclure=set())


def scraper_claude_blog(source: dict) -> list[dict]:
    """Articles de claude.com/blog — le blog produit et Claude Code d'Anthropic.

    La page est construite avec Webflow, qui expose chaque champ dans un attribut
    `fs-list-field` : c'est plus stable à parser que la structure des div.
    """
    reponse = _http_get(source["url"])
    reponse.raise_for_status()

    soup = BeautifulSoup(reponse.text, "lxml")
    items = []
    vus = set()

    for titre_tag in soup.select('[fs-list-field="heading"]'):
        # Le lien n'est pas dans le bloc du titre : on remonte jusqu'à l'ancêtre
        # qui contient les deux.
        conteneur, lien = titre_tag, None
        for _ in range(6):
            conteneur = conteneur.parent
            if conteneur is None:
                break
            lien = conteneur.select_one('a[href^="/blog/"]')
            if lien:
                break
        if not lien:
            continue

        href = lien.get("href", "")
        if not href or href in vus:
            continue
        vus.add(href)

        date_tag = conteneur.select_one('[fs-list-field="date"]')
        categorie_tag = conteneur.select_one('[fs-list-field="category"]')

        items.append(
            {
                "titre": nettoyer_html(titre_tag.get_text(strip=True), limite=200),
                "url": urljoin(source["url"], href),
                "date": _parser_date(date_tag.get_text(strip=True)) if date_tag else None,
                "extrait": categorie_tag.get_text(strip=True) if categorie_tag else "",
            }
        )

    return items


def scraper_sitemap(source: dict) -> list[dict]:
    """Détecte les nouvelles pages d'un site à partir de son sitemap.

    Pensé pour la documentation, qui n'a pas de flux. La déduplication fait le travail :
    une URL déjà vue ne ressort pas, donc seules les **pages nouvellement publiées**
    remontent — une doc retouchée pour une coquille ne pollue pas le digest.

    Paramètres attendus dans `params` : `filtre_url` (sous-chaîne obligatoire dans
    l'URL, ex. `/docs/en/`) pour éviter de remonter dix fois la même page traduite.
    """
    reponse = _http_get(source["url"])
    reponse.raise_for_status()

    filtre = source.get("params", {}).get("filtre_url", "")
    items = []

    for bloc in re.findall(r"<url>(.*?)</url>", reponse.text, re.S):
        lien = re.search(r"<loc>(.*?)</loc>", bloc)
        if not lien or (filtre and filtre not in lien.group(1)):
            continue

        modifie = re.search(r"<lastmod>(.*?)</lastmod>", bloc)
        slug = lien.group(1).rstrip("/").rsplit("/", 1)[-1]

        items.append(
            {
                "titre": slug.replace("-", " ").capitalize(),
                "url": lien.group(1),
                "date": _parser_date(modifie.group(1)) if modifie else None,
                "extrait": "Nouvelle page de documentation.",
            }
        )

    return items


# Les liens de navigation de The Batch partagent le préfixe des articles.
_BATCH_IGNORES = ("tag/", "page/", "about", "search")
# Chaque numéro est accompagné d'un lien de tag qui encode sa date : "aug-08-2026".
_BATCH_DATE_TAG = re.compile(r"/the-batch/tag/([a-z]{3}-\d{2}-\d{4})$")


def scraper_the_batch(source: dict) -> list[dict]:
    """Numéros de The Batch (aucun flux RSS exploitable).

    La page mélange articles et navigation (tags, pagination). La date n'est pas
    dans une balise <time> mais dans le lien de tag voisin, d'où ce traitement
    distinct du scraper générique.
    """
    reponse = _http_get(source["url"])
    reponse.raise_for_status()

    soup = BeautifulSoup(reponse.text, "lxml")
    items = []
    vus = set()

    for lien in soup.select('a[href^="/the-batch/"]'):
        href = lien.get("href", "")
        reste = href.removeprefix("/the-batch/").strip("/")
        if not reste or href in vus or reste.startswith(_BATCH_IGNORES):
            continue
        vus.add(href)

        conteneur = lien.find_parent(["article", "div", "li"]) or lien
        titre_tag = lien.find(["h1", "h2", "h3"]) or conteneur.find(["h1", "h2", "h3"])
        titre = titre_tag.get_text(strip=True) if titre_tag else _titre_depuis_slug(href)

        items.append(
            {
                "titre": nettoyer_html(titre, limite=200),
                "url": urljoin(source["url"], href),
                "date": _date_depuis_tag(conteneur),
                "extrait": "",
            }
        )

    return items


def _date_depuis_tag(conteneur) -> datetime | None:
    """Cherche un lien de tag daté ('aug-08-2026') dans le bloc de l'article."""
    for tag in conteneur.select('a[href*="/the-batch/tag/"]'):
        correspondance = _BATCH_DATE_TAG.search(tag.get("href", ""))
        if correspondance:
            try:
                return datetime.strptime(
                    correspondance.group(1), "%b-%d-%Y"
                ).replace(tzinfo=UTC)
            except ValueError:
                continue
    return None
