"""
Intègre les favoris exportés depuis le site dans le vault.

    python run_favoris.py                    # traite l'export en attente
    python run_favoris.py --dry-run          # dit ce qu'il ferait, n'écrit rien
    python run_favoris.py --fichier X.json   # export désigné explicitement

Sans export en attente, le script sort immédiatement : il peut donc tourner à chaque
synchronisation sans rien coûter. Aucune requête réseau, aucun appel de modèle — il ne
fait que fusionner un fichier local dans `data/favoris.json`, réécrire la note Obsidian
et reconstruire le site.

L'étoile cliquée dans la page va d'abord dans le stockage du navigateur : une page
ouverte en `file://` ne peut rien écrire sur le disque. Le bouton « Sauvegarder » de
l'onglet Favoris produit le fichier que ce script attend.
"""
import argparse
import sys
from pathlib import Path

from veille import favoris, site, vault


def main() -> int:
    parseur = argparse.ArgumentParser(description="Import des favoris du site.")
    parseur.add_argument("--fichier", help="export à traiter (sinon : le plus récent trouvé)")
    parseur.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    args = parseur.parse_args()

    chemin = Path(args.fichier) if args.fichier else favoris.trouver_export()
    if not chemin:
        print("Aucun export de favoris en attente.")
        return 0
    if not chemin.exists():
        print(f"Export introuvable : {chemin}")
        return 1

    print(f"Export : {chemin}")
    export = favoris.charger_export(chemin)
    etat = favoris.charger()
    avant = len(etat["favoris"])

    ajoutes, retires = favoris.fusionner(etat, export)
    total = len(etat["favoris"])
    print(f"  {avant} favori(s) connu(s) -> {total} ({ajoutes} nouveau(x), {retires} retiré(s))")

    if args.dry_run:
        print("\n--dry-run : rien n'a été écrit.")
        return 0

    vault.verifier_vault()
    favoris.enregistrer(etat)
    note = vault.ecrire_favoris(favoris.note_markdown(etat))
    print(f"  note : {note}")

    # Le site rejoue la fusion à l'ouverture, mais il faut qu'il embarque l'état du
    # vault : sans reconstruction, un favori posé depuis un autre navigateur resterait
    # invisible ici.
    print(f"  site : {site.construire()}")
    print(f"  export archivé : {favoris.archiver_export(chemin)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
