"""
Publications X des gens qui font les outils — sans jamais toucher à une session X.

Ce qui se dit sur X par l'équipe Claude Code (astuces, fonctionnalités annoncées avant
la doc, réponses sur les comportements) n'existe nulle part ailleurs. Deux voies, toutes
deux sans navigateur ni cookie — la limite posée le 09/08 pour les signets reste entière :

- `follow_builders` : le flux JSON public du projet open source follow-builders, régénéré
  chaque matin depuis l'API officielle. Gratuit, mais on dépend de sa liste de comptes et
  de ses crédits (il est déjà resté vide en juillet, sur un 402).
- `x_api` : l'API officielle, avec un jeton d'application en lecture seule. Contrairement
  au jeton OAuth utilisateur écarté pour les signets, celui-ci **ne tourne pas** : un
  secret GitHub suffit, sans rien réécrire d'une exécution à l'autre. Payant à l'usage.
"""
import html
import os
import re
from datetime import UTC, datetime, timedelta

import httpx

from .feeds import _http_get

_URL = re.compile(r"https?://\S+")


def _texte_utile(texte: str) -> str:
    """Texte d'un post sans ses liens raccourcis : « AGI https://t.co/x » ne dit rien."""
    return _URL.sub("", texte or "").strip()


def _item(handle: str, nom: str, texte: str, url: str, date: datetime | None,
          contexte: str = "") -> dict:
    """Met un post au format commun. Le titre est une accroche, l'extrait le post entier."""
    texte = html.unescape(texte)  # l'API renvoie « &amp; » là où le post affiche « & »
    premiere = " ".join(_texte_utile(texte).split())
    if len(premiere) > 110:
        premiere = premiere[:110].rsplit(" ", 1)[0] + "…"
    entete = f"{nom} (@{handle}{', ' + contexte if contexte else ''})"
    return {
        "titre": f"@{handle} : {premiere}",
        "url": url,
        "date": date,
        "extrait": f"{entete} — {texte.strip()}",
    }


def _borner(items: list[dict], source: dict) -> list[dict]:
    """Applique `extrait_max`, comme lire_rss : un fil d'astuces peut faire 4000 signes."""
    limite = source.get("extrait_max", 1500)
    for it in items:
        if len(it["extrait"]) > limite:
            it["extrait"] = it["extrait"][:limite].rsplit(" ", 1)[0] + "…"
    return items


def _date(valeur: str | None) -> datetime | None:
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def lire_follow_builders(source: dict) -> list[dict]:
    """Posts X du flux follow-builders (`feed-x.json`).

    Le fichier ne porte que les dernières 24 h : si une de nos exécutions échoue, le
    lendemain ne verrait plus la veille. On lit donc aussi ses versions précédentes dans
    l'historique git du dépôt — la fenêtre de collecte et la déduplication font le tri.

    Paramètres (`params`) : `depot` (propriétaire/nom), `fichier`, `versions` (nombre de
    versions lues, 3 par défaut), `exclure` (comptes ignorés), `min_caracteres` (texte
    utile minimal, liens retirés : « o no :( » n'apprend rien à personne).
    """
    params = source.get("params", {})
    depot = params.get("depot", "zarazhangrui/follow-builders")
    fichier = params.get("fichier", "feed-x.json")
    exclure = {h.lower() for h in params.get("exclure", [])}
    minimum = params.get("min_caracteres", 50)

    urls = [source["url"]]
    try:
        reponse = _http_get(
            f"https://api.github.com/repos/{depot}/commits",
            params={"path": fichier, "per_page": params.get("versions", 3)},
        )
        if reponse.status_code == 200:
            urls = [
                f"https://raw.githubusercontent.com/{depot}/{c['sha']}/{fichier}"
                for c in reponse.json()
            ] or urls
    except Exception:  # noqa: BLE001 — l'historique est un bonus, la version courante suffit
        pass

    items, vus = [], set()
    for url in urls:
        reponse = _http_get(url)
        if reponse.status_code != 200 and url != urls[0]:
            continue
        reponse.raise_for_status()
        for compte in reponse.json().get("x", []):
            handle = compte.get("handle", "")
            if not handle or handle.lower() in exclure:
                continue
            for post in compte.get("tweets", []):
                lien = post.get("url")
                if not lien or lien in vus or len(_texte_utile(post.get("text", ""))) < minimum:
                    continue
                vus.add(lien)
                bio = (compte.get("bio") or "").split("\n")[0][:60]
                items.append(_item(handle, compte.get("name") or handle, post["text"], lien,
                                   _date(post.get("createdAt")), bio))
    return _borner(items, source)


def lire_x_api(source: dict) -> list[dict]:
    """Posts récents de comptes choisis, via l'API officielle X (recherche récente).

    Une requête par compte : le résultat dit alors lui-même de qui vient chaque post, sans
    l'expansion `author_id`, facturée comme une lecture de profil. Retweets et réponses
    sont exclus à la source — on ne paie que ce qu'on garde. La fenêtre part de `_depuis`,
    que la collecte transmet : relire des posts déjà vus serait payé une seconde fois.

    Le jeton vient de `X_BEARER_TOKEN` ; sans lui la source n'est pas chargée du tout
    (`requiert_env` dans sources.yaml).
    """
    jeton = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not jeton:
        raise RuntimeError("X_BEARER_TOKEN absent")
    params = source.get("params", {})
    minimum = params.get("min_caracteres", 50)
    depuis = source.get("_depuis")

    items = []
    for handle in params.get("comptes", []):
        requete = {
            "query": f"from:{handle} -is:retweet -is:reply",
            "max_results": params.get("max_par_compte", 10),
            # note_tweet : sans lui, un post long est coupé à 280 caractères — et les
            # fils d'astuces de l'équipe Claude Code sont justement des posts longs.
            "tweet.fields": "created_at,public_metrics,note_tweet",
        }
        if depuis:
            # La recherche récente ne remonte qu'à sept jours : au-delà, X répond 400.
            depuis = max(depuis, datetime.now(UTC) - timedelta(days=6, hours=23))
            requete["start_time"] = depuis.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        reponse = httpx.get(
            source["url"], params=requete, timeout=20,
            headers={"Authorization": f"Bearer {jeton}"},
        )
        if reponse.status_code == 402:
            raise RuntimeError("crédits de l'API X épuisés (402) — recharger la console X")
        if reponse.status_code in (401, 403):
            raise RuntimeError(f"jeton X refusé ({reponse.status_code})")
        reponse.raise_for_status()
        for post in reponse.json().get("data", []):
            texte = (post.get("note_tweet") or {}).get("text") or post.get("text", "")
            if len(_texte_utile(texte)) < minimum:
                continue
            j_aime = (post.get("public_metrics") or {}).get("like_count")
            items.append(_item(
                handle, handle, texte, f"https://x.com/{handle}/status/{post['id']}",
                _date(post.get("created_at")),
                f"{j_aime} j'aime" if j_aime is not None else "",
            ))
    return _borner(items, source)
