"""
Génère le site de consultation depuis les archives quotidiennes.

Usage :
    python build_site.py                # reconstruit site/index.html
    python build_site.py --ouvrir       # et l'ouvre dans le navigateur
    python build_site.py --amorcer 7d   # remplit l'archive avec les 7 derniers jours

L'amorçage sert une seule fois, au démarrage : l'archive naît avec le site, elle est
donc vide alors que les sources, elles, ont déjà publié. Il collecte sans tenir compte
de la déduplication et sans appeler le modèle — aucun digest n'est produit, aucune note
Obsidian n'est touchée, seuls les fichiers data/ sont écrits.
"""
import argparse
import re
import sys
import webbrowser
from collections import defaultdict
from datetime import date, datetime

from veille import collect, config, site


def _digest_depuis_note(jour: date) -> str:
    """Extrait le corps rédigé d'une note quotidienne déjà écrite dans le vault.

    Les journées antérieures au site ont un digest, mais seulement dans Obsidian.
    Le récupérer évite de rappeler le modèle pour un texte déjà produit.
    """
    chemin = config.DOSSIER_QUOTIDIEN / f"{jour.isoformat()}.md"
    if not chemin.exists():
        return ""

    texte = chemin.read_text(encoding="utf-8")
    texte = re.sub(r"^---\n.*?\n---\n", "", texte, count=1, flags=re.DOTALL)  # frontmatter
    # Le \s* est nécessaire : le frontmatter laisse une ligne vide avant le titre.
    texte = re.sub(r"^\s*#\s+.*\n", "", texte, count=1)                       # titre H1
    # Le repli « Sources en échec » est un diagnostic d'exécution, pas du contenu.
    texte = re.split(r"\n---\s*\n\s*>\s*\[!warning\]", texte)[0]
    return texte.strip()


def _amorcer(fenetre: str) -> int:
    """Remplit data/ avec le contenu actuel des sources, réparti par jour de publication."""
    # Les sitemaps sont écartés de l'amorçage. La documentation est republiée en bloc,
    # donc son `lastmod` date la reconstruction du site, pas la publication : sans la
    # déduplication — que l'amorçage contourne par construction — elle noie tout le
    # reste. Mesuré : 130 pages de doc sur 331 items, dont 74 sur une seule journée.
    # En fonctionnement normal, run_daily.py les fait remonter à raison des vraies
    # nouveautés, ce qui reste la priorité n°1 du profil.
    sources = [s for s in config.charger_sources() if s["type"] != "sitemap"]
    depuis = collect.fenetre_depuis(fenetre)
    print(f"Amorçage du site sur {len(sources)} sources (fenêtre {fenetre})\n")

    items, echecs = collect.collecter(sources, depuis)

    par_jour: dict[date, list[dict]] = defaultdict(list)
    for it in items:
        # Sans date exploitable, l'item est rattaché à aujourd'hui : le rejeter le
        # ferait disparaître alors qu'il est bien dans la fenêtre demandée.
        quand = it.get("date")
        jour = quand.astimezone(config.FUSEAU).date() if isinstance(quand, datetime) else config.aujourdhui()
        par_jour[jour].append(it)

    for jour in sorted(par_jour):
        chemin = site.enregistrer_jour(jour, par_jour[jour], _digest_depuis_note(jour))
        print(f"  {jour}  {len(par_jour[jour]):>3} items  ->  {chemin.name}")

    print(f"\n{len(items)} items archivés sur {len(par_jour)} jours.")
    for e in echecs:
        print(f"  ÉCHEC {e['source']} — {e['erreur'][:100]}")
    return 0


def _noter(forcer: bool) -> int:
    """Attribue un score aux journées archivées qui n'en ont pas.

    Un appel au modèle par journée. Le digest produit au passage n'est conservé que
    si la journée n'en a aucun — on ne réécrit jamais un digest déjà rédigé.
    """
    from veille import summarize

    for jour_data in reversed(site.charger_jours()):
        jour = date.fromisoformat(jour_data["date"])
        items = jour_data.get("items", [])
        if not items:
            continue
        if not forcer and all(it.get("score") is not None for it in items):
            print(f"  {jour}  déjà noté")
            continue

        for it in items:
            it["date"] = datetime.fromisoformat(it["date"]) if it.get("date") else None

        print(f"  {jour}  {len(items)} items…", flush=True)
        try:
            digest = summarize.resumer_et_noter(items)
        except Exception as e:  # noqa: BLE001 — une journée en échec n'arrête pas les autres
            print(f"  {jour}  ÉCHEC {type(e).__name__}: {e}")
            continue

        scores = {it["url"]: it["score"] for it in items if it.get("score") is not None}
        touches = site.annoter_jour(jour, scores, digest)
        print(f"  {jour}  {touches} items notés")

    return 0


def main() -> int:
    parseur = argparse.ArgumentParser(description="Site de consultation de la veille.")
    parseur.add_argument("--ouvrir", action="store_true", help="ouvre le site dans le navigateur")
    parseur.add_argument(
        "--noter",
        action="store_true",
        help="note les journées archivées sans score (un appel modèle par journée)",
    )
    parseur.add_argument(
        "--renoter",
        action="store_true",
        help="renote toutes les journées, y compris celles déjà notées",
    )
    parseur.add_argument(
        "--amorcer",
        metavar="FENETRE",
        help="collecte sans déduplication ni résumé pour remplir l'archive (ex: 7d)",
    )
    parseur.add_argument(
        "--public",
        action="store_true",
        help="construit AUSSI le site publiable dans site-public/ (sans signets, "
             "favoris ni développements)",
    )
    parseur.add_argument(
        "--jours",
        type=int,
        default=site.JOURS_AFFICHES,
        help=f"nombre de jours affichés (défaut : {site.JOURS_AFFICHES})",
    )
    args = parseur.parse_args()

    if args.amorcer:
        code = _amorcer(args.amorcer)
        if code:
            return code

    if args.noter or args.renoter:
        print(f"Notation via le backend « {config.BACKEND} »\n")
        _noter(forcer=args.renoter)
        print()

    chemin = site.construire(args.jours)
    jours = site.charger_jours(args.jours)
    total = sum(len(j.get("items", [])) for j in jours)
    print(f"Site généré : {chemin}  ({total} éléments sur {len(jours)} jours)")

    if args.public:
        publie = site.construire(args.jours, public=True)
        publics = sum(
            1
            for j in jours
            for it in j.get("items", [])
            if it.get("url") and it.get("categorie") != "signets"
        )
        print(f"Site public : {publie}  ({publics} éléments, sans signets ni favoris)")

    if args.ouvrir:
        webbrowser.open(chemin.as_uri())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
