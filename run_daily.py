"""
Digest quotidien : collecte -> déduplication -> résumé -> écriture dans Obsidian.

Usage :
    python run_daily.py                      # run complet
    python run_daily.py --dry-run            # collecte seule, sans modèle ni écriture
    python run_daily.py --since 3d           # élargit la fenêtre de collecte
    python run_daily.py --no-vault           # affiche le digest sans écrire dans le vault
"""
import argparse
import json
import sys
from datetime import datetime

from veille import collect, config, dedupe, render, site, summarize, vault


def _serialiser(items: list[dict]) -> str:
    """Sérialise les items en JSON (dates en ISO)."""
    copie = []
    for it in items:
        clone = dict(it)
        clone["date"] = it["date"].isoformat() if it.get("date") else None
        copie.append(clone)
    return json.dumps(copie, ensure_ascii=False, indent=2)


def _amorcer(ids: list[str]) -> int:
    """Enregistre le contenu actuel de certaines sources comme déjà vu.

    Aucun digest n'est produit : l'objectif est uniquement de constituer une base de
    référence, pour que seules les nouveautés ultérieures remontent.
    """
    toutes = {s["id"]: s for s in config.charger_sources(inclure_inactives=True)}
    inconnues = [i for i in ids if i not in toutes]
    if inconnues:
        print(f"Source(s) inconnue(s) : {', '.join(inconnues)}")
        return 1

    sources = [toutes[i] for i in ids]
    # Fenêtre très large : on veut la totalité du contenu existant, pas les récents.
    items, echecs = collect.collecter(sources, collect.fenetre_depuis("3650d"))

    seen = dedupe.charger_seen()
    avant = len(seen)
    dedupe.filtrer_nouveaux(items, seen)
    dedupe.enregistrer_seen(seen)

    print(
        f"\nAmorçage terminé : {len(seen) - avant} URLs ajoutées "
        f"({len(seen)} au total). Aucun digest produit."
    )
    for e in echecs:
        print(f"  ÉCHEC {e['source']} — {e['erreur'][:100]}")
    return 0


def main() -> int:
    parseur = argparse.ArgumentParser(description="Digest de veille IA quotidien.")
    parseur.add_argument("--since", default="24h", help="fenêtre de collecte (ex: 24h, 3d)")
    parseur.add_argument(
        "--dry-run",
        action="store_true",
        help="collecte seule : aucun appel au modèle, aucune écriture, état inchangé",
    )
    parseur.add_argument(
        "--no-vault", action="store_true", help="affiche le digest sans écrire dans le vault"
    )
    parseur.add_argument(
        "--amorcer",
        nargs="+",
        metavar="SOURCE_ID",
        help=(
            "marque tout le contenu actuel des sources indiquées comme déjà vu, sans "
            "produire de digest. Indispensable pour une source de type sitemap : la "
            "documentation est republiée en bloc, donc lastmod ne distingue pas une "
            "nouveauté d'une reconstruction du site. Sans amorçage, le premier run "
            "remonterait une centaine de pages d'un coup."
        ),
    )
    args = parseur.parse_args()

    if args.amorcer:
        return _amorcer(args.amorcer)

    sources = config.charger_sources()
    depuis = collect.fenetre_depuis(args.since)
    print(f"Collecte sur {len(sources)} sources (fenêtre {args.since})\n")

    items, echecs = collect.collecter(sources, depuis)

    seen = dedupe.charger_seen()
    nouveaux = collect.trier(dedupe.filtrer_nouveaux(items, seen))

    print(
        f"\n{len(items)} items collectés, {len(nouveaux)} nouveaux "
        f"après déduplication | {len(sources) - len(echecs)}/{len(sources)} sources OK"
    )

    if args.dry_run:
        print("\n--dry-run : ni modèle, ni écriture, état inchangé.")
        for e in echecs:
            print(f"  ÉCHEC {e['source']} — {e['erreur'][:100]}")
        return 0

    # Une seconde exécution le même jour ne remonte rien (tout est déjà dédoublonné).
    # Sans ce garde-fou, elle écraserait la note du matin par un digest vide.
    note_du_jour = config.DOSSIER_QUOTIDIEN / f"{config.aujourdhui().isoformat()}.md"
    if not nouveaux and note_du_jour.exists():
        print(f"\nAucun élément nouveau — note existante conservée : {note_du_jour}")
        return 0

    config.DOSSIER_STATE.mkdir(parents=True, exist_ok=True)
    config.FICHIER_DERNIERS_ITEMS.write_text(_serialiser(nouveaux), encoding="utf-8")

    print(f"\nRésumé via le backend « {config.BACKEND} »…", flush=True)
    # Le digest et la note de chaque item viennent du même appel : le scoring ne
    # consomme ni requête ni quota supplémentaires. `nouveaux` est annoté en place.
    corps = summarize.resumer_et_noter(nouveaux, mode="quotidien")

    # Deux cas distincts. Note absente : on la crée. Note déjà là : les items du jour
    # ayant déjà été vus sont dédoublonnés, ce second lot ne contient donc que les
    # nouveautés — il complète le digest existant au lieu de s'y substituer.
    complement = note_du_jour.exists()
    if complement:
        note = render.rendre_mise_a_jour(
            heure=datetime.now(config.FUSEAU).strftime("%Hh%M"),
            corps=corps,
            nb_items=len(nouveaux),
        )
    else:
        note = render.rendre_quotidien(
            jour=config.aujourdhui(),
            corps=corps,
            nb_items=len(nouveaux),
            nb_sources_ok=len(sources) - len(echecs),
            echecs=echecs,
        )

    if args.no_vault:
        print("\n" + note)
        return 0

    vault.verifier_vault()
    if complement:
        chemin = vault.completer_quotidien(config.aujourdhui(), note)
        print(f"\nNote complétée ({len(nouveaux)} nouveaux éléments) : {chemin}")
    else:
        chemin = vault.ecrire_quotidien(config.aujourdhui(), note)
        print(f"\nNote écrite : {chemin}")

    # La note ne contient que de la prose : les URLs y sont noyées. On archive à côté
    # les items bruts, seule matière exploitable pour un affichage cliquable.
    archive = site.enregistrer_jour(config.aujourdhui(), nouveaux, corps)
    print(f"Archive du site : {archive}")

    dedupe.enregistrer_seen(seen)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
