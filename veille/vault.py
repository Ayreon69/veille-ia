"""
Écriture des notes dans le vault Obsidian.

Le connecteur Obsidian MCP vit dans Claude Code et n'est pas joignable depuis une
tâche planifiée : on écrit donc les fichiers directement sur disque. Obsidian les
détecte immédiatement.
"""
import os
from datetime import date, timedelta
from pathlib import Path

from . import config


def _ecrire_atomique(chemin: Path, contenu: str) -> None:
    """Écrit via un fichier temporaire puis renomme.

    Évite qu'Obsidian ne lise une note tronquée s'il indexe pendant l'écriture.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    temporaire.write_text(contenu, encoding="utf-8")
    os.replace(temporaire, chemin)


def ecrire_quotidien(jour: date, contenu: str) -> Path:
    """Écrit la note quotidienne et renvoie son chemin."""
    chemin = config.DOSSIER_QUOTIDIEN / f"{jour.isoformat()}.md"
    _ecrire_atomique(chemin, contenu)
    return chemin


def completer_quotidien(jour: date, contenu: str) -> Path:
    """Ajoute une section à la note du jour au lieu de la réécrire.

    Une seconde exécution le même jour (rattrapage, déclenchement manuel) ne porte
    que sur les items arrivés depuis la première : ils *complètent* le digest du
    matin, ils ne le remplacent pas. Écraser la note ferait perdre le contenu déjà
    produit — c'est arrivé une fois, le 7 août 2026.
    """
    chemin = config.DOSSIER_QUOTIDIEN / f"{jour.isoformat()}.md"
    existant = chemin.read_text(encoding="utf-8")
    _ecrire_atomique(chemin, existant.rstrip() + "\n\n" + contenu.lstrip())
    return chemin


def ecrire_signets(jour: date, contenu: str) -> Path:
    """Écrit — ou complète — la note de signets du jour.

    Même logique que la note quotidienne : plusieurs relevés dans la journée ajoutent
    des signets, ils ne remplacent pas ceux déjà traités.
    """
    chemin = config.DOSSIER_SIGNETS / f"{jour.isoformat()}.md"
    if chemin.exists():
        existant = chemin.read_text(encoding="utf-8")
        _ecrire_atomique(chemin, existant.rstrip() + "\n\n" + contenu.lstrip())
    else:
        _ecrire_atomique(chemin, contenu)
    return chemin


def ecrire_favoris(contenu: str) -> Path:
    """Écrit la note des favoris, en écrasant la précédente.

    Seule note du vault qui est *remplacée* et non complétée : elle est le reflet de
    l'état des favoris, retraits compris. Une note complétée garderait à jamais un
    favori enlevé depuis.
    """
    chemin = config.VAULT_PATH / config.VAULT_DOSSIER / "Favoris.md"
    _ecrire_atomique(chemin, contenu)
    return chemin


def ecrire_hebdo(nom: str, contenu: str) -> Path:
    """Écrit le digest hebdomadaire et renvoie son chemin."""
    chemin = config.DOSSIER_DIGESTS / f"{nom}.md"
    _ecrire_atomique(chemin, contenu)
    return chemin


def notes_quotidiennes_entre(debut: date, fin: date) -> list[str]:
    """Liste les notes quotidiennes existantes sur l'intervalle (bornes incluses).

    Sert à construire les liens [[...]] du digest hebdomadaire.
    """
    noms = []
    jour = debut
    while jour <= fin:
        if (config.DOSSIER_QUOTIDIEN / f"{jour.isoformat()}.md").exists():
            noms.append(jour.isoformat())
        jour += timedelta(days=1)
    return noms


def lire_notes_quotidiennes(noms: list[str]) -> str:
    """Concatène le contenu des notes quotidiennes, pour nourrir la synthèse hebdo."""
    morceaux = []
    for nom in noms:
        chemin = config.DOSSIER_QUOTIDIEN / f"{nom}.md"
        try:
            morceaux.append(f"--- Note du {nom} ---\n{chemin.read_text(encoding='utf-8')}")
        except OSError:
            continue
    return "\n\n".join(morceaux)


def verifier_vault() -> None:
    """Vérifie que le vault existe avant d'écrire quoi que ce soit."""
    if not config.VAULT_PATH.exists():
        raise RuntimeError(
            f"Vault introuvable : {config.VAULT_PATH}\n"
            "Ajuster VAULT_PATH dans le fichier .env."
        )
