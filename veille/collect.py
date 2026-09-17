"""
Orchestration de la collecte sur l'ensemble des sources.

Règle non négociable : une source en panne ne doit jamais faire échouer le run.
Les flux meurent ou changent d'URL sans prévenir — plusieurs l'ont fait pendant
la constitution de la liste. Chaque source est donc isolée, et les échecs sont
remontés dans le digest pour être visibles sans consulter les logs.
"""
import time
from datetime import UTC, datetime, timedelta

from . import config, feeds, scrapers

_COLLECTEURS = {
    "rss": feeds.lire_rss,
    "hn": feeds.lire_hackernews,
    "scrape_anthropic": scrapers.scraper_anthropic,
    "scrape_claude_blog": scrapers.scraper_claude_blog,
    "scrape_the_batch": scrapers.scraper_the_batch,
    "sitemap": scrapers.scraper_sitemap,
}


def collecter(
    sources: list[dict], depuis: datetime, verbeux: bool = True
) -> tuple[list[dict], list[dict]]:
    """Collecte tous les items publiés depuis `depuis`.

    Returns:
        (items, echecs) — echecs contient {source, erreur} pour chaque source en panne.
    """
    items: list[dict] = []
    echecs: list[dict] = []

    for i, source in enumerate(sources):
        collecteur = _COLLECTEURS.get(source["type"])
        if collecteur is None:
            echecs.append(
                {"source": source["nom"], "erreur": f"type inconnu : {source['type']}"}
            )
            continue

        debut = time.monotonic()
        try:
            bruts = collecteur(source)
        except Exception as e:  # noqa: BLE001 — aucune source ne doit casser le run
            echecs.append({"source": source["nom"], "erreur": f"{type(e).__name__}: {e}"})
            if verbeux:
                print(f"  {source['nom']:<32} ÉCHEC  {type(e).__name__}: {e}")
            continue

        retenus = [it for it in bruts if _dans_fenetre(it, depuis)]
        for it in retenus:
            it["source_id"] = source["id"]
            it["source_nom"] = source["nom"]
            it["categorie"] = source["categorie"]
            it["titre_utilisateur"] = source.get("titre_utilisateur", False)
            it["poids"] = source["poids"]

        items.extend(retenus)

        if verbeux:
            duree = time.monotonic() - debut
            print(
                f"  {source['nom']:<32} {len(retenus):>3} items "
                f"(sur {len(bruts):>3})  {duree:.1f}s"
            )

        # Reddit renvoie 429 au-delà d'environ une requête par seconde.
        if i < len(sources) - 1:
            time.sleep(config.DELAI_ENTRE_SOURCES)

    return items, echecs


def _dans_fenetre(item: dict, depuis: datetime) -> bool:
    """Un item sans date est conservé : la déduplication évite les répétitions.

    Ce filtrage est obligatoire, pas cosmétique — le flux OpenAI contient plus de
    1100 entrées, dont l'essentiel remonte à plusieurs années.
    """
    if item.get("date") is None:
        return True
    return item["date"] >= depuis


def trier(items: list[dict]) -> list[dict]:
    """Trie par poids de source décroissant, puis par date décroissante."""
    tres_ancien = datetime(1970, 1, 1, tzinfo=UTC)
    return sorted(
        items,
        key=lambda it: (it.get("poids", 1), it.get("date") or tres_ancien),
        reverse=True,
    )


def fenetre_depuis(expression: str) -> datetime:
    """Convertit '24h', '3d', '7d' en datetime UTC de début de fenêtre."""
    expression = expression.strip().lower()
    valeur, unite = int(expression[:-1]), expression[-1]
    delta = {"h": timedelta(hours=valeur), "d": timedelta(days=valeur)}.get(unite)
    if delta is None:
        raise ValueError(f"fenêtre invalide : {expression} (attendu ex. 24h, 3d)")
    return datetime.now(UTC) - delta
