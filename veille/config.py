"""
Chargement de la configuration : sources.yaml + variables d'environnement.
"""
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent

load_dotenv(RACINE / ".env")

# Chemins
SOURCES_YAML = RACINE / "sources.yaml"
DOSSIER_STATE = RACINE / "state"
FICHIER_SEEN = DOSSIER_STATE / "seen.json"
FICHIER_DERNIERS_ITEMS = DOSSIER_STATE / "last_items.json"

# Vault Obsidian. Le script écrit les fichiers directement sur disque : le connecteur
# MCP vit dans Claude Code et n'est pas joignable depuis une exécution automatique.
#
# Le collecteur vit dans `.veille/` à la racine du vault, donc le vault est le dossier
# parent. Cette résolution relative fonctionne à l'identique en local et dans un runner
# GitHub, où le dépôt est cloné à un chemin quelconque.
VAULT_PATH = Path(os.getenv("VAULT_PATH") or RACINE.parent)
VAULT_DOSSIER = os.getenv("VAULT_DOSSIER", "Veille IA")
DOSSIER_QUOTIDIEN = VAULT_PATH / VAULT_DOSSIER / "Quotidien"
DOSSIER_DIGESTS = VAULT_PATH / VAULT_DOSSIER / "Digests"
DOSSIER_SIGNETS = VAULT_PATH / VAULT_DOSSIER / "Signets"
FICHIER_SIGNETS_VUS = DOSSIER_STATE / "signets_vus.json"

# Moteur de résumé
BACKEND = os.getenv("VEILLE_BACKEND", "cli").lower()
MODELE = os.getenv("VEILLE_MODELE", "claude-sonnet-5")
# Les identifiants de modèles Gemini évoluent vite : garder ce réglage externalisé.
# `python -m veille.summarize --modeles-gemini` liste ceux que la clé peut appeler.
MODELE_GEMINI = os.getenv("VEILLE_MODELE_GEMINI", "gemini-3.6-flash")

# Collecte
# Fuseau de référence pour dater les notes. Sans lui, une exécution GitHub Actions
# utiliserait UTC : un run lancé à 00h30 heure de Paris écrirait dans la note de la
# veille, ce qui ne correspond à rien pour qui lit le vault depuis la France.
FUSEAU = ZoneInfo(os.getenv("VEILLE_FUSEAU", "Europe/Paris"))


def aujourdhui() -> date:
    """Date du jour dans le fuseau de référence, quel que soit le lieu d'exécution."""
    return datetime.now(FUSEAU).date()


TIMEOUT_HTTP = 20.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DELAI_ENTRE_SOURCES = 0.5
# Intervalle minimum entre deux requêtes vers un même domaine. Reddit limite par
# domaine et non par URL : deux subreddits lus coup sur coup déclenchent un 429.
# Valeur mesurée — 5s, 10s et 20s d'écart échouent encore, 60s passe. Coût réel :
# une minute d'attente par run, sans incidence pour une tâche planifiée.
DELAI_DOMAINES = {"reddit.com": 60.0}
# Purge des URLs vues au-delà de ce délai.
RETENTION_SEEN_JOURS = 60

# Longueur d'extrait conservée à la collecte. Suffisant pour un article de presse,
# dont le résumé tient en quelques phrases. Les changelogs sont un cas à part : leur
# valeur est dans la liste complète des puces, pas dans les deux premières. Une
# release de Claude Code en compte une vingtaine, et tronquer à 400 caractères a
# fait manquer l'annonce de la messagerie inter-sessions. D'où `extrait_max` par
# source dans sources.yaml.
EXTRAIT_MAX_DEFAUT = 400

# Voies de lecture, dérivées du score attribué à chaque item par le modèle.
# Le principe est repris de llmgram.app : trier par item plutôt que par source, pour
# que la page s'ouvre sur l'essentiel sans masquer le reste. Les seuils sont les leurs,
# mais le score, lui, mesure l'intérêt POUR CE PROFIL et non l'importance générale —
# sinon une sortie Gemini passerait devant une release de Claude Code.
SEUIL_ESSENTIEL = 0.85
SEUIL_UTILE = 0.50


def voie(score: float | None) -> str:
    """Classe un score en voie de lecture. Un item non noté reste visible."""
    if score is None:
        return "non_note"
    if score >= SEUIL_ESSENTIEL:
        return "essentiel"
    if score >= SEUIL_UTILE:
        return "utile"
    return "bruit"


# Critère de pertinence injecté dans le prompt de résumé.
# C'est ici que se fait le filtrage — pas dans la liste de sources.
PROFIL = """\
Développeur français qui utilise l'IA au quotidien dans son travail.

Centres d'intérêt par ordre de priorité STRICT — cet ordre gouverne à la fois ce qu'on
garde et l'ordre dans lequel on le présente :

1. PRIORITÉ ABSOLUE — Claude et Claude Code (Anthropic) : nouvelles versions, fonctionnalités,
   changements de comportement, MCP, plugins, hooks, agents, retours d'expérience et
   techniques d'utilisation. Tout élément de cette catégorie doit être conservé et remonté
   en tête, même s'il paraît mineur.
2. Les autres modèles : OpenAI/GPT, Kimi, Qwen, DeepSeek, Gemini, Mistral, Llama.
   Sorties, capacités réelles, poids ouverts, benchmarks sérieux, comparaisons.
3. Agentic coding en général : autres outils et agents de code, protocoles, tooling LLM.
4. Automatisation, scripting, Python et data engineering — dont une migration SAS vers
   Python en cours.

Peu d'intérêt pour : levées de fonds, nominations, débats réglementaires, spéculation sur
l'AGI, communiqués d'entreprise sans contenu technique."""


# Profil du site PUBLIC. Le profil ci-dessus décrit une personne : l'employer pour
# développer un article à la demande d'un inconnu n'aurait aucun sens, et publierait au
# passage des détails personnels dans le prompt embarqué dans la page.
#
# Celui-ci décrit le lectorat du site, pas son auteur. Il reste orienté — c'est la ligne
# éditoriale, et elle est annoncée sur la page — mais il ne dit rien de personne.
PROFIL_PUBLIC = """\
Développeur qui utilise l'IA au quotidien dans son travail.

Centres d'intérêt, par ordre de priorité :

1. Claude et Claude Code (Anthropic) : versions, fonctionnalités, MCP, plugins, hooks,
   agents, techniques d'utilisation.
2. Les autres modèles : OpenAI/GPT, Gemini, Mistral, Llama, Qwen, DeepSeek, Kimi.
   Sorties, capacités réelles, poids ouverts, benchmarks sérieux.
3. Agentic coding en général : outils et agents de code, protocoles, tooling LLM.
4. Automatisation, scripting, Python et data engineering.

Peu d'intérêt pour : levées de fonds, nominations, débats réglementaires, spéculation sur
l'AGI, communiqués d'entreprise sans contenu technique."""

# Adresse du Worker de lecture d'articles, embarquée dans le site public. Vide, le
# développement se rabat sur le titre et l'extrait — voir Site public.md.
WORKER_LECTURE = os.getenv("VEILLE_WORKER_LECTURE", "").strip().rstrip("/")

# Adresse du site publié. Elle ne sert qu'aux métadonnées de partage et au flux RSS :
# un aperçu de lien exige des URLs absolues, un chemin relatif n'y est jamais résolu.
URL_PUBLIQUE = os.getenv("VEILLE_URL_PUBLIQUE", "https://veille-ia-rj.pages.dev").strip().rstrip("/")


def charger_sources(inclure_inactives: bool = False) -> list[dict]:
    """Charge sources.yaml et renvoie les sources actives.

    Args:
        inclure_inactives: si True, renvoie aussi les sources marquées actif: false
    """
    with open(SOURCES_YAML, encoding="utf-8") as f:
        sources = yaml.safe_load(f)

    if not inclure_inactives:
        sources = [s for s in sources if s.get("actif", True)]

    for s in sources:
        s.setdefault("params", {})
        s.setdefault("poids", 1)

    return sources
