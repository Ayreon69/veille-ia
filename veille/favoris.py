"""
Favoris : les items que j'ai explicitement mis de côté.

Trois choses distinguent un favori du reste de la veille, et expliquent la mécanique
un peu particulière de ce module :

1. **Il ne doit jamais expirer.** Le site n'affiche que 90 jours d'archive, et un
   signet peut dater de 2023. Un favori est donc stocké *en entier* — titre, extrait,
   fiche, score — et non par simple référence à son URL. Il reste affichable une fois
   sa journée sortie de la fenêtre.

2. **Il naît dans le navigateur.** La page est un fichier local ouvert par
   double-clic : elle ne peut rien écrire sur le disque. Le clic sur l'étoile va donc
   dans `localStorage`, et c'est un export explicite qui fait entrer les favoris dans
   le vault — même circuit que les signets, à ceci près qu'ici l'export part de ma
   propre page.

3. **Il peut être retiré.** Sans trace des retraits, la fusion ressusciterait à chaque
   import un favori enlevé la veille. D'où `retires` : une pierre tombale datée par
   URL. Le retrait l'emporte s'il est postérieur à la mise en favori — remettre en
   favori plus tard suffit donc à faire revenir l'item, sans traitement particulier.
"""
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import config

FICHIER = config.RACINE / "data" / "favoris.json"

MOTIF_EXPORT = "favoris-*.json"
DOSSIER_TRAITES = config.DOSSIER_STATE / "favoris-traites"

# Mêmes dossiers que pour les signets : le navigateur dépose où il dépose.
DOSSIERS_EXPORT = [
    Path(os.getenv("VEILLE_DOSSIER_EXPORT") or Path.home() / "Downloads"),
    Path.home() / "Téléchargements",
    config.RACINE,
]

_VIDE = {"favoris": [], "retires": {}}


def charger() -> dict:
    """Lit data/favoris.json. Renvoie une structure vide s'il n'existe pas encore."""
    if not FICHIER.exists():
        return dict(_VIDE, favoris=[], retires={})
    try:
        donnees = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_VIDE, favoris=[], retires={})

    return {
        "favoris": [f for f in donnees.get("favoris", []) if f.get("url")],
        "retires": donnees.get("retires", {}),
    }


def enregistrer(etat: dict) -> Path:
    """Écrit l'état des favoris, du plus récemment ajouté au plus ancien."""
    etat["favoris"].sort(key=lambda f: f.get("favori_le") or "", reverse=True)
    etat["maj"] = datetime.now(config.FUSEAU).isoformat(timespec="seconds")

    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    return FICHIER


def fusionner(etat: dict, export: dict) -> tuple[int, int]:
    """Intègre un export de la page dans l'état, et renvoie (ajoutés, retirés).

    La fusion se fait par URL. Un item déjà connu garde sa date de mise en favori la
    plus ancienne : c'est elle qui ordonne la liste, et un ré-export ne doit pas
    remonter artificiellement de vieux favoris en tête.
    """
    connus = {f["url"]: f for f in etat["favoris"]}
    avant = len(connus)

    for item in export.get("favoris", []):
        url = (item.get("url") or "").strip()
        if not url:
            continue
        item = dict(item, url=url)
        precedent = connus.get(url)
        if precedent and precedent.get("favori_le"):
            item["favori_le"] = min(
                precedent["favori_le"], item.get("favori_le") or precedent["favori_le"]
            )
        connus[url] = item

    etat["retires"].update(export.get("retires", {}))

    # Un retrait ne vaut que s'il est postérieur à la mise en favori. Sinon un item
    # remis en favori après coup serait supprimé par sa propre pierre tombale.
    retires = 0
    for url, quand in etat["retires"].items():
        item = connus.get(url)
        if item and (item.get("favori_le") or "") <= quand:
            del connus[url]
            retires += 1

    etat["favoris"] = list(connus.values())
    return len(connus) - avant + retires, retires


def trouver_export() -> Path | None:
    """Renvoie l'export de favoris le plus récent, s'il en existe un."""
    candidats = [
        chemin
        for dossier in DOSSIERS_EXPORT
        if dossier.is_dir()
        for chemin in dossier.glob(MOTIF_EXPORT)
    ]
    return max(candidats, key=lambda p: p.stat().st_mtime) if candidats else None


def charger_export(chemin: Path) -> dict:
    """Lit un export produit par le bouton « Sauvegarder » de la page."""
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    if isinstance(donnees, list):  # tolérance : une liste nue reste exploitable
        return {"favoris": donnees, "retires": {}}
    return {
        "favoris": donnees.get("favoris", []),
        "retires": donnees.get("retires", {}) or {},
    }


def archiver_export(chemin: Path) -> Path:
    """Déplace un export traité, pour qu'il ne soit pas repris à la synchro suivante."""
    DOSSIER_TRAITES.mkdir(parents=True, exist_ok=True)
    destination = DOSSIER_TRAITES / chemin.name
    if destination.exists():
        destination = DOSSIER_TRAITES / f"{chemin.stem}-{int(time.time())}{chemin.suffix}"
    shutil.move(str(chemin), destination)
    return destination


# --------------------------------------------------------------------------- #
# Note Obsidian
# --------------------------------------------------------------------------- #


def _jour(iso: str) -> str:
    return (iso or "")[:10]


def note_markdown(etat: dict) -> str:
    """Rend la note `Veille IA/Favoris.md`, regroupée par jour de mise en favori.

    La note est réécrite à chaque import, jamais complétée : elle est le reflet exact
    de l'état, retraits compris. C'est la seule note du vault dans ce cas — d'où
    l'avertissement en tête.
    """
    lignes = [
        "---",
        "tags: [veille-ia, favoris]",
        "---",
        "",
        "# Favoris",
        "",
        "> [!warning] Note générée",
        "> Réécrite à chaque import depuis le [[Site]]. Toute modification manuelle sera",
        "> perdue : c'est l'étoile sur la page qui fait foi.",
        "",
    ]

    if not etat["favoris"]:
        lignes.append("*Aucun favori pour l'instant.*")
        return "\n".join(lignes) + "\n"

    lignes.append(f"{len(etat['favoris'])} élément(s) mis de côté.")

    jour_courant = None
    for f in etat["favoris"]:
        jour = _jour(f.get("favori_le"))
        if jour != jour_courant:
            jour_courant = jour
            lignes += ["", f"## Ajoutés le {jour or '(date inconnue)'}", ""]

        titre = (f.get("titre") or f["url"]).replace("[", "(").replace("]", ")")
        details = [d for d in (f.get("source_nom"), f.get("verdict")) if d]
        if f.get("score") is not None:
            details.append(f"{f['score']:.2f}")

        lignes.append(f"- [{titre}]({f['url']})" + (f" — *{' · '.join(details)}*" if details else ""))
        # La cible réelle d'un signet n'est pas le tweet : sans elle, la note
        # renverrait vers X pour un dépôt qu'on cherche à retrouver.
        if f.get("cible") and f["cible"] != f["url"]:
            lignes.append(f"    - ↗ {f['cible']}")
        if f.get("analyse"):
            lignes.append(f"    - {f['analyse']}")

    return "\n".join(lignes) + "\n"
