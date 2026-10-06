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
# Depuis le 06/10 : l'alias `gemini-flash-latest`, que Google fait pointer sur le Flash
# courant. Un identifiant figé finit retiré (gemini-2.5-flash, 404 début octobre) ;
# l'alias suit les générations sans qu'on ait à revenir ici.
MODELE_GEMINI = os.getenv("VEILLE_MODELE_GEMINI", "gemini-flash-latest")
# Modèles de repli, essayés dans l'ordre quand le principal reste indisponible après
# ses tentatives. Un 503 de Gemini est une saturation propre à un modèle, pas une
# panne de l'API : du 18 au 24/09, cinq exécutions sur neuf ont échoué sur le seul
# gemini-3.6-flash, et l'hebdo du lundi 21 n'a jamais été écrit. Un modèle d'une
# génération voisine tourne sur une autre capacité et répond d'ordinaire. Le second
# repli est l'alias Flash-Lite : plus modeste, mais lui aussi maintenu par Google.
MODELES_GEMINI_SECOURS = [
    m.strip()
    for m in os.getenv("VEILLE_MODELES_GEMINI_SECOURS", "gemini-3.7-flash,gemini-flash-lite-latest").split(",")
    if m.strip() and m.strip() != MODELE_GEMINI
]

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
#
# Révisé le 06/10 : la veille doit couvrir TOUT le spectre de l'IA. L'ancien profil
# donnait à Claude un plancher de 0,80 : sur huit jours, Claude prenait 90 essentiels
# sur 116, et Qwen, Meta ou Gemini n'en avaient aucun malgré des dizaines d'éléments
# utiles. Claude garde la tête des sections et un bonus, plus de passe-droit.
PROFIL = """\
Développeur français qui utilise l'IA au quotidien et veut suivre TOUT le spectre de
l'intelligence artificielle, sans angle mort.

Domaines suivis — l'ordre est celui de la présentation, pas un filtre :

1. Claude et Claude Code (Anthropic) — l'outil utilisé chaque jour : versions,
   fonctionnalités, changements de comportement, MCP, plugins, hooks, agents, techniques
   d'utilisation.
2. Les modèles de tous les labos : OpenAI, Google, Meta, xAI, Mistral, Microsoft,
   et les labos chinois (Qwen, DeepSeek, Kimi, GLM, MiniMax). Sorties, capacités
   réelles, poids ouverts, benchmarks sérieux, prix et accès.
3. Agents et outils de code : Codex, Cursor, Copilot, Amp et les autres, protocoles,
   tooling LLM.
4. Le reste du spectre : recherche (papiers marquants, nouvelles techniques), image,
   vidéo, voix et musique, robotique et IA incarnée, puces et infrastructure, IA locale,
   sécurité et alignement, IA en science et en santé, régulation et industrie quand
   elles changent la donne.

Peu d'intérêt pour : levées de fonds et nominations de routine, spéculation sur l'AGI,
communiqués sans contenu, opinions qui n'apportent aucun fait nouveau."""


# Depuis le 06/10, le site public embarque ce même profil, et les synthèses hebdo
# qu'il oriente : la page en ligne est d'abord lue par son auteur, depuis son
# téléphone. Ce texte part donc sur Internet — n'y mettre rien de sensible.

# Adresse du Worker de lecture d'articles, embarquée dans le site public. Vide, le
# développement se rabat sur le titre et l'extrait — voir Site public.md.
WORKER_LECTURE = os.getenv("VEILLE_WORKER_LECTURE", "").strip().rstrip("/")

# Adresse du site publié. Elle ne sert qu'aux métadonnées de partage et au flux RSS :
# un aperçu de lien exige des URLs absolues, un chemin relatif n'y est jamais résolu.
URL_PUBLIQUE = os.getenv("VEILLE_URL_PUBLIQUE", "https://veille-ia-rj.pages.dev").strip().rstrip("/")


def charger_sources(inclure_inactives: bool = False) -> list[dict]:
    """Charge sources.yaml et renvoie les sources actives.

    Une source qui déclare `requiert_env` reste dormante tant que cette variable est vide :
    une source payante attend son secret sans afficher d'échec dans chaque note.

    Args:
        inclure_inactives: si True, renvoie aussi les sources marquées actif: false
    """
    with open(SOURCES_YAML, encoding="utf-8") as f:
        sources = yaml.safe_load(f)

    if not inclure_inactives:
        sources = [
            s for s in sources
            if s.get("actif", True)
            and (not s.get("requiert_env") or os.getenv(s["requiert_env"], "").strip())
        ]

    for s in sources:
        s.setdefault("params", {})
        s.setdefault("poids", 1)

    return sources
