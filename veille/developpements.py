"""
Développements d'articles : résumé complet et exemple d'usage, à la demande.

Le bouton du site déclenche un appel modèle sur UN article. Trois précautions, toutes
dictées par le fait que cet appel est déclenché à la main, plusieurs fois par jour :

1. **Le résultat est mis en cache**, un fichier par article dans `data/developpements/`.
   Un article n'est développé qu'une fois : rouvrir le panneau ne rappelle pas le
   modèle, et la page reconstruite le lendemain embarque ce qui a déjà été produit.

   Un fichier par article, et non un fichier unique, pour la raison qui vaut déjà pour
   les archives quotidiennes : une fois écrit, il ne change plus, donc git ne le stocke
   qu'une fois. Un cache global de quelques centaines de kilo-octets serait réécrit
   intégralement à chaque bouton cliqué.

2. **Le contenu est lu, pas deviné.** `enrichir` va chercher le texte de la page — 6000
   caractères là où un signet s'en tient à 2500. Sans cela le modèle brode sur un titre,
   ce qui est exactement le défaut qui avait produit l'erreur factuelle du 8 août.

3. **Le markdown est la forme conservée**, pas le HTML. C'est lui qui part dans git avec
   le reste du vault ; le HTML n'est qu'un rendu, refait à chaque construction de page.
"""
import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from . import config, enrichir, summarize

DOSSIER = config.RACINE / "data" / "developpements"

# Un article mérite plus de matière qu'un signet : à 2500 caractères, le modèle résume
# l'introduction d'un billet de blog en croyant résumer le billet.
LONGUEUR_LECTURE = 6000

# Le serveur est multi-thread : deux clics rapprochés sur le même article produiraient
# deux appels et deux écritures concurrentes. Le verrou est volontairement global et non
# par URL : il sérialise aussi les articles différents, ce qui est ici un avantage — le
# tier gratuit compte les requêtes par minute, et personne ne lit deux développements à
# la fois. Un clic déclenché pendant qu'un autre tourne attend son tour, sans échouer.
_verrou = threading.Lock()


def _nom(url: str) -> str:
    """Nom de fichier stable pour une URL. Le hash évite tout souci de longueur."""
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:16] + ".json"


def charger() -> dict[str, dict]:
    """Renvoie les développements connus, indexés par URL."""
    if not DOSSIER.is_dir():
        return {}

    tout = {}
    for chemin in DOSSIER.glob("*.json"):
        try:
            entree = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # un fichier illisible n'empêche pas de lire les autres
        if entree.get("url"):
            tout[entree["url"]] = entree
    return tout


def lire(url: str) -> dict | None:
    """Renvoie le développement d'une URL, ou None."""
    chemin = DOSSIER / _nom(url)
    if not chemin.exists():
        return None
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ecrire(entree: dict) -> Path:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER / _nom(entree["url"])
    provisoire = chemin.with_suffix(".json.tmp")
    provisoire.write_text(
        json.dumps(entree, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    os.replace(provisoire, chemin)
    return chemin


def obtenir(item: dict, refaire: bool = False) -> dict:
    """Développe un article, ou renvoie le développement déjà en cache.

    Args:
        item: l'item tel qu'il figure dans la page (titre, url, source_nom, extrait)
        refaire: rappelle le modèle même si un développement existe

    Returns:
        {"url", "titre", "lu", "genere", "modele", "corps"} — `corps` en markdown.
    """
    url = (item.get("url") or "").strip()
    if not url:
        raise ValueError("item sans URL")

    with _verrou:
        if not refaire:
            existant = lire(url)
            if existant:
                return existant

        # La cible réelle prime : pour un signet, l'article est le dépôt ou le billet
        # lié, pas le tweet qui le relaie — dont les 280 caractères n'ont rien à
        # développer.
        cible = (item.get("cible") or "").strip() or url
        contenu = enrichir.enrichir(cible, limite=LONGUEUR_LECTURE)

        entree = {
            "url": url,
            "titre": item.get("titre", ""),
            "lu": cible,
            "genere": datetime.now(config.FUSEAU).isoformat(timespec="seconds"),
            "modele": config.MODELE_GEMINI if config.BACKEND == "gemini" else config.MODELE,
            "corps": summarize.developper(item, contenu),
        }
        _ecrire(entree)
        return entree


def oublier(url: str) -> bool:
    """Retire un développement du cache. Le prochain clic le régénérera."""
    chemin = DOSSIER / _nom(url)
    if not chemin.exists():
        return False
    chemin.unlink()
    return True
