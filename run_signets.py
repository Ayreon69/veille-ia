"""
Signets X : export -> lecture des liens -> résumé -> écriture dans Obsidian.

La collecte se fait dans TON navigateur, pas ici : coller `collecte_signets.js` dans la
console sur https://x.com/i/bookmarks produit un fichier JSON. Ce script le retrouve tout
seul dans le dossier de téléchargement et se charge du reste.

Les trois voies automatiques ont été essayées et fermées : X refuse la connexion depuis un
navigateur piloté, une copie de profil Chrome perd la session (chiffrement lié à
l'application), et Chrome 136 interdit le débogage distant sur le profil par défaut. Les
deux dernières sont des protections anti-vol de cookies : on ne les contourne pas.

Usage :
    python run_signets.py                  # traite l'export le plus récent
    python run_signets.py --dry-run        # affiche ce qui serait traité, n'écrit rien
    python run_signets.py --fichier X.json # export désigné explicitement
    python run_signets.py --navigateur     # ancienne voie pilotée (bloquée par X)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from veille import config, enrichir, render, signets, site, summarize, vault

# Seuil de rédaction. Volontairement bas : le tri écarte le hors-sujet franc (cuisine,
# sport, jeux), pas les sujets techniques marginaux. Mieux vaut une fiche inutile qu'un
# signet pertinent passé à la trappe.
SEUIL_DEFAUT = 0.30

# Fiches par appel au modèle. Au-delà, la réponse dépasse le plafond de tokens et se
# retrouve tronquée en plein milieu d'une phrase — constaté avec 120 fiches demandées
# d'un coup lors du premier import.
LOT_REDACTION = 20

_AIDE_EXPORT = """\
Aucun export de signets trouvé.

  1. ouvrir https://x.com/i/bookmarks dans le navigateur, connecté normalement
  2. F12, onglet « Console »
  3. coller le contenu de .veille/collecte_signets.js, puis Entrée
  4. laisser la page défiler : un fichier signets-x-....json se télécharge
  5. relancer cette commande — le fichier est retrouvé tout seul

Dossiers fouillés : {dossiers}"""


def _charger_vus() -> set[str]:
    try:
        return set(json.loads(config.FICHIER_SIGNETS_VUS.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def _enregistrer_vus(vus: set[str]) -> None:
    config.DOSSIER_STATE.mkdir(parents=True, exist_ok=True)
    config.FICHIER_SIGNETS_VUS.write_text(
        json.dumps(sorted(vus), ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _metadonnees(item: dict) -> dict:
    """Complète un signet des champs attendus par le reste du pipeline."""
    return {
        **item,
        "source_id": "signets_x",
        "source_nom": item.get("auteur") or "Signets X",
        "categorie": "signets",
        "poids": 3,
        # C'est un tweet : le texte est une accroche écrite par quelqu'un, pas un fait.
        "titre_utilisateur": True,
    }


def _pour_tri(item: dict) -> dict:
    """Version légère pour la passe de tri : aucun accès réseau.

    Les URL des liens sont jointes au texte — un lien vers github.com ou arxiv.org est
    à lui seul un signal de pertinence, sans qu'il faille ouvrir la page.
    """
    extrait = item.get("extrait") or ""
    if item.get("liens"):
        extrait += "\nLiens : " + " ".join(item["liens"][:3])
    return {**_metadonnees(item), "extrait": extrait}


def _preparer(item: dict) -> dict:
    """Enrichit un signet du contenu de ses liens."""
    morceaux = [f"Tweet : {item['extrait']}"] if item.get("extrait") else []

    for lien in item.get("liens", [])[:2]:  # au-delà, c'est un fil, pas une ressource
        print(f"      lien : {lien[:78]}", flush=True)
        morceaux.append(f"\nLien : {lien}\nContenu de la page :\n{enrichir.enrichir(lien)}")

    return {**_metadonnees(item), "extrait": "\n".join(morceaux)}


def main() -> int:
    parseur = argparse.ArgumentParser(description="Relevé des signets X.")
    parseur.add_argument("--fichier", help="export JSON à traiter, au lieu du plus récent")
    parseur.add_argument(
        "--seuil",
        type=float,
        default=SEUIL_DEFAUT,
        help=f"score minimum pour rédiger une fiche (défaut : {SEUIL_DEFAUT})",
    )
    parseur.add_argument(
        "--dry-run", action="store_true", help="affiche les signets trouvés, sans rien écrire"
    )
    parseur.add_argument(
        "--refaire",
        action="store_true",
        help=(
            "retraite tous les signets de l'export, même déjà vus, et remplace la note "
            "et l'archive du jour. À utiliser après un correctif de collecte."
        ),
    )
    parseur.add_argument(
        "--navigateur",
        action="store_true",
        help="ancienne voie par navigateur piloté — bloquée par X, conservée pour essai",
    )
    parseur.add_argument(
        "--connexion",
        action="store_true",
        help="ouvre un navigateur pour se connecter à X (voie pilotée uniquement)",
    )
    parseur.add_argument("--limite", type=int, default=40, help="voie pilotée : signets lus")
    parseur.add_argument(
        "--visible", action="store_true", help="voie pilotée : navigateur affiché"
    )
    args = parseur.parse_args()

    if args.connexion:
        signets.ouvrir_session()
        print("\nSession enregistrée. Lancer `python run_signets.py --navigateur`.")
        return 0

    export = None
    if args.navigateur:
        print(f"Voie pilotée (profil : {signets.PROFIL_NAVIGATEUR})\n", flush=True)
        try:
            trouves = signets.collecter(limite=args.limite, headless=not args.visible)
        except signets.SessionAbsente as e:
            print(f"\n{e}")
            return 1
    else:
        export = Path(args.fichier) if args.fichier else signets.trouver_export()
        if export is None:
            print(_AIDE_EXPORT.format(
                dossiers=", ".join(str(d) for d in signets.DOSSIERS_EXPORT)
            ))
            return 1
        if not export.exists():
            print(f"Fichier introuvable : {export}")
            return 1

        print(f"Export : {export}", flush=True)
        trouves = signets.charger_export(export)

    vus = _charger_vus()
    if args.refaire:
        nouveaux = trouves
        print(f"{len(trouves)} signets lus — retraitement complet demandé\n")
    else:
        nouveaux = [it for it in trouves if it["url"] not in vus]
        print(f"{len(trouves)} signets lus, {len(nouveaux)} nouveaux\n")

    if args.dry_run:
        for it in trouves:
            marque = "NOUVEAU" if it["url"] not in vus else "  déjà  "
            print(f"  [{marque}] {it['titre'][:70]}")
            for lien in it.get("liens", []):
                print(f"            -> {lien[:80]}")
        print("\n--dry-run : rien écrit, état inchangé.")
        return 0

    if not nouveaux:
        # L'export est archivé quand même : sans cela, il serait repris à chaque
        # synchronisation, toutes les 3 heures, pour ne rien produire.
        if export:
            print(f"Aucun nouveau signet — export archivé : {signets.archiver_export(export).name}")
        else:
            print("Aucun nouveau signet.")
        return 0

    # Passe 1 — tri sur le seul texte du tweet. Juger la pertinence ne demande pas
    # d'ouvrir les liens, et un premier import peut contenir des centaines de signets
    # sans rapport avec le profil : les enrichir tous serait du gaspillage pur.
    print(f"Tri de {len(nouveaux)} signets via « {config.BACKEND} »…", flush=True)
    allege = [_pour_tri(it) for it in nouveaux]
    summarize.noter(allege)
    # strict=True : les deux listes sont construites l'une depuis l'autre, une
    # différence de longueur serait un bug silencieux de notation.
    for source, note in zip(nouveaux, allege, strict=True):
        source["score"] = note.get("score")

    retenus = [it for it in nouveaux if (it.get("score") or 0) >= args.seuil]
    ecartes = len(nouveaux) - len(retenus)
    print(f"\n{len(retenus)} retenus (score ≥ {args.seuil}), {ecartes} écartés\n")

    if not retenus:
        print("Aucun signet ne dépasse le seuil — rien à rédiger.")
        _enregistrer_vus(vus | {it["url"] for it in nouveaux})
        if export:
            print(f"Export archivé : {signets.archiver_export(export).name}")
        return 0

    # Passe 2 — lecture des liens, puis rédaction par lots. Un lot par appel : demander
    # 120 fiches d'un coup dépasse le plafond de tokens et tronque la réponse en plein
    # milieu, ce qui est arrivé au premier import du 9 août.
    print("Lecture des liens…", flush=True)
    prets = []
    for i, it in enumerate(retenus, 1):
        print(f"  {i}/{len(retenus)} {it['titre'][:60]}", flush=True)
        prets.append(_preparer(it))

    morceaux = []
    for debut in range(0, len(prets), LOT_REDACTION):
        lot = prets[debut : debut + LOT_REDACTION]
        print(
            f"\nRédaction {debut + 1}-{debut + len(lot)} sur {len(prets)}…", flush=True
        )
        morceaux.append(summarize.resumer(lot, mode="signets"))
    corps = "\n\n".join(morceaux)

    # Sans ce rattachement, l'analyse resterait confinée à la note Obsidian et le site
    # n'afficherait que le texte brut du tweet — soit rien de plus que X lui-même.
    associes = signets.associer_fiches(corps, prets)
    print(f"\n{associes}/{len(prets)} fiches rattachées à leur signet")
    for it in prets:
        if it.get("titre_fiche"):
            it["titre"] = it["titre_fiche"]

    # Les écartés sont listés sans fiche, en repli. Ils ne méritent pas d'appel au
    # modèle, mais les faire disparaître sans trace serait pire : on doit pouvoir
    # vérifier que le tri n'a pas mis de côté quelque chose d'intéressant.
    if ecartes:
        lignes = "\n".join(
            f"> - [{it['titre'][:90]}]({it['url']}) — {it.get('score', 0):.2f}"
            for it in sorted(nouveaux, key=lambda x: -(x.get("score") or 0))
            if (it.get("score") or 0) < args.seuil
        )
        corps += f"\n\n> [!note]- Écartés par le tri ({ecartes})\n{lignes}\n"

    jour = config.aujourdhui()
    chemin_note = config.DOSSIER_SIGNETS / f"{jour.isoformat()}.md"

    if args.refaire:
        # Note réécrite et archive purgée : sans cela, la note se verrait ajouter une
        # seconde version des mêmes fiches, et l'archive garderait les anciennes — un
        # item déjà connu par son URL n'y est jamais mis à jour.
        retires = site.retirer_categorie(jour, "signets")
        chemin_note.unlink(missing_ok=True)
        print(f"Remplacement : note réécrite, {retires} signets retirés de l'archive")

    if chemin_note.exists():
        note = render.rendre_ajout_signets(
            heure=datetime.now(config.FUSEAU).strftime("%Hh%M"),
            corps=corps,
            nb_items=len(prets),
        )
    else:
        note = render.rendre_signets(jour=jour, corps=corps, nb_items=len(prets))

    vault.verifier_vault()
    chemin = vault.ecrire_signets(jour, note)
    print(f"\nNote écrite : {chemin}")

    # Les signets rejoignent l'archive du site, dans leur propre catégorie.
    archive = site.enregistrer_jour(jour, prets)
    print(f"Archive du site : {archive}")

    # Reconstruction immédiate : archiver sans régénérer laissait l'onglet « Mes
    # signets » vide jusqu'à la synchronisation suivante, ce qui donne l'impression
    # que le relevé n'a rien produit.
    print(f"Site régénéré   : {site.construire()}")

    _enregistrer_vus(vus | {it["url"] for it in nouveaux})
    if export:
        print(f"Export archivé : {signets.archiver_export(export).name}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
