"""
Étage de résumé, derrière une interface unique et trois backends interchangeables.

- "gemini" : API Gemini en REST (GEMINI_API_KEY). Tier gratuit largement suffisant :
             ~1 requête/jour pour un plafond à 1500.
- "cli"    : appelle le binaire `claude` en sous-processus (abonnement Claude Code).
- "api"    : SDK anthropic (nécessite ANTHROPIC_API_KEY).

Le backend se choisit par VEILLE_BACKEND, sans rien changer au reste du pipeline.
Le filtrage de la pertinence se fait ici, dans le prompt — pas dans la liste de sources.
"""
import json
import os
import shutil
import subprocess
import time
from datetime import datetime

import httpx

from . import config

# Plafond d'items envoyés au modèle : au-delà, le prompt devient coûteux sans
# gagner en qualité (les items sont déjà triés par poids de source puis par date).
MAX_ITEMS = 120
# Plafond de sécurité seulement : la vraie limite est appliquée à la collecte, par
# source (`extrait_max` dans sources.yaml). Une seconde troncature ici à 300 caractères
# annulait le bénéfice des extraits longs des changelogs.
LONGUEUR_EXTRAIT = 6000

_CONSIGNES_QUOTIDIEN = """\
Rédige un digest de veille QUOTIDIEN en français, lisible en 5 minutes environ.

Structure attendue (omets une section si elle est vide, n'en invente pas d'autres) :

## À retenir
3 à 5 puces maximum : ce qui mérite vraiment l'attention aujourd'hui. S'il existe le
moindre élément sur Claude ou Claude Code, il ouvre cette section.

## Claude & Claude Code
## Autres modèles
## Agentic coding & outils
## Écosystème & reste

Dans les sections, une entrée par sujet, au format :
- **Titre court** — une ou deux phrases expliquant ce que c'est et pourquoi ça compte. [lien](url)

Règles :
- L'ordre des sections reflète la priorité du profil et ne doit jamais changer.
  « Claude & Claude Code » couvre Anthropic ; « Autres modèles » couvre OpenAI, Kimi,
  Qwen, DeepSeek, Gemini, Mistral, Llama.
- Écarte sans état d'âme tout ce qui ne correspond pas au profil. Un digest court et
  pertinent vaut mieux qu'un digest exhaustif. Ne conserve rien par remplissage.
- Seule exception à la sévérité du filtre : les éléments sur Claude et Claude Code se
  gardent tous, même mineurs.
- Fusionne les doublons : plusieurs sources relaient souvent la même annonce. Une seule
  entrée, avec le lien le plus informatif.
- N'invente jamais un fait absent des titres et extraits fournis. En cas de doute sur le
  contenu d'un article, reste factuel sur ce que dit le titre.
- N'ajoute JAMAIS de comparaison, de classement, de position ou de superlatif qui ne
  figure pas explicitement dans la source. Écrire « devant tel modèle », « le meilleur »
  ou « en première place » alors que la source ne le dit pas est une faute grave, même si
  cela paraît plausible.
- Les éléments marqués « titre d'utilisateur » viennent de Hacker News ou Reddit : ce sont
  des affirmations postées par quelqu'un, pas des faits vérifiés, et souvent déjà périmées
  quand il s'agit d'un classement. Attribue-les explicitement — « selon un post Hacker
  News », « d'après un fil r/LocalLLaMA » — au lieu de les présenter comme établies.
- Pas de préambule ni de conclusion : commence directement par "## À retenir"."""

_CONSIGNES_SIGNETS = """\
Voici des tweets que l'utilisateur a lui-même mis en signet, avec le contenu de la page
liée quand elle a pu être récupérée. Il les a choisis : ne juge pas s'ils méritent d'être
là, explique ce qu'ils sont et à quoi ils lui servent.

Une entrée par signet, dans cet ordre exact :

### Titre court et descriptif
**Ce que c'est** — deux ou trois phrases concrètes. Pour un dépôt, dis ce qu'il fait, dans
quel langage, et son degré de maturité. Pour un article, l'idée centrale et le résultat.
**Pour toi** — commence par « Utile : », « À tester : », « Pour info : » ou « Peu
d'intérêt : », puis une phrase qui justifie, rattachée au profil ci-dessus.
[lien](url du tweet) · via @auteur

Règles :
- Appuie-toi en priorité sur le contenu de la page liée, pas sur le texte du tweet, qui
  n'est qu'une accroche écrite par quelqu'un.
- Si le contenu du lien n'a pas pu être récupéré, dis-le franchement plutôt que de
  deviner ce que contient la page.
- N'invente aucune caractéristique technique absente des éléments fournis. Pas de
  comparaison ni de superlatif qui n'y figure pas.
- « Peu d'intérêt » est une réponse acceptable et attendue : elle vaut mieux qu'un
  enthousiasme de complaisance.
- Pas de préambule : commence directement par le premier "###"."""

_CONSIGNES_SCORES = """

Une fois le texte terminé, et seulement à ce moment, écris une ligne contenant
exactement <<<SCORES>>>, puis un tableau JSON compact notant CHAQUE élément fourni,
identifié par son numéro #N :

<<<SCORES>>>
[{"i":0,"s":0.92},{"i":1,"s":0.31}]

Le score va de 0 à 1 et mesure l'intérêt POUR CE PROFIL — pas l'importance générale
dans l'actualité IA. Mélange pondéré de :
- nouveauté : information neuve, ou Nième reprise d'une annonce déjà relayée ?
- importance pour ce profil : est-ce que cela change sa façon de travailler ? Tout ce
  qui concerne Claude, Claude Code, Anthropic ou MCP part de 0,80 au minimum.
- rigueur : éléments concrets et vérifiables, ou communication sans contenu ?
- fraîcheur : une annonce du jour prime sur le rappel d'un fait ancien.

Repères : 0,85 et plus = à ne pas rater. 0,50 à 0,84 = utile mais dispensable.
Sous 0,50 = bruit. Un titre d'utilisateur invérifiable ne dépasse pas 0,60.
Note tous les éléments, n'invente aucun numéro au-delà du dernier fourni, et n'écris
rien après le tableau."""

# La synthèse hebdo se lit dans un navigateur, pas dans un terminal : la forme compte
# autant que le fond. L'ancienne version produisait quatre paragraphes de 145 mots en
# moyenne — du texte juste, illisible en diagonale. Le détail vit déjà dans les digests
# quotidiens ; l'hebdo sert à voir les tendances, et rien d'autre.
_CONSIGNES_HEBDO = """\
Rédige une synthèse HEBDOMADAIRE en français. Elle doit se lire en trois minutes : le
détail est déjà dans les digests quotidiens, ici on veut seulement les tendances.

Structure exacte :

## L'essentiel
Trois puces, une phrase chacune. Ce qu'il faut retenir si on ne lit rien d'autre.

## <titre du thème>
2 à 4 sections, une par tendance de fond. Le titre dit quelque chose plutôt que de
nommer une catégorie : « Claude Code durcit le contrôle des agents », et non
« Claude Code ». Six mots au maximum. Sous chaque titre, un paragraphe, deux au plus.

## À creuser
2 ou 3 puces : ce qui mérite un vrai temps d'exploration, et pourquoi.

Chaque section répond à « qu'est-ce que ça change ? », et non « qu'est-ce qui est
sorti ? ». Une suite de faits juxtaposés n'est pas une synthèse : ce qu'on attend, c'est
le fil qui les relie.

Règles de forme, aussi importantes que le fond :
- Un paragraphe fait 40 à 60 mots. En dessous de 40 tu télégraphies, et le lien entre
  les faits disparaît ; au-dessus de 60 le paragraphe devient un pavé.
- Une phrase ne dépasse pas 25 mots. Coupe plutôt que d'enchaîner par des virgules.
- Vise 2 000 à 2 500 caractères de prose en tout. Nettement moins, c'est que tu as
  énuméré au lieu de relier.
- Tutoie, comme le reste du site. Jamais de vouvoiement.
- Mets en **gras** le terme dont on se souviendra, une à deux fois par paragraphe.
- Le `code en ligne` est réservé aux commandes, options et identifiants réellement
  tapés. Un nom de produit ou de modèle s'écrit en texte normal.
- N'invente aucun fait absent des éléments fournis.
- Pas de préambule : commence directement par "## L'essentiel"."""


def _formater_items(items: list[dict], limite: int | None = None) -> str:
    """Met les items en liste compacte pour le prompt.

    Les titres issus de Hacker News et Reddit sont signalés au modèle : ce sont des
    affirmations d'utilisateurs, pas des faits vérifiés. Sans ce marquage, un titre
    comme « X est désormais le meilleur modèle » est repris comme une vérité établie,
    alors qu'il peut être faux ou déjà périmé.
    """
    lignes = []
    for i, it in enumerate(items[: limite or MAX_ITEMS]):
        date = it["date"].strftime("%Y-%m-%d") if it.get("date") else "date inconnue"
        marque = " | titre d'utilisateur" if it.get("titre_utilisateur") else ""
        # Le numéro est la clé de rattachement des scores renvoyés par le modèle.
        source = it.get("source_nom") or it.get("source_id") or "source inconnue"
        ligne = f"- #{i} [{source} | {date}{marque}] {it.get('titre', '')}\n  {it.get('url', '')}"
        extrait = (it.get("extrait") or "")[:LONGUEUR_EXTRAIT]
        if extrait:
            ligne += f"\n  {extrait}"
        lignes.append(ligne)
    return "\n".join(lignes)


_CONSIGNES_TRI = """\
Note chaque élément fourni de 0 à 1 selon son intérêt POUR CE PROFIL — pas selon son
importance générale. Mélange pondéré de :
- importance pour ce profil : est-ce que cela change sa façon de travailler ? Tout ce qui
  concerne Claude, Claude Code, Anthropic ou MCP part de 0,80 au minimum.
- nouveauté : information neuve, ou reprise d'une annonce déjà relayée ?
- rigueur : ressource concrète et exploitable, ou simple opinion ?

Repères : 0,85 et plus = à ne pas rater. 0,50 à 0,84 = utile. 0,20 à 0,49 = marginal.
Sous 0,20 = hors sujet pour ce profil (cuisine, sport, jeux vidéo, politique, religion,
vie quotidienne — quel que soit l'intérêt qu'y trouve la personne par ailleurs).

Réponds UNIQUEMENT par un tableau JSON compact, sans phrase avant ni après :
[{"i":0,"s":0.92},{"i":1,"s":0.05}]

Note tous les éléments, et n'invente aucun numéro au-delà du dernier fourni."""

CONSIGNES_DEVELOPPER = """\
On te donne UN article, avec le texte de la page quand il a pu être récupéré. Produis un
développement complet, en français, directement exploitable. Structure imposée :

## En bref
Deux ou trois phrases : de quoi il s'agit et pourquoi ça existe.

## Le détail
Le contenu de l'article, développé en puces. Ce qui est annoncé ou démontré, comment ça
marche, les chiffres et les limites annoncées. C'est la partie la plus longue : elle doit
dispenser d'aller lire l'article.

## Exemple d'usage
Un cas concret et applicable PAR CE PROFIL, pas une généralité. Commande, extrait de code
ou enchaînement d'étapes selon ce qui convient — dans un bloc ``` quand c'est du code.
Si le sujet ne se prête à aucun usage direct (annonce d'entreprise, analyse de marché),
écris à la place ce qu'il faut en retenir et en quoi ça change la donne, sans inventer un
usage artificiel.

## À retenir
Une ou deux lignes : ce que ça change concrètement pour ce profil. Le dire franchement si
la réponse est « rien pour l'instant » — c'est une information utile, pas un échec.

Règles :
- Le poste de travail est un PC sous Windows 11, PowerShell et Python 3.11 : une commande
  proposée doit y tourner telle quelle. Pas d'`apt install` ni de `brew`.
- Adresse-toi directement à la personne, sans vouvoiement, comme le reste du site.
- Ne t'appuie QUE sur le contenu fourni. Si le texte de la page n'a pas été récupéré,
  dis-le en une ligne au début et développe à partir du seul titre, sans rien inventer.
- Pas de préambule, pas de conclusion, pas de « voici ». Commence par « ## En bref ».
- Pas de superlatif commercial. Ce qui est incertain est présenté comme incertain."""


_CONSIGNES = {
    "quotidien": _CONSIGNES_QUOTIDIEN + _CONSIGNES_SCORES,
    # Pas de bloc de scores ici : le tri a déjà eu lieu, en amont et sur tous les items.
    "signets": _CONSIGNES_SIGNETS,
    "tri": _CONSIGNES_TRI,
    # Un seul article, et tout son contenu : le seul mode où le prompt porte sur une
    # ressource lue en entier plutôt que sur une liste de titres.
    "developper": CONSIGNES_DEVELOPPER,
    # L'hebdo travaille sur un item unique — les notes quotidiennes concaténées : il n'y
    # a rien à noter.
    "hebdo": _CONSIGNES_HEBDO,
}


def construire_prompt(items: list[dict], mode: str, limite: int | None = None) -> str:
    """Assemble le prompt complet : profil, consignes, items."""
    consignes = _CONSIGNES.get(mode, _CONSIGNES_QUOTIDIEN)
    nombre = min(len(items), limite or MAX_ITEMS)
    return (
        f"Tu produis une veille IA personnelle pour ce profil :\n\n{config.PROFIL}\n\n"
        f"{consignes}\n\n"
        f"Voici les {nombre} éléments collectés :\n\n"
        f"{_formater_items(items, limite)}"
    )


def _resumer_cli(prompt: str) -> str:
    """Appelle le binaire `claude` en sous-processus.

    CLAUDECODE doit être retiré de l'environnement : sans cela, le CLI refuse de
    démarrer avec « cannot be launched inside another Claude Code session ».
    Le prompt passe par stdin pour éviter la limite de longueur des arguments Windows.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CLAUDECODE", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_ENTRYPOINT")
    }

    # Sous Windows, `claude` est un .cmd : subprocess ne le trouve pas sans chemin
    # explicite. shutil.which le résout, ce qui évite de passer par shell=True.
    binaire = shutil.which("claude")
    if not binaire:
        raise RuntimeError(
            "Binaire `claude` introuvable dans le PATH. "
            "Utiliser VEILLE_BACKEND=api, ou installer Claude Code."
        )

    resultat = subprocess.run(
        [binaire, "-p", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=600,
    )

    if resultat.returncode != 0:
        erreur = (resultat.stderr or resultat.stdout or "").strip()
        if "401" in erreur or "authenticate" in erreur.lower():
            raise RuntimeError(
                "Le CLI claude n'est plus authentifié (401, token OAuth expiré).\n"
                "  → Correctif ponctuel : lancer `claude` dans un terminal et se reconnecter.\n"
                "  → Correctif durable pour une tâche planifiée : passer sur l'API, en\n"
                "    définissant ANTHROPIC_API_KEY et VEILLE_BACKEND=api dans le .env.\n"
                "  Un token OAuth expire périodiquement et exige une reconnexion manuelle,\n"
                "  ce qui casse silencieusement une exécution automatique."
            )
        raise RuntimeError(f"claude CLI a échoué (code {resultat.returncode}) : {erreur[:400]}")

    return resultat.stdout.strip()


def _resumer_api(prompt: str) -> str:
    """Appelle l'API Anthropic via le SDK officiel."""
    from anthropic import Anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "VEILLE_BACKEND=api mais ANTHROPIC_API_KEY est absente de l'environnement."
        )

    client = Anthropic()
    reponse = client.messages.create(
        model=config.MODELE,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(bloc.text for bloc in reponse.content if bloc.type == "text").strip()


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _resumer_gemini(prompt: str) -> str:
    """Appelle l'API Gemini en REST direct.

    Volontairement sans SDK : httpx est déjà une dépendance du projet, et l'endpoint
    generateContent est stable. Une dépendance de moins à maintenir.
    """
    cle = os.getenv("GEMINI_API_KEY")
    if not cle:
        raise RuntimeError(
            "VEILLE_BACKEND=gemini mais GEMINI_API_KEY est absente.\n"
            "  → Créer une clé sur https://aistudio.google.com/apikey "
            "et la placer dans le .env."
        )

    # Gemini renvoie régulièrement des 503 quand le service est chargé. Sans ces
    # tentatives, un aléa passager de quelques secondes fait échouer tout le run
    # et la veille du jour est perdue — constaté dès la première exécution en CI.
    transitoires = {429, 500, 502, 503, 504}
    reponse = None

    for tentative in range(4):
        reponse = httpx.post(
            f"{_GEMINI_BASE}/models/{config.MODELE_GEMINI}:generateContent",
            headers={"x-goog-api-key": cle, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                # Large : les modèles récents consomment des tokens de réflexion avant
                # de produire la réponse, et un plafond trop bas tronque le digest.
                # Relevé de 8000 à 12000 depuis l'ajout du bloc de scores, qui ajoute
                # jusqu'à 120 entrées JSON après le digest.
                "generationConfig": {"maxOutputTokens": 12000, "temperature": 0.3},
            },
            timeout=180.0,
        )

        if reponse.status_code not in transitoires:
            break

        if tentative < 3:
            attente = 5 * (3 ** tentative)  # 5s, 15s, 45s
            print(
                f"  Gemini a répondu {reponse.status_code} — "
                f"nouvelle tentative dans {attente}s",
                flush=True,
            )
            time.sleep(attente)

    if reponse.status_code == 429:
        raise RuntimeError(
            "Quota Gemini dépassé (429), après 4 tentatives. Le tier gratuit autorise "
            "~1500 requêtes/jour ; ce pipeline en consomme 1 à 2. Vérifier qu'aucun "
            "autre projet ne partage la clé."
        )
    if reponse.status_code in transitoires:
        raise RuntimeError(
            f"Gemini indisponible ({reponse.status_code}) après 4 tentatives sur ~65s. "
            "Incident côté Google : la prochaine exécution planifiée reprendra les mêmes "
            "items, rien n'est perdu."
        )
    if reponse.status_code in (401, 403):
        raise RuntimeError(f"Clé Gemini refusée ({reponse.status_code}) : {reponse.text[:200]}")
    if reponse.status_code == 404:
        raise RuntimeError(
            f"Modèle « {config.MODELE_GEMINI} » introuvable. Les identifiants Gemini changent "
            "souvent : lancer `python -m veille.summarize --modeles-gemini` pour voir "
            "ceux que la clé peut appeler, puis ajuster VEILLE_MODELE_GEMINI dans le .env."
        )
    reponse.raise_for_status()

    donnees = reponse.json()
    candidats = donnees.get("candidates") or []
    if not candidats:
        raison = donnees.get("promptFeedback", {}).get("blockReason", "inconnue")
        raise RuntimeError(f"Gemini n'a renvoyé aucune réponse (raison : {raison}).")

    parts = candidats[0].get("content", {}).get("parts") or []
    # Les parties marquées "thought" sont du raisonnement interne, pas le digest.
    texte = "".join(p.get("text", "") for p in parts if not p.get("thought"))

    if not texte.strip():
        fin = candidats[0].get("finishReason", "inconnue")
        raise RuntimeError(
            f"Gemini a renvoyé une réponse vide (finishReason : {fin}). "
            "Si c'est MAX_TOKENS, augmenter maxOutputTokens."
        )
    return texte.strip()


def lister_modeles_gemini() -> list[str]:
    """Liste les modèles Gemini appelables avec la clé courante."""
    cle = os.getenv("GEMINI_API_KEY")
    if not cle:
        raise RuntimeError("GEMINI_API_KEY absente de l'environnement.")

    reponse = httpx.get(
        f"{_GEMINI_BASE}/models", headers={"x-goog-api-key": cle}, timeout=60.0
    )
    reponse.raise_for_status()

    return sorted(
        m["name"].removeprefix("models/")
        for m in reponse.json().get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    )


def _appeler(prompt: str) -> str:
    """Envoie le prompt au backend configuré."""
    backends = {"gemini": _resumer_gemini, "api": _resumer_api, "cli": _resumer_cli}
    if config.BACKEND not in backends:
        raise ValueError(
            f"VEILLE_BACKEND inconnu : {config.BACKEND} "
            f"(attendu {', '.join(sorted(backends))})"
        )
    return backends[config.BACKEND](prompt)


def resumer(items: list[dict], mode: str = "quotidien") -> str:
    """Produit le corps markdown du digest.

    Args:
        items: items collectés, déjà triés et dédoublonnés
        mode: "quotidien", "hebdo" ou "signets"
    """
    if not items:
        return "_Aucun élément nouveau sur la période._"
    return _appeler(construire_prompt(items, mode, limite=len(items)))


def developper(item: dict, contenu: str) -> str:
    """Développe un article : résumé complet et exemple d'usage, en markdown.

    Appelé à la demande depuis le site, un article à la fois — d'où un prompt qui ne
    ressemble à aucun autre : pas de liste, pas de tri, une seule ressource et tout son
    texte. Le contenu est lu par `enrichir`, jamais deviné à partir du titre.
    """
    lignes = [f"Titre : {item.get('titre', '')}", f"Source : {item.get('source_nom', '')}"]
    if item.get("date"):
        lignes.append(f"Date : {item['date']}")
    lignes.append(f"URL : {item.get('url', '')}")
    if item.get("extrait"):
        lignes.append(f"\nExtrait collecté :\n{item['extrait']}")
    lignes.append(f"\nContenu de la page :\n{contenu or '(non récupéré)'}")

    prompt = (
        f"Tu produis une veille IA personnelle pour ce profil :\n\n{config.PROFIL}\n\n"
        f"{CONSIGNES_DEVELOPPER}\n\n"
        f"Voici l'article :\n\n" + "\n".join(lignes)
    )
    return _appeler(prompt).strip()


_SENTINELLE = "<<<SCORES>>>"

# Taille des lots de notation. La sortie fait ~18 caractères par item : à 80, on reste
# très loin du plafond de tokens, même avec le raisonnement interne du modèle.
LOT_TRI = 80


def _appliquer_scores(fragment: str, items: list[dict]) -> int:
    """Lit un tableau JSON de scores et annote les items. Renvoie le nombre attribué."""
    debut, fin = fragment.find("["), fragment.rfind("]")
    if debut == -1 or fin <= debut:
        print("  Bloc de scores illisible — items non notés.", flush=True)
        return 0

    try:
        notes = json.loads(fragment[debut : fin + 1])
    except json.JSONDecodeError as e:
        print(f"  Scores non parsables ({e}) — items non notés.", flush=True)
        return 0

    attribues = 0
    for note in notes:
        if not isinstance(note, dict):
            continue
        indice, score = note.get("i"), note.get("s")
        if not isinstance(indice, int) or not isinstance(score, (int, float)):
            continue
        if not 0 <= indice < len(items):
            continue  # le modèle a inventé un numéro
        items[indice]["score"] = round(min(max(float(score), 0.0), 1.0), 2)
        attribues += 1
    return attribues


def noter(items: list[dict]) -> int:
    """Note tous les items, sans produire de texte. Annote en place.

    Passe de tri, à faire **avant** tout enrichissement : juger la pertinence ne demande
    que le titre et le lien. Sur un premier import de signets, cela évite d'aller chercher
    le contenu de centaines de pages dont la plupart seront écartées.
    """
    attribues = 0
    for debut in range(0, len(items), LOT_TRI):
        lot = items[debut : debut + LOT_TRI]
        attribues += _appliquer_scores(
            _appeler(construire_prompt(lot, "tri", limite=len(lot))), lot
        )
        print(f"  {min(debut + LOT_TRI, len(items))}/{len(items)} triés", flush=True)
    return attribues


def _extraire_scores(texte: str, items: list[dict]) -> str:
    """Détache le bloc de scores du digest et annote les items en place.

    Le bloc est demandé **après** le digest, et c'est délibéré : si la réponse est
    tronquée, on perd les scores et pas le texte. Toute anomalie de format est donc
    traitée comme une dégradation acceptable — les items restent sans note, le site
    les affiche tous — jamais comme une erreur qui ferait échouer le run.

    Returns:
        le digest seul, débarrassé du bloc de scores.
    """
    if _SENTINELLE not in texte:
        print("  Aucun bloc de scores dans la réponse — items non notés.", flush=True)
        return texte.strip()

    digest, _, queue = texte.partition(_SENTINELLE)
    digest = digest.strip()

    attribues = _appliquer_scores(queue, items)
    manquants = len(items[:MAX_ITEMS]) - attribues
    print(
        f"  {attribues} items notés"
        + (f", {manquants} sans note" if manquants > 0 else ""),
        flush=True,
    )
    return digest


def resumer_et_noter(items: list[dict], mode: str = "quotidien") -> str:
    """Produit le digest et attribue un score à chaque item, annoté en place.

    Un seul appel au modèle : le score est demandé dans la même réponse que le digest,
    donc sans requête ni quota supplémentaires.
    """
    digest = resumer(items, mode)
    return _extraire_scores(digest, items) if items else digest


def _charger_items(chemin: str) -> list[dict]:
    """Recharge des items depuis un JSON (dates réhydratées)."""
    items = json.loads(open(chemin, encoding="utf-8").read())
    for it in items:
        if it.get("date"):
            it["date"] = datetime.fromisoformat(it["date"])
    return items


if __name__ == "__main__":
    import argparse

    parseur = argparse.ArgumentParser(
        description="Teste l'étage de résumé sur un lot d'items déjà collecté."
    )
    parseur.add_argument(
        "--from",
        dest="source",
        default=str(config.FICHIER_DERNIERS_ITEMS),
        help="JSON produit par run_daily.py",
    )
    parseur.add_argument("--mode", choices=["quotidien", "hebdo"], default="quotidien")
    parseur.add_argument(
        "--modeles-gemini",
        action="store_true",
        help="liste les modèles Gemini appelables avec la clé courante, puis quitte",
    )
    args = parseur.parse_args()

    if args.modeles_gemini:
        for nom in lister_modeles_gemini():
            marque = "  <- configuré" if nom == config.MODELE_GEMINI else ""
            print(f"  {nom}{marque}")
        raise SystemExit(0)

    lot = _charger_items(args.source)
    print(f"Backend : {config.BACKEND} | {len(lot)} items\n", flush=True)
    print(resumer(lot, args.mode))
