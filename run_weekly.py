"""
Digest hebdomadaire : synthèse transversale des 7 derniers jours.

Contrairement au quotidien, ce script part des notes quotidiennes déjà écrites
dans le vault et les relie, plutôt que de recollecter les sources.

Usage :
    python run_weekly.py
    python run_weekly.py --no-vault
"""
import argparse
import sys
from datetime import date, timedelta

from veille import config, render, summarize, vault


def main() -> int:
    parseur = argparse.ArgumentParser(description="Digest de veille IA hebdomadaire.")
    parseur.add_argument(
        "--no-vault", action="store_true", help="affiche le digest sans écrire dans le vault"
    )
    parseur.add_argument(
        "--semaine",
        metavar="AAAA-Wxx",
        help="régénère une semaine passée, ex. 2026-W33 (défaut : la dernière complète)",
    )
    args = parseur.parse_args()

    # Le digest porte sur la dernière semaine ISO **complète**, du lundi au dimanche,
    # et non sur les sept derniers jours à cheval sur deux semaines. Lancé le lundi
    # matin, il synthétise donc la semaine qui vient de s'achever — et relancé un
    # mercredi, il produit exactement la même chose plutôt qu'un décalage d'un jour.
    if args.semaine:
        try:
            an, _, numero = args.semaine.partition("-W")
            fin = date.fromisocalendar(int(an), int(numero), 7)   # le dimanche
        except ValueError:
            print(f"Semaine invalide : {args.semaine} — attendu AAAA-Wxx, par exemple 2026-W33.")
            return 1
    else:
        aujourd_hui = config.aujourdhui()
        fin = aujourd_hui - timedelta(days=aujourd_hui.isoweekday())   # dimanche écoulé
    debut = fin - timedelta(days=6)                                     # son lundi

    noms = vault.notes_quotidiennes_entre(debut, fin)
    if not noms:
        print(
            f"Aucune note quotidienne entre {debut} et {fin} — "
            "lancer run_daily.py quelques jours avant de générer un hebdo."
        )
        return 1

    print(f"{len(noms)} notes quotidiennes trouvées : {', '.join(noms)}")
    contenu = vault.lire_notes_quotidiennes(noms)

    # La synthèse hebdo travaille sur du texte déjà rédigé, pas sur des items bruts :
    # on le présente au modèle sous la forme d'un item unique.
    items = [
        {
            "source_nom": "Notes quotidiennes de la semaine",
            "titre": f"Veille du {debut} au {fin}",
            "url": "",
            "date": None,
            "extrait": contenu,
        }
    ]

    print(f"\nSynthèse via le backend « {config.BACKEND} »…", flush=True)
    ancien_max = summarize.LONGUEUR_EXTRAIT
    summarize.LONGUEUR_EXTRAIT = 200_000  # les notes entières doivent passer
    try:
        corps = summarize.resumer(items, mode="hebdo")
    finally:
        summarize.LONGUEUR_EXTRAIT = ancien_max

    note = render.rendre_hebdo(
        debut=debut, fin=fin, corps=corps, nb_items=len(noms), notes_quotidiennes=noms
    )

    if args.no_vault:
        print("\n" + note)
        return 0

    vault.verifier_vault()
    chemin = vault.ecrire_hebdo(render.nom_note_hebdo(fin), note)
    print(f"\nDigest écrit : {chemin}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
